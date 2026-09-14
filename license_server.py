import argparse
import hashlib
import html
import json
import os
import secrets
import ssl
import time
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from create_offline_license import create_license_document


DEFAULT_TOKEN = "ACCESS3H"
DEFAULT_LEASE_SECONDS = 3 * 60 * 60
DEFAULT_STORE = "license_tokens.json"
DEFAULT_PRIVATE_KEY = "license_private.pem"


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_store(path):
    if not os.path.exists(path):
        initial_token = os.environ.get("STEALTH_INITIAL_TOKEN", DEFAULT_TOKEN)
        store = {
            token_hash(initial_token): {
                "created_at": int(time.time()),
                "expires_at": None,
            }
        }
        save_store(path, store)
        return store

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def save_store(path, store):
    temporary_path = path + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as file:
        json.dump(store, file, indent=2)
    os.replace(temporary_path, path)


def create_token(path, duration):
    token = secrets.token_urlsafe(24)
    store = load_store(path)
    store[token_hash(token)] = {
        "created_at": int(time.time()),
        "expires_at": None,
        "duration": duration,
    }
    save_store(path, store)
    print(token)


def activate_token(path, token, duration):
    store = load_store(path)
    record = store.get(token_hash(token))

    if record is None:
        return {"valid": False, "error": "Invalid token."}

    now = int(time.time())
    expires_at = record.get("expires_at")

    if expires_at is None:
        expires_at = now + int(record.get("duration", duration))
        record["expires_at"] = expires_at
        save_store(path, store)
    elif now >= expires_at:
        return {"valid": False, "error": "Token expired."}

    return {"valid": True, "expires_at": expires_at}


class LicenseHandler(BaseHTTPRequestHandler):
    store_path = DEFAULT_STORE
    lease_seconds = DEFAULT_LEASE_SECONDS
    admin_username = None
    admin_password = None
    private_key_path = DEFAULT_PRIVATE_KEY
    private_key_pem = None
    secure_cookies = True
    sessions = set()

    def send_page(self, status, body, content_type="text/html; charset=utf-8"):
        body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_form(self):
        length = int(self.headers.get("Content-Length", "0"))
        from urllib.parse import parse_qs
        return parse_qs(self.rfile.read(length).decode("utf-8"))

    def authenticated(self):
        jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        session = jar.get("license_admin_session")
        return session is not None and session.value in self.sessions

    def request_is_secure(self):
        cloudflare_visitor = self.headers.get("Cf-Visitor", "")
        return (
            self.secure_cookies
            or self.headers.get("X-Forwarded-Proto", "").lower() == "https"
            or '"scheme":"https"' in cloudflare_visitor.replace(" ", "")
        )

    def admin_page(self, message=""):
        notice = f"<p>{html.escape(message)}</p>" if message else ""
        return f"""<!doctype html>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>License generator</title>
<style>body{{font:16px system-ui;max-width:34rem;margin:3rem auto;padding:0 1rem}}label{{display:block;margin-top:1rem}}input,button{{box-sizing:border-box;width:100%;padding:.75rem;font:inherit}}button{{margin-top:1.25rem}}</style>
<h1>Create license</h1>{notice}
<form method="post" action="/admin/create">
<label>Customer<input name="customer" required maxlength="200"></label>
<label>Duration (hours)<input name="hours" type="number" min="0.1" max="87600" step="0.1" value="720" required></label>
<label>Machine ID (optional)<input name="machine_id" maxlength="200"></label>
<button type="submit">Create License</button>
</form>"""

    def do_GET(self):
        if self.path == "/healthz":
            self.send_page(200, "ok", "text/plain; charset=utf-8")
            return

        if self.path == "/admin":
            if self.authenticated():
                self.send_page(200, self.admin_page())
            else:
                self.send_page(200, """<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><title>Admin login</title><style>body{font:16px system-ui;max-width:24rem;margin:3rem auto;padding:0 1rem}input,button{box-sizing:border-box;width:100%;padding:.75rem;margin-top:.5rem;font:inherit}button{margin-top:1rem}</style><h1>Admin login</h1><form method="post" action="/admin/login"><label>Username<input name="username" required autocomplete="username"></label><label>Password<input name="password" type="password" required autocomplete="current-password"></label><button>Log in</button></form>""")
            return
        self.send_error(404)

    def do_POST(self):
        if self.path == "/admin/login":
            form = self.read_form()
            username = form.get("username", [""])[0]
            password = form.get("password", [""])[0]
            if secrets.compare_digest(username, self.admin_username) and secrets.compare_digest(password, self.admin_password):
                session = secrets.token_urlsafe(32)
                self.sessions.add(session)
                self.send_response(303)
                self.send_header("Location", "/admin")
                secure = "; Secure" if self.request_is_secure() else ""
                self.send_header("Set-Cookie", f"license_admin_session={session}; HttpOnly{secure}; SameSite=Lax; Path=/")
                self.end_headers()
            else:
                self.send_page(401, self.admin_page("Invalid credentials."))
            return

        if self.path == "/admin/create":
            if not self.authenticated():
                self.send_error(403)
                return
            form = self.read_form()
            customer = form.get("customer", [""])[0].strip()
            machine_id = form.get("machine_id", [""])[0].strip() or None
            try:
                hours = float(form.get("hours", [""])[0])
                if not customer or not 0.1 <= hours <= 87600:
                    raise ValueError
                document = create_license_document(
                    customer,
                    hours,
                    self.private_key_path,
                    machine_id,
                    self.private_key_pem,
                )
                body = json.dumps(document, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", "attachment; filename=license.lic")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (ValueError, OSError):
                self.send_page(400, self.admin_page("Enter a valid customer and duration."))
            return

        if self.path == "/activate":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                token = str(payload.get("token", "")).strip()
                response = activate_token(self.store_path, token, self.lease_seconds)
                body = json.dumps(response).encode("utf-8")
                self.send_response(200 if response["valid"] else 403)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (ValueError, json.JSONDecodeError):
                self.send_error(400, "Invalid JSON request.")
            return

        self.send_error(404)

    def log_message(self, format_string, *args):
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--create-token", action="store_true")
    parser.add_argument("--hours", type=float, default=3)
    parser.add_argument("--admin-username", default=os.environ.get("LICENSE_ADMIN_USERNAME"))
    parser.add_argument("--admin-password", default=os.environ.get("LICENSE_ADMIN_PASSWORD"))
    parser.add_argument("--private-key", default=DEFAULT_PRIVATE_KEY)
    parser.add_argument("--tls-cert")
    parser.add_argument("--tls-key")
    args = parser.parse_args()

    duration = int(args.hours * 60 * 60)

    if args.create_token:
        create_token(args.store, duration)
        return

    load_store(args.store)
    LicenseHandler.store_path = args.store
    LicenseHandler.lease_seconds = duration
    if not args.admin_username or not args.admin_password:
        parser.error("--admin-username/--admin-password or LICENSE_ADMIN_USERNAME/LICENSE_ADMIN_PASSWORD are required")
    if bool(args.tls_cert) != bool(args.tls_key):
        parser.error("--tls-cert and --tls-key must be provided together")
    LicenseHandler.admin_username = args.admin_username
    LicenseHandler.admin_password = args.admin_password
    LicenseHandler.private_key_path = args.private_key
    LicenseHandler.private_key_pem = os.environ.get("LICENSE_PRIVATE_KEY_PEM")
    LicenseHandler.secure_cookies = bool(args.tls_cert)
    server = ThreadingHTTPServer((args.host, args.port), LicenseHandler)
    scheme = "https" if args.tls_cert else "http"
    if args.tls_cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.tls_cert, args.tls_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"License server listening on {scheme}://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

import argparse
import base64
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization


def canonical_payload(payload):
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def create_license_document(
    customer,
    hours,
    private_key_path,
    machine_id=None,
    private_key_pem=None,
):
    issued_at = int(time.time())
    expires_at = issued_at + int(hours * 60 * 60)
    payload = {
        "license_id": str(uuid.uuid4()),
        "customer": customer,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "expires_utc": datetime.fromtimestamp(
            expires_at,
            timezone.utc,
        ).isoformat(),
    }

    if machine_id:
        payload["machine_id"] = machine_id

    key_bytes = (
        private_key_pem.replace("\\n", "\n").encode("ascii")
        if private_key_pem
        else Path(private_key_path).read_bytes()
    )
    private_key = serialization.load_pem_private_key(
        key_bytes,
        password=None,
    )
    signature = private_key.sign(canonical_payload(payload))
    return {
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer", required=True)
    parser.add_argument("--hours", type=float, default=3)
    parser.add_argument("--machine-id")
    parser.add_argument("--private-key", default="license_private.pem")
    parser.add_argument("--output", default="license.lic")
    args = parser.parse_args()

    license_document = create_license_document(
        args.customer,
        args.hours,
        args.private_key,
        args.machine_id,
    )

    Path(args.output).write_text(
        json.dumps(license_document, indent=2),
        encoding="utf-8",
    )
    print(f"Created {args.output}")
    print(f"Expires: {license_document['payload']['expires_utc']}")


if __name__ == "__main__":
    main()

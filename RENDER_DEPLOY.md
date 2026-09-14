# Render Deployment

Deploy this as a Render Python web service from a private GitHub repository.

## Files To Keep Local

Do not commit or upload these files:

- `license_private.pem`
- `license.lic`
- `license_tokens.json`
- `token_config.txt`
- `.env`

The `.gitignore` also excludes local build output, browser profile data, screenshots, the virtual environment, and `cloudflared.exe`.

## Render Settings

If you use the included `render.yaml`, Render will use:

- Build command: `pip install -r requirements.txt`
- Start command: `python license_server.py --host 0.0.0.0`
- Health check path: `/healthz`

Set these Render environment variables before the first deploy:

- `LICENSE_ADMIN_USERNAME`
- `LICENSE_ADMIN_PASSWORD`
- `LICENSE_PRIVATE_KEY_PEM`
- `STEALTH_INITIAL_TOKEN`

For `LICENSE_PRIVATE_KEY_PEM`, paste the full private key PEM. Multiline PEM text and `\n`-escaped PEM text are both supported.

After deployment, open:

```text
https://<your-render-service>.onrender.com/admin
```

The phone tunnel and `cloudflared.exe` are no longer needed once the Render URL is live.

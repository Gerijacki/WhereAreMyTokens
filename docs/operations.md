# Running WhereAreMyTokens

## Who can reach it

Compose publishes the dashboard on `127.0.0.1` only. To use it from other computers, set `WAMT_BIND=0.0.0.0` (or a
specific address such as your Tailscale IP) in `.env`, **and** protect it with one of:

- `WAMT_AUTH_PASSWORD` (or a password set in *Settings → Security*). Logins are limited to
  `WAMT_LOGIN_MAX_ATTEMPTS` wrong passwords per IP (default 5), then locked for 15 minutes.
- An authenticating reverse proxy (Authelia, oauth2-proxy, Cloudflare Access) plus
  `WAMT_TRUST_PROXY_AUTH_HEADER` and `WAMT_TRUSTED_PROXY_IPS`.

Without any of these the server logs a warning at startup: anyone who can reach the port can read your usage data,
create device tokens and set the password.

`/metrics` follows the same rule: with a password set it needs the dashboard session, or give your scraper
`WAMT_METRICS_TOKEN` and `Authorization: Bearer <token>`.

## Behind a reverse proxy with TLS

Terminate TLS at the proxy and keep WAMT on a private address. Set `WAMT_COOKIE_SECURE=true` so the session cookie is
only sent over HTTPS, and `WAMT_PUBLIC_URL` for alert links.

**Caddy**

```
wamt.example.com {
    reverse_proxy 127.0.0.1:8787
}
```

**nginx**

```nginx
server {
    listen 443 ssl;
    server_name wamt.example.com;
    # ssl_certificate ... ssl_certificate_key ...
    client_max_body_size 25m;                       # matches WAMT_MAX_BODY_MB
    add_header Strict-Transport-Security "max-age=31536000" always;
    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header Remote-User "";            # never pass the client's copy of the auth header
    }
}
```

With an authenticating proxy, set the user header there (for example `Remote-User`), put the proxy's address in
`WAMT_TRUSTED_PROXY_IPS`, and make sure the WAMT port is not reachable except through the proxy. The proxy must
overwrite or strip that header on every request.

## Backup and restore

The database is the only copy of your history once Claude Code deletes old transcripts, so back it up.

**PostgreSQL (compose)**

```bash
docker compose exec -T db pg_dump -U wamt wamt | gzip > wamt-$(date +%F).sql.gz        # backup
docker compose stop wamt
gunzip -c wamt-2026-01-01.sql.gz | docker compose exec -T db psql -U wamt -d wamt         # restore into an empty DB
docker compose start wamt
```

To restore into a database that already has tables, drop and recreate it first:
`docker compose exec db psql -U wamt -d postgres -c 'DROP DATABASE wamt' -c 'CREATE DATABASE wamt OWNER wamt'`.

**SQLite (single container)**

```bash
docker compose stop wamt   # or: docker stop wamt
docker run --rm -v wamt-data:/data -v "$PWD":/backup alpine cp /data/wamt/wamt.db /backup/wamt.db   # backup
# restore: copy the file back to the same place while the container is stopped, then start it
```

## Upgrading

```bash
git pull && docker compose up -d --build        # or: docker compose pull && docker compose up -d
```

Schema migrations run automatically at startup. Back up first. When a release changes how transcripts are parsed,
WAMT re-reads them on its own without deleting anything.

## Data retention

WAMT never deletes usage data by design, because Claude Code removes old transcripts and your database may be the
only copy. To drop everything, remove the database volume (`docker compose down -v`).

# Deploy runbook — intro.loefbijter.nl

Same EC2 instance as the main loefbijter.nl WordPress site. Host Apache
terminates TLS (existing Let's Encrypt cert) and reverse-proxies to the
Docker Compose stack, which is otherwise identical in dev and prod.

## Prerequisites (once, on the EC2 instance)

- Docker + the Compose plugin installed (`docker compose version` works).
- DNS: an A record for `intro.loefbijter.nl` pointing at the instance.
- Port `8080` free on loopback — verify: `sudo ss -ltnp | grep 8080`.
- A Git remote the server can pull from (this repo's GitHub remote).
- Apache modules enabled: `sudo a2enmod proxy proxy_http headers ssl rewrite`.
- A Let's Encrypt certificate covering `intro.loefbijter.nl` (either a SAN
  cert shared with the main site, or a separate `certbot` run for this
  subdomain — either way, point `deploy/intro.loefbijter.nl.conf`'s
  `SSLCertificateFile`/`SSLCertificateKeyFile` at wherever it lands).

## First deploy

1. Clone the repo:
   ```
   sudo git clone <repo-url> /opt/intro-loefbijter
   cd /opt/intro-loefbijter
   ```
2. Create the prod `.env`:
   ```
   cp .env.example .env
   ```
   Then edit `.env`:
   - `SECRET_KEY` — generate a real one:
     `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`
   - `DEBUG=False`
   - `ALLOWED_HOSTS=intro.loefbijter.nl`
   - `CSRF_TRUSTED_ORIGINS=https://intro.loefbijter.nl`
   - Uncomment `COMPOSE_FILE=docker-compose.yml` — this is the line that
     keeps `docker-compose.override.yml` (dev-only: bind mounts, `DEBUG=True`,
     `runserver`) from silently applying on the server. Leaving it commented
     out here would defeat `DEBUG=False` above and expose the Django dev
     server instead of gunicorn.
   - Do **not** set `COMPOSE_PROFILES=build` (that's a dev-only convenience
     so `make dev` includes the frontend's dev server — see `DECISIONS.md`).
3. Build images and produce the static frontend build:
   ```
   make build
   ```
   (Runs `docker compose build` then the one-shot
   `docker compose --profile build run --rm frontend`, which builds the
   Astro site and copies `dist/` into the `web_dist` volume nginx serves.)
4. Start the backend + nginx (not the one-shot frontend builder):
   ```
   make up
   ```
5. Run migrations if `entrypoint.sh` hasn't already (it runs `migrate` on
   every backend start, so this is normally redundant, but useful to confirm):
   ```
   make migrate
   ```
6. Create the board's admin login:
   ```
   make superuser
   ```
7. Install the Apache vhost:
   ```
   sudo cp deploy/intro.loefbijter.nl.conf /etc/apache2/sites-available/
   sudo a2ensite intro.loefbijter.nl.conf
   sudo apache2ctl configtest
   sudo systemctl reload apache2
   ```
8. **Smoke test over HTTPS** (see checklist below).

## Redeploys

```
git pull
make build
make up
```

`make build` only rebuilds images/layers that actually changed, and `make up`
recreates only the containers whose config or image changed — backend/web
stay up. Copy changes (hardcoded frontend text) go through the exact same
flow: edit, commit, `git pull` on the server, `make build && make up`.

## Smoke test checklist

Run this after every deploy, not just the first one:

- [ ] `https://intro.loefbijter.nl/` loads the static homepage.
- [ ] `https://intro.loefbijter.nl/admin/` shows the Django admin login page
      and accepts the board's credentials.
- [ ] A full registration round-trip works: pick a published, open activity,
      submit the form, confirm the "bevestigd" or "wachtlijst" message.
- [ ] Submitting the same email again for the same activity is rejected with
      the duplicate-email Dutch error.
- [ ] `/api/activities/` does **not** include unpublished activities or any
      registration data.

## Backups

Registrations are irreplaceable — there's no email trail and no external
system holding a copy. Nightly, via host cron:

```
0 3 * * * cd /opt/intro-loefbijter && make backup
```

`make backup` runs SQLite's own `.backup` command (safe against a live
WAL-mode database, unlike copying the file directly) into the `db` volume as
`backup-YYYY-MM-DD.sqlite3`. That alone isn't sufficient — a volume backup
sitting next to the live database doesn't survive an instance loss. Add a
second cron step (or extend `make backup`) to copy the dated backup file off
the volume and off-instance, e.g. to S3:

```
docker run --rm -v intro-loefbijter_db:/data -v /opt/backups:/out alpine \
  cp /data/backup-$(date +%F).sqlite3 /out/
aws s3 cp /opt/backups/backup-$(date +%F).sqlite3 s3://<bucket>/intro-loefbijter/
```

Keep 14 days locally (and per your S3 lifecycle policy). If activity images
matter, back up the `media` volume the same way.

## Retention purge (weekly cron)

```
0 4 * * 0 cd /opt/intro-loefbijter && make purge
```

Deletes registrations older than `RETENTION_DAYS` (`.env`, default 30) —
see SPEC §7. This is the site's only data-retention mechanism since no
emails are ever sent and there's no self-service cancellation.

## Troubleshooting

- **502 from Apache**: check `docker compose ps` — is `web` up? Is `backend`
  up (nginx proxies `/api/` and `/admin/` to it)? `docker compose logs web`
  / `docker compose logs backend`.
- **Static assets 404 under `/django-static/`**: `collectstatic` runs as
  part of `entrypoint.sh` on every backend start (skipped only when
  `DEBUG=True`, which prod's `.env` shouldn't set) — check backend logs for
  a failed `collectstatic` step.
- **Rate limiting blocking everyone from one IP, or not blocking abusive
  traffic at all**: the client IP for rate limiting is derived from
  `X-Forwarded-For` via `activities/api.py`'s `client_ip_key`, configured for
  *this exact* Apache→nginx→gunicorn chain (see DECISIONS.md, milestone 7,
  for why that's `proxy_count=1` and not the more obvious-looking `2`). If
  another hop is ever added in front (a CDN, a load balancer, another
  reverse proxy), that value needs to change too — get it wrong in either
  direction and rate limiting either blocks every visitor as one shared IP,
  or can be bypassed entirely by an attacker forging their own
  `X-Forwarded-For` header.

# Deploy runbook — intro.loefbijter.nl

Same EC2 instance as the main loefbijter.nl WordPress site. The site sits
**behind Cloudflare**, so the real request chain is four hops:

    Cloudflare → Apache (:443) → nginx (127.0.0.1:8080) → gunicorn (backend:8000)

- **Cloudflare** terminates TLS for the visitor and re-encrypts to the origin.
  SSL mode is **Full (strict)**: Cloudflare validates the origin's certificate,
  so the origin Apache must serve a valid, unexpired Let's Encrypt cert at all
  times — a broken/expired origin cert is a hard outage (Cloudflare 526), not a
  silent warning.
- **Apache** runs `mod_remoteip` to recover the true visitor IP from
  Cloudflare's `CF-Connecting-IP` header, then thin-proxies to nginx.
- **nginx** (in Compose) serves the static build and proxies `/api/` + `/admin/`
  to gunicorn.

DNS `intro.loefbijter.nl` resolves to **Cloudflare** IPs, not the instance.

## Prerequisites (once, on the EC2 instance)

- Docker + the Compose plugin installed (`docker compose version` works).
- Cloudflare DNS: `intro.loefbijter.nl` proxied (orange cloud), SSL/TLS mode
  **Full (strict)**, and the cache rules in "Cloudflare configuration" below.
- Port `8080` free on loopback — verify: `sudo ss -ltnp | grep 8080`.
- A Git remote the server can pull from (this repo's GitHub remote).
- Apache modules enabled:
  `sudo a2enmod proxy proxy_http headers ssl rewrite remoteip`.
- **certbot must be the snap binary** at `/snap/bin/certbot`. An old pip install
  at `/usr/local/bin/certbot` fails with an Augeas error on this host. Check
  with `which -a certbot`; use the full `/snap/bin/certbot` path in commands and
  cron to avoid picking up the broken one.
- The certificate is issued **after** the HTTP-only vhost is in place (see
  below) — it is not a pre-req, and trying to make it one creates a circular
  dependency (the TLS vhost references a cert that doesn't exist yet, so
  `configtest` fails, so `certbot --apache` refuses to run).

## Pre-flight (before touching any vhost or cert)

Multiple vhosts on this host may share one certificate. Deleting a cert or
breaking a vhost takes down **configtest for every site**, after which Apache
can't reload and won't survive a reboot. Before editing:

```
grep -RE 'SSLCertificateFile|ServerName' /etc/apache2/sites-enabled/
sudo apache2ctl configtest
```

Note `-R` (recursive), **not** `-r`: `sites-enabled/` holds symlinks, which `-r`
skips. Confirm which cert files are referenced by which sites, and that
`configtest` is already clean, before changing anything.

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
   - Uncomment `COMPOSE_FILE=docker-compose.yml` — this keeps
     `docker-compose.override.yml` (dev-only: bind mounts, `DEBUG=True`,
     `runserver`) from silently applying on the server. Leaving it commented
     out would defeat `DEBUG=False` and expose the Django dev server instead of
     gunicorn.
   - Do **not** set `COMPOSE_PROFILES=build` (dev-only convenience so `make dev`
     includes the frontend's dev server — see `DECISIONS.md`).
3. Build images and produce the static frontend build:
   ```
   make build
   ```
   (Runs `docker compose build` then the one-shot
   `docker compose --profile build run --rm frontend`, which builds the Astro
   site and copies `dist/` into the `web_dist` volume nginx serves.)
4. Start the backend + nginx (not the one-shot frontend builder):
   ```
   make up
   ```
5. Create the board's admin login:
   ```
   make superuser
   ```
   (`entrypoint.sh` already runs `migrate` + `collectstatic` on every backend
   start, so no separate migrate step is needed.)

### Certificate + Apache (correct order — do not reorder)

The order matters: an HTTP-only vhost must exist first so the ACME webroot
challenge can be served, **then** the cert is issued, **then** the TLS vhost
(which references the now-existing cert) is enabled.

6. Install the vhost file but enable **only** HTTP first. The vhost file has
   both an `*:80` and an `*:443` block; enable the site with the `:443` block
   commented out for now (or temporarily comment it), so `configtest` passes
   without the not-yet-existing cert:
   ```
   sudo cp deploy/intro.loefbijter.nl.conf /etc/apache2/sites-available/
   # temporarily comment out the <VirtualHost *:443> block, then:
   sudo a2ensite intro.loefbijter.nl.conf
   sudo apache2ctl configtest && sudo systemctl reload apache2
   ```
   The `*:80` block serves `/.well-known/acme-challenge/` from `/var/www/html`
   via an `Alias`, and redirects everything else to HTTPS **except** that path.
   Make sure `/var/www/html` exists.
7. Issue the cert with the **webroot** plugin (not `--apache`):
   ```
   sudo /snap/bin/certbot certonly --webroot -w /var/www/html \
     -d intro.loefbijter.nl
   ```
   Webroot keeps renewals decoupled from Apache's config: the permanent `*:80`
   Alias serves the challenge, so certbot never needs to rewrite a vhost.
8. Now uncomment the `<VirtualHost *:443>` block (it references
   `/etc/letsencrypt/live/intro.loefbijter.nl/`), and reload:
   ```
   sudo apache2ctl configtest && sudo systemctl reload apache2
   ```
9. Install the renewal deploy hook (see "Certificate renewal" — mandatory under
   Full (strict)).
10. Point Cloudflare at the origin and set SSL mode + cache rules (see
    "Cloudflare configuration"), then run the smoke test.

## Redeploys

```
git pull
make build
make up
```

`make build` only rebuilds changed layers; `make up` recreates only the
containers whose config/image changed. Copy changes (hardcoded frontend text)
follow the same flow. Redeploys don't touch Apache or the cert.

**Purge Cloudflare's cache** for the static site after a redeploy that changes
the build (Astro output filenames are content-hashed, so `index.html` is the
one file that must not serve stale — the cache rules below mark it
non-cacheable, but a manual "Purge Everything" after a big change is cheap
insurance).

## Cloudflare configuration

Dashboard settings (not code). Registrations must never read a stale capacity
count from an edge cache, and the admin must never be cached at all.

**SSL/TLS → Overview:** mode **Full (strict)**.

**Caching → Cache Rules** — create two rules, ordered so the bypass wins:

1. **Bypass dynamic** (evaluate first):
   - When incoming requests match: `URI Path starts with "/api/"` **OR**
     `URI Path starts with "/admin/"`
   - Then: **Bypass cache**.
2. **Cache static** (default for everything else):
   - The static Astro build (hashed `/_astro/*` assets, images) is safe to edge
     cache. Either leave Cloudflare's default caching on, or add an explicit
     "Eligible for cache" rule for the rest. Do **not** cache `/index.html`
     (it's the entry point that must reflect the current build) — Cloudflare
     doesn't cache bare HTML by default, so no rule is usually needed, but if a
     rule force-caches HTML, exclude `/` and `*.html`.

**Verify** the split with `cf-cache-status` response headers:

```
# A static hashed asset SHOULD be cacheable (HIT after a warm-up request, or
# MISS then HIT):
curl -sI https://intro.loefbijter.nl/_astro/<some-hashed-file>.css | grep -i cf-cache-status
# → cf-cache-status: HIT   (or MISS on first request, HIT on the second)

# An API request MUST bypass the cache:
curl -sI https://intro.loefbijter.nl/api/activities/ | grep -i cf-cache-status
# → cf-cache-status: DYNAMIC   (or BYPASS) — never HIT
```

If `/api/activities/` ever shows `cf-cache-status: HIT`, capacity counts can go
stale and the bypass rule is misconfigured — fix before taking registrations.

## Smoke test checklist

Run after every deploy, not just the first. (In zsh, inline `#` comments break a
command line unless `setopt interactive_comments`; either set that or drop the
comments.)

- [ ] `curl -sI https://intro.loefbijter.nl/ | head -1` → `HTTP/2 200`.
- [ ] Origin is serving the cert you think it is (issuing a cert does **not**
      reload Apache):
      ```
      echo | openssl s_client -connect 127.0.0.1:443 -servername intro.loefbijter.nl \
        2>/dev/null | openssl x509 -noout -dates
      ```
      `notAfter` should be ~90 days out, not an old date.
- [ ] `sudo /snap/bin/certbot renew --dry-run` is fully clean.
- [ ] `https://intro.loefbijter.nl/admin/` shows the Django admin login and
      accepts the board's credentials.
- [ ] A full registration round-trip works (submit → "bevestigd"/"wachtlijst"),
      and a duplicate email for the same activity is rejected in Dutch.
- [ ] `cf-cache-status` checks above pass (`/api/*` bypassed, static cacheable).
- [ ] `/api/activities/` includes no unpublished activities or personal data.

## Certificate renewal

certbot's snap timer renews automatically. Two things make it reliable here:

1. **Webroot + the permanent `*:80` Alias** (in the vhost) mean renewals never
   touch Apache's config.
2. **A deploy hook that reloads Apache after renewal is mandatory under Full
   (strict).** certbot writes the renewed cert to disk but does not reload
   Apache, so Apache keeps serving the *old* cert from memory. Once the old cert
   expires, Cloudflare (validating the origin in strict mode) rejects it and the
   site goes hard-down with a **526** — even though a valid cert is sitting on
   disk. The hook closes that gap:

   Create `/etc/letsencrypt/renewal-hooks/deploy/reload-apache.sh`:
   ```sh
   #!/bin/sh
   systemctl reload apache2
   ```
   ```
   sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-apache.sh
   ```
   Every successful renewal now reloads Apache. Confirm with
   `sudo /snap/bin/certbot renew --dry-run` (the hook runs on real renewals; the
   dry run confirms the whole path is clean).

## Backups

Registrations are irreplaceable — there's no email trail and no external system
holding a copy. Nightly, via host cron:

```
0 3 * * * cd /opt/intro-loefbijter && make backup
```

`make backup` runs SQLite's own `.backup` (safe against a live WAL-mode
database) into the `db` volume as `backup-YYYY-MM-DD.sqlite3`. That alone isn't
enough — a backup next to the live DB doesn't survive instance loss. Copy the
dated file off the volume and off-instance, e.g. to S3:

```
docker run --rm -v intro-loefbijter_db:/data -v /opt/backups:/out alpine \
  cp /data/backup-$(date +%F).sqlite3 /out/
aws s3 cp /opt/backups/backup-$(date +%F).sqlite3 s3://<bucket>/intro-loefbijter/
```

Keep 14 days locally. If activity images matter, back up the `media` volume too.

## Retention purge (weekly cron)

```
0 4 * * 0 cd /opt/intro-loefbijter && make purge
```

Deletes registrations older than `RETENTION_DAYS` (`.env`, default 30) — see
SPEC §7. This is the site's only data-retention mechanism since no emails are
sent and there's no self-service cancellation.

## Troubleshooting

- **Cloudflare 526** (invalid SSL certificate): from Cloudflare's view the
  origin cert is invalid/expired. Usually the renewal deploy hook is missing, so
  Apache is serving an old cert from memory — reload Apache
  (`sudo systemctl reload apache2`) and verify with the `openssl s_client` check
  above. Also check the origin cert isn't actually expired.
- **Cloudflare 525** (SSL handshake failed): Cloudflare can't complete TLS to
  the origin — Apache `:443` down, no `SSLEngine`/cert on the vhost, or the
  vhost didn't load. `sudo apache2ctl configtest` and check `:443` is listening.
- **502 from the origin**: check `docker compose ps` — is `web` up? Is `backend`
  up (nginx proxies `/api/` and `/admin/` to it)? `docker compose logs web` /
  `docker compose logs backend`.
- **Static assets 404 under `/django-static/`**: `collectstatic` runs in
  `entrypoint.sh` on every backend start (skipped only when `DEBUG=True`, which
  prod's `.env` shouldn't set) — check backend logs for a failed step.
- **Rate limiting throttles everyone as one client, or does nothing**: the rate
  limit keys on the real visitor IP, which depends on Apache's `mod_remoteip`
  recovering it from Cloudflare's `CF-Connecting-IP`. If every visitor is
  bucketed together, `mod_remoteip` isn't active or its `RemoteIPTrustedProxy`
  list is stale/incomplete, so Django sees a Cloudflare edge IP instead of the
  client. Confirm `remoteip` is enabled (`a2enmod remoteip`) and refresh the
  Cloudflare ranges in the vhost from https://www.cloudflare.com/ips-v4 and
  https://www.cloudflare.com/ips-v6. (Client-IP resolution lives in
  `activities/api.py`'s `client_ip_key`, which reads the entry Apache appends to
  `X-Forwarded-For`; see `DECISIONS.md`.)
- **Stale capacity / registrations behaving oddly**: check
  `cf-cache-status: HIT` isn't appearing on `/api/*` (see Cloudflare
  configuration) — a cached API response would serve stale spot counts.

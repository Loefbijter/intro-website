# intro.loefbijter.nl — Build Specification (v3, final)

A fast, mostly-static intro/activities site for NSZV De Loefbijter, replacing the
WordPress `loefbijter.nl/intro` and `loefbijter.nl/voorjaarsintro` pages. This
document is the implementation brief for a coding agent (Claude Code). The site is
developed and tested locally in an IDE first, then ported to the production EC2.

---

## 1. Goals & constraints

- **Fast**: public pages are static HTML/CSS. No PHP, no WordPress.
- **Flexible**: board members create activities and manage registrations from the Django admin — no code changes or redeploys to add an activity.
- **Registration** with **capacity limits + waiting list** per activity.
- **Semi-flexible fields**: standard fields plus per-activity custom fields configured in the admin.
- **No duplicates**: the same email cannot register twice for the same activity (service-level check **and** DB constraint).
- **No emails** are sent anywhere. Consequences (decided with the client):
  - Waitlist promotion is **manual**: the board promotes people via an admin action and contacts them personally.
  - **No self-service cancellation**: registrants contact the board; the board cancels via the admin. There is **no public cancel endpoint and no cancel token**.
- **Payments on-site** — no payment integration; activities may show a cost note.
- **Single intro period**; the site is revamped per period. Keep the model simple.
- **Page text is hardcoded in Astro** (hero, intro paragraphs, WAZ block, locations, footer). Editing copy = edit + rebuild. Only **activities** are dynamic.
- **Brand, not pixel-perfect**: Loefbijter logo, colours, fonts; tidy standalone markup.
- **Docker Compose** end-to-end; identical stack in dev and prod, differing only via `.env` and a dev override file.
- **Hosting**: same EC2 as the WordPress site. Host Apache (existing Let's Encrypt TLS) acts only as a thin reverse proxy. Subdomain `intro.loefbijter.nl`.
- **Locale**: everything user-facing in **Dutch**; `TIME_ZONE="Europe/Amsterdam"`, `LANGUAGE_CODE="nl"` (Dutch admin + validation messages).

---

## 2. Architecture

```
Visitor
   │  HTTPS
   ▼
Cloudflare  (proxied DNS; terminates visitor TLS; SSL mode Full (strict))
   │  HTTPS to origin; sets CF-Connecting-IP = real visitor IP
   ▼
Host Apache  (intro.loefbijter.nl vhost; Let's Encrypt cert via webroot)
   │  mod_remoteip: RemoteIPHeader CF-Connecting-IP (trusts CF ranges only) → real client IP
   │  ProxyPass / → http://127.0.0.1:8080   (X-Forwarded-Proto + real-client X-Forwarded-For)
   ▼
┌───────────────────────── Docker Compose ─────────────────────────┐
│  web  (nginx, 127.0.0.1:8080→:80)                                 │
│   ├─ /                → static Astro build  (web_dist volume)     │
│   ├─ /django-static/  → Django admin assets (static volume)       │
│   ├─ /media/          → activity images     (media volume)        │
│   └─ /api/ , /admin/  → proxy → backend:8000 (forwards XFF/XFP)   │
│                                                                   │
│  backend  (Django + gunicorn, :8000)                             │
│   └─ SQLite (db volume, WAL) + media + collected static           │
│                                                                   │
│  frontend  (node, one-shot builder)                              │
│   └─ npm run build → web_dist volume, then exits                  │
└───────────────────────────────────────────────────────────────────┘
```

- **Frontend — Astro (static output).** All page content is static. The activities
  list + registration form are one client-side island calling the JSON API with
  **relative `/api` URLs only** (works identically in dev and prod), so new
  activities appear without a rebuild.
- **Backend — Django 5.x + Django REST Framework** under gunicorn.
- **Database — SQLite** in a named volume, WAL mode.

### SQLite concurrency — important correctness note

`select_for_update()` is **silently ignored on SQLite** — do not rely on it.
Correct approach:
- Wrap registration logic in `transaction.atomic()` and configure the SQLite
  connection for immediate write transactions so concurrent registrations
  serialize instead of failing mid-transaction:

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": env("DB_PATH", default="/data/db.sqlite3"),
        "OPTIONS": {
            "transaction_mode": "IMMEDIATE",   # Django 5.1+
            "timeout": 20,
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA busy_timeout=20000;",
        },
    }
}
```
- The `UniqueConstraint` (§4) remains the race-safe backstop for duplicates, and
  the capacity count inside the immediate transaction is safe because SQLite
  allows a single writer. If the club ever outgrows this, Postgres is a drop-in
  Compose service and `select_for_update` becomes meaningful again.

### Versions (pin these)

Python **3.12**, Django **5.1.x**, DRF latest stable, gunicorn latest stable,
Node **20 LTS**, Astro latest stable, nginx **alpine**. Pin in
`requirements.txt` / `package.json` and Dockerfile base images.

---

## 3. Repository layout

```
intro-loefbijter/
├─ docker-compose.yml            # prod-shaped base
├─ docker-compose.override.yml   # dev: DEBUG, bind mounts, hot reload (auto-applied)
├─ .env.example                  # all env vars documented
├─ Makefile                      # dev, build, deploy, backup, superuser targets
├─ frontend/
│  ├─ Dockerfile                 # multi-stage: node build → files to /output
│  ├─ src/
│  │  ├─ pages/index.astro
│  │  ├─ content/                # hardcoded copy: hero.md, waz.md, locations data
│  │  ├─ components/             # Hero, JumpNav, ActivityList, ActivityCard,
│  │  │                          # RegisterModal, Locations, Footer
│  │  ├─ lib/api.ts              # relative /api fetch helpers
│  │  └─ styles/tokens.css       # brand colours, fonts (see §8)
│  └─ astro.config.mjs           # dev server proxies /api → backend
├─ backend/
│  ├─ Dockerfile
│  ├─ entrypoint.sh              # migrate + collectstatic → gunicorn
│  ├─ config/                    # settings, urls, wsgi
│  ├─ activities/
│  │  ├─ models.py  admin.py  api.py  serializers.py  services.py
│  │  ├─ fixtures/sample_activities.json   # dev/test seed data
│  │  ├─ management/commands/purge_old_registrations.py
│  │  └─ tests/                  # pytest: services, API, constraints
│  ├─ manage.py
│  └─ requirements.txt
├─ deploy/
│  ├─ nginx.conf
│  ├─ intro.loefbijter.nl.conf   # host Apache thin-proxy vhost
│  └─ deploy.md                  # runbook incl. backups
└─ README.md                     # quickstart for dev + deploy
```

---

## 4. Data model (Django)

Two models only. Locations are hardcoded in the frontend, so `Activity` carries a
plain text location; no Location model, no cancel tokens.

```python
class Activity(models.Model):
    title = models.CharField(max_length=140)
    slug = models.SlugField(unique=True)
    date = models.DateField()
    time_text = models.CharField(max_length=120, blank=True)     # "21:00" / "12:00–18:00, BBQ 18:00"
    theme = models.CharField(max_length=120, blank=True)          # "Piraten & Zeemeerminnen"
    location_text = models.CharField(max_length=140, blank=True)  # "Het Bastion" / "Villa van Schaeck"
    description = models.TextField(blank=True)                    # markdown allowed
    image = models.ImageField(upload_to="activities/", blank=True)
    cost_note = models.CharField(max_length=120, blank=True)      # payments on-site

    requires_registration = models.BooleanField(default=True)     # False = "kom gewoon langs"
    external_registration_url = models.URLField(blank=True)       # e.g. bestaande Google Form / WAZ-link
    capacity = models.PositiveIntegerField(null=True, blank=True) # null = onbeperkt
    registration_opens_at = models.DateTimeField(null=True, blank=True)
    registration_closes_at = models.DateTimeField(null=True, blank=True)

    collect_phone = models.BooleanField(default=True)
    collect_study = models.BooleanField(default=True)
    collect_dietary = models.BooleanField(default=True)

    custom_fields = models.JSONField(default=list, blank=True)    # schema below

    is_published = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

class Registration(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Bevestigd"
        WAITLIST = "waitlist", "Wachtlijst"
        CANCELLED = "cancelled", "Geannuleerd"

    activity = models.ForeignKey(Activity, related_name="registrations", on_delete=models.CASCADE)
    name = models.CharField(max_length=140)
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    study = models.CharField(max_length=140, blank=True)
    dietary = models.CharField(max_length=255, blank=True)
    answers = models.JSONField(default=dict, blank=True)          # custom answers by field "key"
    status = models.CharField(max_length=12, choices=Status.choices)
    consent = models.BooleanField(default=False)                  # GDPR (§7)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["activity", "email"],
                condition=~models.Q(status="cancelled"),
                name="uniq_active_email_per_activity",
            ),
        ]
```

Normalise `email` to lowercase on save so the constraint can't be dodged by casing.

### Custom field schema (`Activity.custom_fields`)

JSON list configured per activity in the admin:

```json
[
  {"key": "tshirt_maat", "label": "T-shirt maat", "type": "select",
   "required": false, "options": ["S", "M", "L", "XL"]},
  {"key": "zeilervaring", "label": "Zeilervaring", "type": "text", "required": false}
]
```

`type` ∈ `text | textarea | select | checkbox | number`. The frontend renders these
after the standard fields; answers land in `Registration.answers`. **Validate the
schema on Activity save** (clear Dutch error if malformed) and **validate answers
server-side** against the schema on registration. In the admin, use a JSON widget
(e.g. a prettified textarea with the schema documented in `help_text`).

---

## 5. Django admin — the board's control panel

This is where "manual" workflows live, so make it good:

- **ActivityAdmin**: `list_display` (title, date, published, capacity, confirmed
  count, waitlist count), list filters, prepopulated slug, inline read-only
  registration summary.
- **RegistrationAdmin**: filters by activity + status, search by name/email,
  and admin **actions**:
  - **"Promoot naar bevestigd"** — moves selected waitlist registrations to
    confirmed. Warn (but allow, board's judgment) if this exceeds capacity.
  - **"Annuleer inschrijving"** — sets status to cancelled. **No auto-promotion**;
    the freed spot simply shows up in the counts and the board promotes whoever
    they choose, then contacts that person by phone/DM themselves.
  - **CSV-export** of selected registrations (all fields incl. custom answers).
- Superuser created manually on first deploy (`createsuperuser`); document in runbook.

---

## 6. API + registration service

DRF, read endpoints only expose `is_published=True` activities, never personal data.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/activities/` | Published activities with `spots_remaining`, `is_full`, `registration_open`, standard-field toggles, and `custom_fields` schema. |
| GET | `/api/activities/<slug>/` | Single activity. |
| POST | `/api/activities/<slug>/register/` | Create registration → returns `status` (`confirmed`/`waitlist`). Dutch error messages for: duplicate email, closed/not open, full form validation. |

That's all. No cancel endpoint, no token in responses.

`activities/services.py`:

```python
from django.db import transaction, IntegrityError

def register(activity_id, payload):
    with transaction.atomic():   # IMMEDIATE mode → single writer, counts are safe
        activity = Activity.objects.get(pk=activity_id)
        _validate(activity, payload)   # window open, requires_registration, no external URL,
                                       # consent given, honeypot empty, custom-field answers valid

        email = payload["email"].strip().lower()
        if activity.registrations.exclude(status="cancelled").filter(email=email).exists():
            raise DuplicateRegistration("Dit e-mailadres is al ingeschreven voor deze activiteit.")

        if activity.capacity is None:
            status = Registration.Status.CONFIRMED
        else:
            confirmed = activity.registrations.filter(status="confirmed").count()
            status = Registration.Status.CONFIRMED if confirmed < activity.capacity \
                     else Registration.Status.WAITLIST
        try:
            return Registration.objects.create(activity=activity, status=status,
                                               **{**payload, "email": email})
        except IntegrityError:
            raise DuplicateRegistration("Dit e-mailadres is al ingeschreven voor deze activiteit.")
```

Abuse protection on the register endpoint:
- **Rate limit by client IP** (`django-ratelimit`, e.g. 5/min). Because of the
  Apache→nginx→gunicorn chain, the client IP must come from `X-Forwarded-For`
  (see §9 — both proxies set/forward it; strip untrusted values at nginx).
- **Honeypot** hidden field — reject silently if filled.
- CSRF-exempt (same-origin static POST) but covered by the above + duplicate guard.

---

## 7. Privacy / GDPR (EU — required)

- Required **consent checkbox** linking to `https://loefbijter.nl/privacyverklaring/`.
- Dietary/allergy info is sensitive: optional, purpose stated ("voor de catering"),
  only collected when the toggle is on.
- **Retention**: `purge_old_registrations` management command deletes registrations
  older than `RETENTION_DAYS` (env, default **30**); run via host cron:
  `docker compose exec backend python manage.py purge_old_registrations`.
- Admin-only CSV export; no personal data in any public API response; no emails stored beyond the registration itself.

---

## 8. Frontend — Astro

Rebuild as clean, standalone, on-brand sections. Reference the live pages for
content and section order: `loefbijter.nl/voorjaarsintro` and `loefbijter.nl/intro`.

Static sections, with copy in `src/content/` so it's easy to find and edit
(editing copy = edit + rebuild + redeploy, per client decision):
1. **Header** — logo, link to `loefbijter.nl`, `Word lid` / `Inloggen` buttons.
2. **Hero** — period title, intro paragraphs, poster image, jump-nav buttons.
3. **Jump nav** — anchors to sections (Programma, WAZ, Locaties, ...).
4. **Programma** — the dynamic island (below).
5. **WoensdagAvondZeilen** block — text + external link.
6. **Locaties** — Het Bastion & Villa van Schaeck with Google Maps embeds (hardcoded).
7. **Footer** — logo, adres, socials, quick links, privacylink, copyright.

**Activities island**: fetches `/api/activities/`, renders cards (title, date —
formatted Dutch, e.g. "dinsdag 25 augustus" —, theme, time, location, image, cost
note) and per activity either: **Inschrijven** button (modal), an external link
(`external_registration_url`), or "Aanmelden niet nodig — kom gewoon langs!"
(`requires_registration=False`). Show "Nog X plekken" / "Vol — schrijf je in voor
de wachtlijst" / "Inschrijving gesloten" states.

**Registration modal**: standard fields per toggles, then custom fields, consent
checkbox, honeypot. On success show the outcome clearly:
- *Bevestigd*: "Je inschrijving is bevestigd. Tot dan!"
- *Wachtlijst*: "De activiteit zit vol — je staat op de wachtlijst. Het bestuur
  neemt contact met je op als er een plek vrijkomt."
- Include one line for changes/cancellation: "Afmelden of iets wijzigen? Mail het
  bestuur via [intro@loefbijter.nl — confirm address]."
All errors (duplicate, closed, validation) shown inline in Dutch.

**Brand extraction (agent task):** fetch the live site; extract palette, fonts,
logo (`Logo-transparant-zonder-tekst.png`) and the period poster into
`frontend/src/assets/` (committed to the repo — do **not** hotlink the WordPress
site, which may be slow or later restructured). Define tokens in
`src/styles/tokens.css`. Mobile-first; audience is mostly on phones.

---

## 9. Docker Compose — dev and prod parity

One stack, two modes. **Prod** is `docker-compose.yml`; **dev** adds
`docker-compose.override.yml` (Compose applies it automatically when present).

### docker-compose.yml (prod shape)

```yaml
services:
  backend:
    build: ./backend
    env_file: .env
    volumes:
      - db:/data
      - media:/app/media
      - static:/app/staticfiles
    expose: ["8000"]
    restart: unless-stopped

  frontend:               # one-shot builder; profile keeps it out of `up -d`
    build: ./frontend
    profiles: ["build"]
    volumes:
      - web_dist:/output
    command: sh -c "npm run build && rm -rf /output/* && cp -r dist/* /output/"

  web:
    image: nginx:1.27-alpine
    depends_on: [backend]
    volumes:
      - web_dist:/usr/share/nginx/html:ro
      - static:/srv/django-static:ro
      - media:/srv/media:ro
      - ./deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    ports:
      - "127.0.0.1:8080:80"
    restart: unless-stopped

volumes: { db: {}, media: {}, static: {}, web_dist: {} }
```

### docker-compose.override.yml (dev — IDE workflow)

```yaml
services:
  backend:
    command: python manage.py runserver 0.0.0.0:8000   # auto-reload
    volumes:
      - ./backend:/app                                  # bind mount for hot reload
    environment:
      - DEBUG=True
      - ALLOWED_HOSTS=localhost,127.0.0.1,backend
    ports:
      - "8000:8000"                                     # direct admin access in dev

  frontend:
    profiles: []                                        # runs in dev
    command: npm run dev -- --host
    volumes:
      - ./frontend:/app
      - /app/node_modules
    ports:
      - "4321:4321"                                     # Astro dev server w/ HMR
```

`astro.config.mjs` dev server proxies `/api` → `http://backend:8000` (Vite
`server.proxy`), so the island's relative `/api` calls work identically in dev —
**no CORS anywhere**. Dev loop: `make dev` (`docker compose up`), open
`http://localhost:4321` (site with hot reload) and `http://localhost:8000/admin`
(admin). Seed with `make seed` → `loaddata sample_activities`. Tests:
`make test` → `docker compose run --rm backend pytest`.

### nginx.conf (web container)

```nginx
server {
    listen 80;
    server_name _;
    client_max_body_size 10m;

    location /django-static/ { alias /srv/django-static/; expires 30d; access_log off; }
    location /media/         { alias /srv/media/;         expires 30d; }

    location ~ ^/(api|admin)/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;  # append real chain
    }

    location / { root /usr/share/nginx/html; try_files $uri $uri/ /index.html; }
}
```

### Host Apache (behind Cloudflare, thin proxy)

The site sits behind Cloudflare (proxied DNS, SSL mode **Full (strict)**), so
Apache must (a) recover the real visitor IP from Cloudflare's `CF-Connecting-IP`
via `mod_remoteip`, trusting only Cloudflare's published ranges, and (b) always
serve a valid origin cert (issued via **webroot** — see §10 / `deploy/deploy.md`).

Enable `mod_proxy`, `mod_proxy_http`, `mod_headers`, `mod_rewrite`, `mod_ssl`,
`mod_remoteip`. The full, authoritative vhost lives in
`deploy/intro.loefbijter.nl.conf`; sketch:

```apache
<VirtualHost *:443>
    ServerName intro.loefbijter.nl
    SSLEngine On
    SSLCertificateFile    /etc/letsencrypt/live/intro.loefbijter.nl/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/intro.loefbijter.nl/privkey.pem

    # Real visitor IP from Cloudflare (trust CF ranges only — refresh from
    # cloudflare.com/ips-v4 and /ips-v6). mod_proxy_http then appends the
    # recovered client IP to X-Forwarded-For.
    RemoteIPHeader CF-Connecting-IP
    RemoteIPTrustedProxy <Cloudflare IPv4 + IPv6 ranges>

    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto "https"
    ProxyPass        /  http://127.0.0.1:8080/
    ProxyPassReverse /  http://127.0.0.1:8080/
</VirtualHost>
```

### Django settings (env-driven, `.env.example` documents all)

```python
DEBUG = env.bool("DEBUG", False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["intro.loefbijter.nl"])
CSRF_TRUSTED_ORIGINS = ["https://intro.loefbijter.nl"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
TIME_ZONE = "Europe/Amsterdam"; LANGUAGE_CODE = "nl"; USE_TZ = True
STATIC_URL = "/django-static/"; STATIC_ROOT = "/app/staticfiles"
MEDIA_URL = "/media/"; MEDIA_ROOT = "/app/media"
RETENTION_DAYS = env.int("RETENTION_DAYS", 30)
# Client IP for rate limiting: Apache's mod_remoteip recovers the real visitor IP
# from Cloudflare's CF-Connecting-IP (trusting CF ranges only) and mod_proxy_http
# appends it to X-Forwarded-For; nginx appends its loopback peer. Read the entry
# Apache appends — the second-from-last X-Forwarded-For value. A client-forged
# X-Forwarded-For lands to its left and cannot influence the key. See DECISIONS.md.
```

---

## 10. Porting dev → EC2 (runbook, `deploy/deploy.md`)

Prereqs on EC2: Docker + Compose plugin installed; DNS A record for
`intro.loefbijter.nl` → instance; port `8080` free on loopback (verify:
`sudo ss -ltnp | grep 8080`); code in a Git remote the server can pull
(**confirm: GitHub repo available?**).

First deploy:
1. `git clone` the repo to e.g. `/opt/intro-loefbijter`.
2. `cp .env.example .env` → fill `SECRET_KEY` (generate), `DEBUG=False`, hosts.
   No `docker-compose.override.yml` on the server (dev-only; git-ignore it or keep
   it named so it must be explicitly excluded — prefer committing it and adding
   `COMPOSE_FILE=docker-compose.yml` to the prod `.env` so overrides can't leak in).
3. `make build` → builds images + runs the one-shot frontend build
   (`docker compose --profile build run --rm frontend`).
4. `make up` → `docker compose up -d backend web`.
5. `docker compose exec backend python manage.py createsuperuser`.
6. Install the Apache vhost, `a2ensite`, reload Apache. Smoke test over HTTPS:
   homepage, `/admin` login, a full registration round-trip, duplicate rejection.

Redeploys: `git pull && make build && make up` (only rebuilds what changed).
Copy changes (hardcoded text) follow the same flow.

**Backups (crucial — registrations are irreplaceable):** nightly host cron:
`docker compose exec backend sqlite3 /data/db.sqlite3 ".backup /data/backup-$(date +%F).sqlite3"`
plus copying the backup off the volume (and ideally off-instance, e.g. S3). Keep 14 days. Include `media/` if activity images matter. `make backup` target provided.

Cron also runs the retention purge (§7) weekly.

---

## 11. Testing (pytest, runs in the backend container)

Minimum coverage, all runnable via `make test`:
- **Service**: confirmed under capacity; waitlist at capacity; unlimited capacity;
  duplicate email rejected (case-insensitive); re-registration allowed after the
  previous one was cancelled; closed/not-yet-open windows; consent required;
  honeypot rejection; custom-field validation (required, select options, types).
- **Constraint**: DB-level duplicate rejection (IntegrityError path).
- **API**: unpublished activities hidden; no personal data in any GET response;
  register endpoint happy path + all error messages in Dutch.
- **Admin actions**: promote + cancel behave as specified (no auto-promotion).

---

## 12. Build order (milestones for Claude Code)

1. **Scaffold**: repo layout, Compose (+ override), Dockerfiles, `.env.example`, Makefile. `make dev` brings up a hello-world of both services.
2. **Models + admin** (§4–5) incl. unique constraint, email normalisation, JSON schema validation, admin actions (promote / cancel / CSV), fixtures. Verify the whole board workflow through the admin alone.
3. **API + service** (§6): endpoints, capacity/waitlist, duplicate guard, rate limiting with correct client IP, Dutch errors. Tests (§11) green.
4. **Frontend static shell** (§8): all static sections, brand tokens + assets extracted from the live site and committed.
5. **Activities island + modal**: all states (open/full/closed/external/no-registration), all outcomes (confirmed/waitlist/duplicate/errors), mobile-first.
6. **Privacy** (§7): consent, purge command.
7. **Prod hardening + runbook** (§9–10): nginx/Apache configs, XFF chain verified, backup target, deploy.md. Full smoke test of the prod-shaped stack locally (`COMPOSE_FILE=docker-compose.yml docker compose ...`) before touching EC2.

---

## 13. Acceptance criteria

- `make dev` gives a working site at `localhost:4321` with hot reload and admin at `localhost:8000/admin`; `make test` passes.
- The prod stack runs locally with the prod compose file alone — proving portability — and on EC2 identically, behind Apache on the subdomain.
- Public homepage is static, fast on mobile, high Lighthouse score.
- Board can create a published activity (capacity + custom fields) in the admin and it appears **without redeploy**; copy changes require edit + rebuild (accepted).
- At capacity, sign-ups become waitlist with a clear Dutch message; duplicate email for the same activity is rejected (incl. under concurrent submissions); cancelled emails may re-register.
- **No auto-promotion**: cancelling in the admin frees a spot; the board promotes manually via the admin action and contacts the person themselves.
- No emails sent anywhere; no public cancel endpoint exists.
- CSV export works; no personal data in any public API response; retention purge command works.
- Rate limiting throttles per real client IP (not the proxy IP).

---

## 14. Remaining items to confirm (non-blocking)

1. **Board contact address** shown in the modal for cancellations/changes (assumed `intro@loefbijter.nl` — confirm).
2. **Git remote** the EC2 can pull from (GitHub?).
3. `RETENTION_DAYS` default of **30** okay?
4. Optional later: pre-render activities at build time for SEO (not needed now; would reintroduce rebuilds on content changes).

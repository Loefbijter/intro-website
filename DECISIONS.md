# Implementation decisions

Small implementation details decided by the agent where the SPEC left room,
per `/goal` working rule 4. Deviations that seemed ambiguous/contradictory
enough to need confirmation are called out explicitly.

## Milestone 1

- **Pinned Astro to `5.18.2`, not the literal npm "latest" (7.1.0).** SPEC §2
  pins both "Node 20 LTS" and "Astro latest stable." Astro 6.x+ raised its
  minimum to Node ≥22.12 (confirmed via `npm view astro engines`), so those
  two pins directly conflict at the current npm HEAD. Chose the latest Astro
  major that still supports Node 20 across its whole release line (5.x, node
  range `18.20.8 || ^20.3.0 || >=22.0.0`) rather than pinning to the last 6.0.x
  patch that happened to still allow Node 20 (`6.0.4`, on the edge of a
  version line already moving to Node-22-only) — the 5.x line is broadly
  tested against Node 20, not just barely compatible with it.
  **Update (milestone 4):** `npm audit` flags 5.18.2 for 5 known Astro
  advisories (XSS in `define:vars`, server-island parameter replay, reflected
  XSS via slot names, XSS via spread props, host-header SSRF in prerendered
  error pages) — all fixed only in the 7.x line, not backported to 5.x/6.x.
  Assessed as low real-world risk here specifically because this site uses
  `output: "static"` (SPEC §2's "public pages are static HTML/CSS"): there's
  no SSR, no server islands, and the dynamic activities data is fetched
  client-side via JS rather than through Astro's own templating at
  request-time, so the exploitable surface for these advisories isn't
  present in how this site is built or served. Flagging this explicitly
  rather than silently swallowing the audit warning — if the Node pin is
  ever raised to 22 LTS, upgrading to Astro 7.x closes this out cleanly.

- **Frontend Dockerfile is single-stage, not multi-stage.** SPEC §3 describes
  it as "multi-stage: node build → files to /output", but SPEC §9's
  `docker-compose.yml` already defines the frontend service's `command` as
  `npm run build && rm -rf /output/* && cp -r dist/* /output/` against a
  `web_dist` volume mount at `/output`. That compose-level command does the
  "build → copy to /output" work directly, making a second Dockerfile build
  stage redundant. Kept the Dockerfile as a single `node:20-alpine` stage
  that installs deps and copies source; the compose `command:` (which
  overrides any Dockerfile `CMD`) performs the actual build + copy step.
- **`DB_PATH=/data/db.sqlite3` used in both dev and prod `.env`.** The `db`
  named volume is mounted at `/data` in the base `docker-compose.yml` and
  isn't touched by `docker-compose.override.yml`, so the same path works in
  both modes — one less thing to differ between dev/prod `.env` files.
- **Dev `.env` sets `COMPOSE_PROFILES=build`, needed on top of the SPEC's
  `docker-compose.override.yml`.** SPEC §9 gives the frontend override as
  `profiles: []`, intending to pull the one-shot builder out from behind the
  "build" profile so `make dev` runs it as a dev server. Verified empirically
  that Compose merges `profiles` lists between base and override files as a
  **union**, not a replace — `["build"]` merged with `[]` stays `["build"]`,
  so the frontend container was silently skipped by plain `docker compose up`.
  Fix: set `COMPOSE_PROFILES=build` in the dev `.env` (a Compose-CLI-level
  var, read from `.env` same as `COMPOSE_FILE`), which activates the profile
  for the whole `up` regardless of the per-service list. Kept
  `docker-compose.override.yml` textually matching the SPEC; the real fix
  lives in `.env`, commented, and does not carry over to prod (`.env.example`
  doesn't set it, and prod's explicit `make up`/`make build` targets name
  services directly so profile filtering doesn't matter there anyway).
- **Backend `entrypoint.sh` now execs `"$@"` instead of hardcoding gunicorn.**
  SPEC §3 describes it as "migrate + collectstatic → gunicorn", and the dev
  override (§9) sets `command: python manage.py runserver ...` expecting that
  to actually run. But Dockerfile's `ENTRYPOINT ["./entrypoint.sh"]` means an
  override `command:` is passed to the entrypoint as arguments, not run in
  its place — the original script ignored them and always launched gunicorn,
  so dev's `runserver` override was silently dead. Fixed by having
  `entrypoint.sh` run migrate (always) and collectstatic (prod only, skipped
  when `DEBUG=True` since `runserver` serves static itself and `STATIC_ROOT`
  isn't bind-mounted in dev), then `exec "$@"` if args were given, falling
  back to gunicorn otherwise.
- **Backend `ENTRYPOINT` invokes `sh entrypoint.sh` instead of
  `./entrypoint.sh`.** The dev bind mount (`./backend:/app`) replaces the
  in-image copy of `entrypoint.sh` with the host file, whose executable bit
  isn't guaranteed (files created by the agent's editor aren't `chmod +x`).
  That caused `permission denied` on every dev container start. Invoking it
  as an explicit `sh` argument sidesteps the executable bit entirely.
- **`COMPOSE_FILE=docker-compose.yml` left commented out in `.env.example`.**
  SPEC §10 step 2 wants it set in the *prod* `.env` so the dev override file
  can't leak onto the server. But `.env.example` is the template for both
  dev and prod `.env` files, and setting it unconditionally would stop
  `docker-compose.override.yml` from auto-applying in dev, breaking
  `make dev`. Documented as a prod-only line to uncomment at deploy time.

## Milestone 3

- **Honeypot field is named `website`.** SPEC §6 says "Honeypot hidden field
  — reject silently if filled" without naming it. Used the common convention
  of naming it after a plausible-looking real field (`website`) rather than
  literally `honeypot`, since an obviously-named trap field is easier for
  bots to detect and skip.
- **HTTP status codes for register errors are my own choice** (SPEC lists the
  Dutch messages, not status codes): 201 for both confirmed/waitlist success
  (and the faked honeypot response), 409 for duplicate email, 403 for
  closed/not-yet-open windows and for activities that don't use the standard
  flow (`requires_registration=False` or an external URL set), 400 for
  field/consent/custom-field validation errors, 429 for rate-limiting.
- **Rate limiting is per-gunicorn-worker**, using Django's default in-process
  `LocMemCache` — no Redis/Memcached added. `django-ratelimit`'s counters
  aren't shared across workers, so the effective limit scales with worker
  count. Acceptable for this club's traffic volume; flagged here in case
  gunicorn is ever run with `--workers > 1` and the limit needs to be exact.
- **Unknown custom-field answer keys are silently dropped**, not rejected,
  when saving a registration (`services._validate_answers`). SPEC's schema
  validation focus is on required/type-correctness of *known* fields; being
  lenient about stray keys (e.g. a stale field from a cached frontend after
  the activity's schema changed) avoids spurious registration failures for
  something the registrant can't fix.

## Milestone 4

- **Hero image is a generic on-brand sailing photo, not a "period poster".**
  SPEC §8 asks for a "poster image" in the hero, and the live `/intro` page's
  `og:image` (`image_2025-08-25_002115675.png`) looked like the obvious
  candidate at first. Checking its position in the live HTML showed it
  actually belongs to `/intro`'s *Na-introductie* (September, after the main
  week) subsection, not the hero — and its content is a dated
  "NA-INTRO PROGRAMMA 2025" graphic with September 2025 dates, which would
  read as stale and mismatched against this site's August-2026 fixture data.
  By contrast, `/voorjaarsintro` *does* have a correctly-scoped, period-named
  hero poster (`Voorjaarsintro-2026-819x1024.png`), confirming each period
  normally gets its own bespoke poster — one doesn't exist yet for whatever
  the next August intro period will be. Used a generic, unbranded-date photo
  of Loefbijter boats sailing the Waal instead (also extracted from
  loefbijter.nl, self-hosted per SPEC §8's "do not hotlink" rule). The board
  should swap in that period's real poster (`frontend/src/assets/hero-photo.jpg`,
  referenced from `Hero.astro`) once it exists, same as any other per-period
  copy change (SPEC §1: "the site is revamped per period").
- **Fonts self-hosted via `@fontsource/roboto` + `@fontsource/roboto-slab`
  npm packages**, not by copying the WordPress site's font files. The site
  uses Roboto (body/nav/buttons) and Roboto Slab (SPEC §8 palette/fonts
  extraction), confirmed via the live site's Elementor global-typography CSS
  variables. Fontsource ships the same Google Fonts as self-hosted npm
  packages bundled at build time — satisfies "committed to the repo, not
  hotlinked" more cleanly than vendoring WordPress's specific pre-subset
  font files, and avoids a runtime request to Google Fonts' CDN too.
- **Dev gotcha, not a repo bug: adding an npm/pip dependency requires
  `docker compose up --build --renew-anon-volumes <service>`, not just
  `--build`.** `docker-compose.override.yml`'s `/app/node_modules` (and
  Python's site-packages inside the image) live behind an anonymous volume
  that Compose reuses across recreations by default, so a rebuilt image's
  fresh `npm install`/`pip install` output is masked by the stale volume
  until it's explicitly renewed. Hit this firsthand adding `@fontsource/*`.
  Worth remembering for milestones 5–7 too whenever `requirements.txt` or
  `package.json` changes.

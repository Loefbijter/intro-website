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

## Milestone 5

- **Activities island is vanilla TypeScript, no UI framework** (no React/
  Vue/Svelte/Preact added to `package.json`). SPEC §2/§8 emphasize "Fast"
  and a lightweight static site; the island's job is fetch → render cards →
  open a form in a `<dialog>` → POST — plain DOM APIs handle that without a
  framework runtime. The built client JS for the whole island (list +
  modal + custom-field rendering) is 7.75 kB (2.74 kB gzipped, verified via
  `npm run build`), which a framework runtime would multiply several times
  over for equivalent behaviour.
- **Registration modal uses the native `<dialog>` element**, not a custom
  overlay built from styled `<div>`s. Gets focus-trapping, `Esc`-to-close,
  and a `::backdrop` for free from the browser, which matters more than
  usual here since the audience is "mostly on phones" (SPEC §8).
- **Card descriptions render as plain escaped text, not parsed Markdown**,
  even though `Activity.description` is documented as "markdown allowed"
  (SPEC §4). Rendering board-authored Markdown as HTML client-side either
  needs a parser dependency (weight, another thing to keep patched) or an
  XSS-sanitization step to do safely; skipped both for now since no fixture
  or real content currently relies on Markdown formatting. Revisit if the
  board actually starts writing Markdown in descriptions — flagged here
  rather than silently ignoring the SPEC's "markdown allowed" note.
- **`typescript` pinned to `6.0.3`, not npm's literal "latest" (7.0.2).**
  Same shape of conflict as the Astro/Node pin in milestone 1: `@astrojs/check@0.9.9`
  (needed for `npm run check` / `astro check`) declares a peer range of
  `^5.0.0 || ^6.0.0`, so TypeScript 7.x fails `npm install` outright. Used
  the newest version inside that peer range instead.

## Client IP for rate limiting (behind Cloudflare)

**Supersedes an earlier decision.** Milestones 3/7 reasoned about client-IP
resolution assuming the SPEC's three-hop chain (Apache → nginx → gunicorn) with
no CDN, and landed on `django-ipware` `proxy_count=1`. **Deployment revealed the
site actually sits behind Cloudflare**, making the real chain four hops:

    Cloudflare → Apache → nginx → gunicorn

That invalidates the old approach and the `proxy_count` reasoning entirely:

- **The bug it caused.** Without anything recovering the true visitor IP,
  Django saw a **Cloudflare edge IP** as the client for every request, so
  `django-ratelimit` bucketed all visitors into one shared key — the
  registration rate limit either locked everyone out at once, or (if the count
  were raised to compensate) protected nothing.
- **`proxy_count` is fundamentally fragile here.** Cloudflare adds its own
  `X-Forwarded-For` entry, and a client can prepend a forged one, so the total
  number of entries varies per request. Any fixed `proxy_count` is wrong for
  some requests: `proxy_count=1` (correct for the old 3-hop chain) returns
  `None` for the normal 4-hop chain, breaking rate limiting outright.

**Fix — at the edge, not by counting.** Apache runs `mod_remoteip` with
`RemoteIPHeader CF-Connecting-IP`, trusting **only** Cloudflare's published IP
ranges (fetched from cloudflare.com/ips-v4 + /ips-v6, not memorised). Cloudflare
sets `CF-Connecting-IP` to the true visitor and a client cannot forge it past
Cloudflare; `mod_remoteip` ignores it entirely on any connection not coming from
a Cloudflare range (so a direct-to-origin hit can't spoof it either). With the
visitor IP restored at Apache, `mod_proxy_http` appends **that** IP to
`X-Forwarded-For`, and nginx appends its own loopback peer. The header therefore
always ends `"<real client>, 127.0.0.1"`.

`client_ip_key` (in `activities/api.py`) now just reads the **second-from-last**
`X-Forwarded-For` entry — the one Apache authoritatively appended — with no
proxy library and no count parameter. A client-forged `X-Forwarded-For` only
ever lands to the *left* of Apache's entry, so it can't reach the
second-from-last slot and can't influence the key. Dropped the now-unused
`django-ipware` dependency. `test_client_ip.py` covers the Cloudflare chain, the
"reads Apache's entry, not the leftmost" property, the spoofing attempt, and the
degenerate-fallback case.

(Note: at Django, `REMOTE_ADDR` is nginx's container IP — there are two internal
hops below Cloudflare — so the real client genuinely lives in `X-Forwarded-For`,
not `REMOTE_ADDR`. If a future change wanted `REMOTE_ADDR` to hold the client
directly, nginx's `realip` module would be the place; it isn't needed for
correctness here.)

## Post-milestone: real Introweek 2026 programme + flyer

- **Replaced the placeholder hero photo with the board's real Introweek 2026
  flyer** (`frontend/src/assets/flyer-introweek-2026.jpeg`), resolving the
  milestone-4 note that flagged the generic sailing photo as a stand-in until
  a real period poster existed. The flyer is the hero image and is clickable
  to open full-size (it's a text-dense image; the readable/accessible version
  is the interactive Programma cards below it, which carry proper alt-free
  semantic text). Removed the now-unused `hero-photo.jpg`.
- **Rewrote `sample_activities.json` to match the flyer exactly** — the seven
  real activities (Loefstrand Muziekbingo/Jamsessie, Eetactie, Loefstrand
  Beachparty, Dinsdagborrel, Loefstrand Fietsversieren, HAN-Introdag,
  Sportdagen) replacing the earlier demo data. These are seed data the board
  would otherwise enter via the admin; seeding the real programme keeps the
  demo/handoff faithful.
- **Modelled the Eetactie as a separate activity with an external signup URL,
  not folded into the Loefstrand day cards.** The flyer visually groups
  "Loefstrand ... + Eetactie" per day, but the two differ functionally: the
  Loefstrand is drop-in (`requires_registration=False` → "kom gewoon langs"),
  while the Eetactie needs a signup via the disputen's Google Form
  (`external_registration_url` → external "Inschrijven" link). Splitting them
  is the honest representation of that difference. Used one Eetactie card
  covering both cook nights (17 & 18 Aug) since it's a single shared form,
  matching the committee text's singular "de link hieronder".
- **The Eetactie signup appears in two places** — a hero CTA button (matching
  the committee text's "Meld je aan via de link hieronder") and the Eetactie
  activity card — both pointing at the same Google Form. Deliberate: two
  low-friction touchpoints for the main actionable signup, per the request to
  "engage potential new members to go to one of the activities."
- **Sportdagen is dated its first day (17 Aug) with the full span in
  `time_text` ("17, 18, 19 & 26 augustus").** The data model has a single
  `date`; the card shows the formatted first day plus the spanning
  `time_text`, mirroring the flyer's "17-18-19-26 augustus". Not worth a
  multi-day model change for one spanning info card.

## Post-milestone: warm Introweek palette (yellow + red)

- **Re-themed the site from the main loefbijter.nl blue palette to the
  Introweek's warm yellow/red palette**, at the board's request to keep colours
  consistent with the intro theme. Re-checked `loefbijter.nl/voorjaarsintro`:
  its page-specific Elementor CSS overrides the site blue with gold `#E8B950`
  (buttons + some headings) and red `#D73E2A` (large headings + button
  hover/focus). Sampled the Introweek 2026 flyer too — dominant gold
  `#EDBB5B`, cream `#FFEDAD`, teal accents — confirming the same warm family.
  So the new palette is grounded in the club's own intro branding, not invented.
- **Button treatment mirrors the reference exactly**: gold background with dark
  text, transitioning to red with white text on hover/focus. Chose this over
  red-filled buttons because it (a) matches what voorjaarsintro actually does
  and (b) puts both hues prominently on every CTA. Verified contrast: dark
  brown `#4a2c10` on gold ≈ 8:1, white on red ≈ 4.5:1 — both pass WCAG AA.
- **Mapping**: `--color-primary` → red `#D73E2A` (headings, links, card dates,
  secondary-button outline, primary-button hover); new `--color-gold`
  `#E8B950` (primary button fill, header top stripe); `--color-deep` `#7A2417`
  (footer, replacing the old navy); warm cream page background `#fffaf0` with
  white card/header/modal surfaces; warm border `#ecdcb8`. Darkened the warm
  muted/secondary text tokens to hold ≥4.5:1 on the cream background. Replaced
  the two hardcoded navy `rgba()` values (hero flyer shadow, modal backdrop)
  with warm equivalents, and dropped the now-unused green `--color-accent`.
- **Kept the blue club logo** as-is: it's the real Loefbijter mark, and the
  flyer itself places the same blue-sails logo on the warm background, so the
  combination is on-brand rather than a clash.

## Post-milestone: activity images + jump-nav hover fix

- **Fixed an invisible jump-nav hover (white text on white background).**
  `JumpNav.astro`'s scoped `.jump-nav .button { background:#fff }` out-specifies
  the global `.button--secondary:hover` (Astro adds a scope attribute, raising
  specificity), so on hover the text turned white while the background stayed
  white. Added a scoped `.jump-nav .button:hover/:focus` rule that re-asserts
  the red fill + white text.
- **Wired up per-activity images end-to-end** (the ImageField existed since
  milestone 2 but was never exercised with real files). Three photos the board
  supplied — also used on the voorjaarsintro page — are mapped by theme:
  sailing → Loefstrand: Beachparty!, feest → Dinsdagborrel, intromarkt →
  HAN-Introdag. Plumbing:
  - Images committed as **seed media** under
    `backend/activities/fixtures/media/activities/` (not `backend/media/`,
    which is git-ignored) so the repo is self-contained. Converted the 1 MB
    `intromarkt.png` to a ~100 KB JPEG (photos-as-PNG are wasteful; SPEC §1
    wants the site fast).
  - `make seed` now copies that seed media into `MEDIA_ROOT` before
    `loaddata`, so the fixture's `image` paths resolve. Same command works in
    prod (the media files are baked into the backend image via `COPY . .`).
  - **Serializer returns a relative `/media/...` URL** (`obj.image.url`) via a
    `SerializerMethodField`, not DRF's default absolute URL. Absolute URLs
    would be built from the request host, which behind the
    Apache→nginx→gunicorn chain (and the dev Vite proxy with
    `changeOrigin:true`) resolves to `backend:8000` — unreachable from the
    browser. Relative URLs match the SPEC's "relative /api URLs only" stance.
  - **Media serving**: added `static(MEDIA_URL, ...)` to `config/urls.py` under
    `DEBUG` (Django serves images in dev), and a `/media` proxy to
    `astro.config.mjs` so relative URLs resolve on the :4321 dev server. Prod
    is unchanged — nginx already serves `/media/` from the volume (verified
    both the :4321 dev proxy and :8080 nginx path return the images).

## Post-milestone: to-be-announced activity + video embed

- **Made `Activity.date` nullable to model a genuine "to-be-announced"
  activity.** The introduction weekend is "sometime in September" with no set
  date, so storing a fake placeholder date would be dishonest and show a
  misleading day on the card. A null date is the truthful signal: the card
  shows a gold "Datum volgt" badge instead of a formatted date, and the
  registration area shows "Meer info volgt — houd onze socials in de gaten!"
  instead of any signup UI (the null-date branch takes priority in
  `renderRegistrationControl`). No date = teaser/announcement card.
- **Added an `Activity.video_url` field + a controlled embed** rather than
  allowing HTML in the description (descriptions are still rendered as escaped
  text for XSS safety, per milestone 5). `videoEmbedSrc()` only recognises
  Instagram and YouTube URLs and rebuilds the iframe `src` from a captured id,
  so a board-pasted URL can't point the iframe at an arbitrary target;
  unrecognised URLs fall back to a plain "Bekijk de video" link. Reusable —
  any future activity can carry a promo video.
- **A video-bearing card becomes full-width (`activity-card--featured`,
  `grid-column: 1 / -1`)** so the embed has room and doesn't distort the
  3-column grid. Placed the teaser first (`sort_order: 0`) as a "Save the
  date" banner atop the programme — most prominent for hype, and it keeps the
  grid clean (the 7 dated cards then flow as full rows, versus a lone card
  leaving empty cells mid-grid if the banner were last). On desktop the video
  sits beside the text; on mobile it stacks on top.
- No public-facing scope was added to registration: the teaser has no signup
  (that opens once the weekend is announced via the admin).

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

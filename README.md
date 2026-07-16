# intro

Introduction website of N.S.Z.V. De Loefbijter.

See `intro-loefbijter-SPEC.md` for the full build spec and `DECISIONS.md` for
implementation decisions made along the way.

## Quickstart (dev)

```
cp .env.example .env   # then fill SECRET_KEY, or use the committed dev .env
make dev                # docker compose up — Astro + Django with hot reload
```

- Site: http://localhost:4321
- Django admin: http://localhost:8000/admin
- API health check: http://localhost:8000/api/health/

Other targets: `make test`, `make seed`, `make superuser`, `make build`,
`make up` (prod-shaped), `make backup`. See `Makefile`.

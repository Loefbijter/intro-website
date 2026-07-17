.PHONY: dev build up down test seed superuser backup migrate logs purge

dev:
	docker compose up

build:
	docker compose build
	docker compose --profile build run --rm --build frontend

up:
	docker compose up -d backend web

down:
	docker compose down

test:
	docker compose run --rm backend pytest

seed:
	docker compose run --rm backend sh -c "cp -r activities/fixtures/media/. /app/media/ && python manage.py loaddata sample_activities"

migrate:
	docker compose run --rm backend python manage.py migrate

superuser:
	docker compose run --rm backend python manage.py createsuperuser

backup:
	docker compose exec backend sqlite3 /data/db.sqlite3 ".backup /data/backup-$$(date +%F).sqlite3"

purge:
	docker compose exec backend python manage.py purge_old_registrations

logs:
	docker compose logs -f

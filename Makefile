.PHONY: dev build up down test seed superuser backup migrate logs

dev:
	docker compose up

build:
	docker compose build
	docker compose --profile build run --rm frontend

up:
	docker compose up -d backend web

down:
	docker compose down

test:
	docker compose run --rm backend pytest

seed:
	docker compose run --rm backend python manage.py loaddata sample_activities

migrate:
	docker compose run --rm backend python manage.py migrate

superuser:
	docker compose run --rm backend python manage.py createsuperuser

backup:
	docker compose exec backend sqlite3 /data/db.sqlite3 ".backup /data/backup-$$(date +%F).sqlite3"

logs:
	docker compose logs -f

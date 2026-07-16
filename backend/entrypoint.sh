#!/bin/sh
set -e

python manage.py migrate --noinput

if [ "$DEBUG" != "True" ]; then
    python manage.py collectstatic --noinput
fi

if [ "$#" -eq 0 ]; then
    set -- gunicorn config.wsgi:application --bind 0.0.0.0:8000
fi

exec "$@"

#!/bin/sh
set -e

python manage.py migrate --noinput

# Only on first run against an empty management-db volume: on a volume that already
# has this user, createsuperuser exits non-zero ("that username is already taken"),
# which must not kill the container under `set -e`.
if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
    python manage.py createsuperuser --noinput || true
fi

python manage.py collectstatic --noinput

# --workers 1 is load-bearing: RESTART_STATES (heappe_ui/view/deploy.py) is in-process state.
exec gunicorn adminpanel.wsgi:application --workers 1 --bind 0.0.0.0:8000 --timeout 360

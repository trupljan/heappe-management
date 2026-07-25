#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# --workers 1 is load-bearing: RESTART_STATES (heappe_ui/view/deploy.py) is in-process state.
exec gunicorn adminpanel.wsgi:application --workers 1 --bind 0.0.0.0:8000 --timeout 360

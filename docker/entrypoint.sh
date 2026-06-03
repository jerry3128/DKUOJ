#!/bin/sh
# Role dispatcher for the DKUOJ site image.
# Usage: entrypoint <web|celery|bridge> ...  (default: web)
set -e

role="${1:-web}"
shift 2>/dev/null || true

case "$role" in
  web)
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput
    python manage.py compilemessages --noinput
    python manage.py compilejsi18n --noinput
    # COMPRESS_OFFLINE installs may also need: python manage.py compress --force
    exec gunicorn dmoj.wsgi \
        --bind "0.0.0.0:${GUNICORN_PORT:-8000}" \
        --worker-class gevent \
        --workers "${GUNICORN_WORKERS:-4}" \
        "$@"
    ;;
  celery)
    exec celery -A dmoj_celery worker --loglevel="${CELERY_LOGLEVEL:-info}" "$@"
    ;;
  bridge)
    exec python dmoj_bridge_async.py "$@"
    ;;
  *)
    # Fall through: run an arbitrary command (e.g. manage.py shell).
    exec "$role" "$@"
    ;;
esac

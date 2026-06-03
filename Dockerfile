# Multi-stage build for the DKUOJ site.
#   styles   : builds resources/*.css via make_style.sh (Node toolchain)
#   wsevent  : the Node websocket event daemon (websocket/daemon.js)        [target: wsevent]
#   web      : the Django app run as web / celery / bridge via entrypoint   [target: web, default]
#
# Built in CI by Kaniko (see .gitlab-ci.yml). Per-deploy config (DB, Redis,
# SECRET_KEY, event/bridge addresses) is supplied at runtime via a mounted
# dmoj/local_settings.py — nothing secret is baked into the image.

# --- stage: styles -------------------------------------------------------
FROM node:20-bookworm-slim AS styles
WORKDIR /app
RUN npm install -g sass postcss-cli postcss autoprefixer
COPY resources ./resources
COPY make_style.sh ./
RUN ./make_style.sh

# --- stage: wsevent (Node websocket daemon) ------------------------------
FROM node:20-bookworm-slim AS wsevent
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install --omit=dev
COPY websocket ./websocket
# Bind on all interfaces inside the container (see websocket/config.js).
ENV WS_GET_HOST=0.0.0.0 WS_POST_HOST=0.0.0.0 WS_HTTP_HOST=0.0.0.0
EXPOSE 15100 15101 15102
CMD ["node", "websocket/daemon.js"]

# --- stage: web (Django: web / celery / bridge) --------------------------
FROM python:3.11-slim-bookworm AS web
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=dmoj.settings
WORKDIR /app

# Build/runtime libs: mysqlclient (libmysqlclient), lxml (libxml2/xslt),
# git for the git+https requirements, curl for healthchecks,
# gettext (msgfmt) for `manage.py compilemessages` in the entrypoint.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config git curl gettext \
        default-libmysqlclient-dev libxml2-dev libxslt1-dev \
        pandoc texlive-full \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt "gunicorn[gevent]" mysqlclient

COPY . .
# Bring in the compiled CSS from the styles stage.
COPY --from=styles /app/resources ./resources
COPY docker/entrypoint.sh /usr/local/bin/entrypoint
RUN chmod +x /usr/local/bin/entrypoint

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint"]
CMD ["web"]

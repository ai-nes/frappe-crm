FROM python:3.11-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV BENCH_DIR=/home/frappe/frappe-bench
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
    gettext \
    mariadb-client \
    redis-tools \
    build-essential \
    libffi-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable \
    && corepack prepare yarn@1.22.22 --activate \
    && pip install --no-cache-dir frappe-bench

RUN useradd -m -s /bin/bash frappe \
    && mkdir -p /home/frappe/frappe-bench /opt/frappe/scripts \
    && chown -R frappe:frappe /home/frappe /opt/frappe

USER frappe
WORKDIR /home/frappe

RUN bench init \
    --ignore-exist \
    --skip-redis-config-generation \
    --no-backups \
    "${BENCH_DIR}" \
    --version version-15

WORKDIR ${BENCH_DIR}

RUN mkdir -p ${BENCH_DIR}/apps/crm/frontend

COPY --chown=frappe:frappe frontend/package.json frontend/yarn.lock ${BENCH_DIR}/apps/crm/frontend/

RUN cd apps/crm/frontend \
    && yarn install --frozen-lockfile

COPY --chown=frappe:frappe . ${BENCH_DIR}/apps/crm

RUN ./env/bin/pip install --no-cache-dir -e apps/crm \
    && cd apps/crm/frontend \
    && yarn build \
    && cd "${BENCH_DIR}" \
    && bench build --app frappe --production \
    && mkdir -p sites/assets/locale/vi/LC_MESSAGES \
    && msguniq --use-first apps/crm/crm/locale/vi.po | msgfmt - -o sites/assets/locale/vi/LC_MESSAGES/crm.mo \
    && cp -a sites /opt/frappe/sites-template

COPY --chown=frappe:frappe docker/prod-runtime.sh docker/prod-site.sh /opt/frappe/scripts/

EXPOSE 8000 9000

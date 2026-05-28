FROM python:3.11-bookworm

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
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
    && corepack prepare yarn@1.22.22 --activate

RUN pip install --no-cache-dir frappe-bench

RUN useradd -m -s /bin/bash frappe \
    && mkdir -p /workspace \
    && chown -R frappe:frappe /workspace /home/frappe

USER frappe
WORKDIR /home/frappe

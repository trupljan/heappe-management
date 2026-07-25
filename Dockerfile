FROM python:3.12-slim

WORKDIR /app

# docker-ce-cli + docker-compose-plugin come from Docker's own apt repo (not in Debian's).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && . /etc/os-release \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $VERSION_CODENAME stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        git \
        build-essential \
        libffi-dev \
        libssl-dev \
        unixodbc \
        unixodbc-dev \
        freetds-dev \
        docker-ce-cli \
        docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Includes .git — context_processors.py shells out to `git describe`/`git branch` for the version badge.
COPY . .
RUN chmod +x /app/docker-entrypoint.sh

# settings.py hardcodes BASE_DIR/db.sqlite3; redirect it to the persisted volume without touching settings.py.
RUN mkdir -p /var/lib/heappe-management \
    && ln -sf /var/lib/heappe-management/db.sqlite3 /app/db.sqlite3

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]

FROM python:3.12-slim

# Instalace Git, curl, certifikátů a Docker CLI + Compose pluginu
RUN apt-get update && apt-get install -y \
    git \
    curl \
    ca-certificates \
    docker.io \
    && mkdir -p /root/.docker/cli-plugins \
    && curl -SL https://github.com/docker/compose/releases/download/v2.20.2/docker-compose-linux-x86_64 \
       -o /root/.docker/cli-plugins/docker-compose \
    && chmod +x /root/.docker/cli-plugins/docker-compose \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Aplikace
RUN mkdir /app
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt
COPY . /app/

EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]

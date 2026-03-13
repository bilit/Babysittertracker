# Supports two modes:
#   1. HA Add-on:   BUILD_FROM is set by the HA build system to the correct
#                   arch-specific base image (e.g. ghcr.io/home-assistant/amd64-base-python:3.12)
#   2. Standalone:  BUILD_FROM is empty → falls back to plain python:3.12-slim
ARG BUILD_FROM=""
FROM ${BUILD_FROM:-python:3.12-slim}

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates/ templates/
COPY static/ static/

# HA add-on entrypoint (also used for standalone when run.sh is present)
COPY run.sh /run.sh
RUN chmod +x /run.sh

RUN mkdir -p /data

ENV PORT=5050
EXPOSE 5050

CMD ["/run.sh"]

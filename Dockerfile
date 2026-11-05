FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app
WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

RUN groupadd -g 10001 krw && useradd -u 10001 -g 10001 -M -s /usr/sbin/nologin krw \
    && mkdir -p /data/krw && chown -R 10001:10001 /data/krw
COPY --chown=10001:10001 agent/ ./agent/
COPY --chown=10001:10001 gateway/ ./gateway/
COPY --chown=10001:10001 scripts/run_northflank.sh scripts/check_devices.py scripts/check_mcp_discovery.py ./scripts/

USER 10001:10001
EXPOSE 8765
CMD ["bash", "/app/scripts/run_northflank.sh"]

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PORT=8080 \
    COOKIE_SECURE=1 \
    TRUST_PROXY=1

WORKDIR /srv/qrtr
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN useradd -r -u 10001 qrtr && mkdir -p /data && chown qrtr:qrtr /data
USER qrtr
EXPOSE 8080
VOLUME ["/data"]

CMD ["sh", "deploy/start.sh"]

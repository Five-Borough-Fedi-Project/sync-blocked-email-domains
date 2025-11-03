# Dockerfile for sync-blocked-email-domains
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sync_blocklist.py .

CMD ["python", "sync_blocklist.py"]

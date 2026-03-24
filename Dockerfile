FROM python:3.11-slim

WORKDIR /app

# System deps for newspaper3k and lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libxml2-dev libxslt1-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render sets PORT env var; default to 8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}

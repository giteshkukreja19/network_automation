# Flask dashboard + Python automation backend (runs as a container; published on 127.0.0.1:5000 only)
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libffi-dev libssl-dev libxml2-dev libxslt1-dev curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend/ backend/
COPY templates/ templates/
COPY static/ static/
EXPOSE 5000
HEALTHCHECK --interval=10s --timeout=3s --retries=6 CMD curl -fsS http://127.0.0.1:5000/healthz || exit 1
CMD ["python", "backend/app.py"]

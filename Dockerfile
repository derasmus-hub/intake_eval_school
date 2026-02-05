FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
  && rm -rf /var/lib/apt/lists/*

# Create data directory for SQLite persistence
RUN mkdir -p /app/data

# Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . /app

# Where the app listens
EXPOSE 8000

# Environment defaults
ENV HOST=0.0.0.0
ENV PORT=8000
ENV DEV_RELOAD=0
ENV IN_DOCKER=1

CMD ["python", "run.py"]

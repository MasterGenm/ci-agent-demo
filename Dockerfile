# v1.5 cs-mvp container image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libxml2-dev \
        libxslt1-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY cs_mvp ./cs_mvp
COPY demo ./demo
COPY docs ./docs
COPY KNOWN_ISSUES.md PRD.md SDD.md ./

RUN pip install --upgrade pip \
    && pip install -e .

RUN mkdir -p runs data

EXPOSE 8765

CMD ["python", "-m", "cs_mvp.cli", "serve", "--host", "0.0.0.0", "--port", "8765"]

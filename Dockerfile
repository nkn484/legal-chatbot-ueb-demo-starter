FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SEMANTIC_MODEL_PATH=/models/multilingual-e5-small \
    RERANKER_MODEL_PATH=/models/mmarco-minilm-l12-h384-int8-avx2

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-vie \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system app && adduser --system --ingroup app --home /app app

COPY pyproject.toml ./
COPY src ./src
COPY contracts ./contracts
COPY demo_data ./demo_data
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install ".[dev]"

RUN mkdir -p /models/multilingual-e5-small /models/mmarco-minilm-l12-h384-int8-avx2 \
    && chown -R app:app /models

USER app

EXPOSE 8000

CMD ["python", "-m", "legal_chatbot.main"]

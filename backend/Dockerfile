FROM python:3.12-slim

WORKDIR /app

# torch/transformers pull in a fair amount of native tooling to build cleanly.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system appgroup \
    && adduser --system --ingroup appgroup appuser

COPY requirements.txt .
# CPU-only torch build: the risk classifier runs on CPU (see risk_classifier.py's
# transformers.pipeline() call, no device= argument), so the default PyPI torch
# wheel's bundled CUDA/NVIDIA dependencies are pure multi-GB dead weight here.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appgroup app app
COPY --chown=appuser:appgroup alembic alembic
COPY --chown=appuser:appgroup alembic.ini alembic.ini
COPY --chown=appuser:appgroup scripts scripts
COPY --chown=appuser:appgroup data data

RUN chown appuser:appgroup /app
USER appuser

EXPOSE 8010

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8010"]

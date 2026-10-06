FROM python:3.12-slim

WORKDIR /app

# torch/transformers pull in a fair amount of native tooling to build cleanly.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# CPU-only torch build: the risk classifier runs on CPU (see risk_classifier.py's
# transformers.pipeline() call, no device= argument), so the default PyPI torch
# wheel's bundled CUDA/NVIDIA dependencies are pure multi-GB dead weight here.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

# The knowledge-base embedding model (~130 MB, app/domains/source_library/
# embeddings.py), baked in so a deploy never depends on a Hugging Face
# download at request time. Keep in step with EMBEDDING_MODEL.
RUN python -c "from transformers import AutoModel, AutoTokenizer; \
AutoTokenizer.from_pretrained('BAAI/bge-small-en-v1.5'); AutoModel.from_pretrained('BAAI/bge-small-en-v1.5')"

COPY app app
COPY scripts scripts
COPY data data
COPY alembic alembic
COPY alembic.ini alembic.ini
COPY evals evals
COPY release_revision.txt release_revision.txt
ARG APP_REVISION=unknown
ENV APP_REVISION=$APP_REVISION

EXPOSE 8010

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]

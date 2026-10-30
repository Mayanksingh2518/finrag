# FinRAG API + built web UI. Data, models and secrets come in at runtime (see docker-compose.yml).
#   docker compose up --build

# --- web UI ---------------------------------------------------------------------------------------
FROM node:24-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- API ------------------------------------------------------------------------------------------
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/hf
WORKDIR /app

# CPU-only torch first (the default wheel bundles CUDA, several GB).
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
# Serving dependencies: requirements.txt without the evaluation/test-only packages (RAGAS pulls in
# langchain, datasets, pandas and pyarrow, which the API never imports).
COPY requirements.txt .
RUN grep -vE '^(ragas|langchain-community|pytest)\b' requirements.txt > /tmp/requirements-serve.txt \
    && pip install -r /tmp/requirements-serve.txt

COPY app/ app/
COPY --from=web /web/dist frontend/dist

# Unprivileged user; /hf (model cache) and /app/data are volumes owned by it.
RUN useradd --create-home --uid 1000 finrag && mkdir -p /hf /app/data && chown finrag /hf /app/data
USER finrag

EXPOSE 8010
HEALTHCHECK --interval=15s --timeout=5s --start-period=180s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/api/health', timeout=4)"
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8010"]

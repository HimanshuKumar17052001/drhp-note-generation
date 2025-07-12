# ---------- build stage: grab the model ----------
FROM python:3.12-slim AS builder

ARG MODEL_ID="naver/splade-cocondenser-ensembledistil"
ENV MODEL_ID=${MODEL_ID} \
    HF_HOME=/opt/hf_cache

RUN mkdir -p $HF_HOME

RUN pip install --no-cache-dir "huggingface_hub>=0.23"
COPY model_download.py /tmp/model_download.py
RUN python3 /tmp/model_download.py




# ---------- runtime stage ----------
FROM python:3.12-slim

ENV HF_HOME=/opt/hf_cache \
    PYTHONUNBUFFERED=1 \
    WEB_CONCURRENCY=4 \
    MODEL_ID="naver/splade-cocondenser-ensembledistil"

# bring in the baked-in HF cache
COPY --from=builder /opt/hf_cache /opt/hf_cache


RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*


# ─── 4) UPGRADE PIP / INSTALL UV ────────────────────────────────────────────────
RUN python -m pip install --upgrade pip  
RUN pip install uv

# ─── 5) COPY & INSTALL PYTHON REQUIREMENTS ────────────────────────────────────

# install runtime deps
COPY requirements.txt /tmp/requirements.txt
RUN uv pip install --system --no-cache-dir -r /tmp/requirements.txt

# copy your FastAPI app
COPY app /app
WORKDIR /app

# copy & run our CPU-tuning script
COPY cpu_tune.py /tmp/cpu_tune.py
RUN python3 /tmp/cpu_tune.py



# -- you can still tune this per-host with `docker run -e WEB_CONCURRENCY=8` --
# CMD uvicorn main:app \
# --host 0.0.0.0 \
# --port 8000 \
# --workers $WEB_CONCURRENCY
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8000 --workers $WEB_CONCURRENCY"]






FROM python:3.12-bullseye

# ─── 1) ENVIRONMENT VARIABLES ───────────────────────────────────────────────
ENV MONGO_URI=mongodb-dev.ubuntu_drhp-network:27017
ENV MONGO_DB=drhp_dev
ENV QDRANT_URL=http://qdrant:6333

# Using IAM role for AWS authentication
# ENV AWS_EC2_METADATA_DISABLED=false
ENV AWS_REGION_NAME=ap-south-1
ENV AWS_REGION=ap-south-1

ENV EMBEDDING_MODEL=bedrock/cohere.embed-english-v3
ENV LLM_MODEL=bedrock/apac.anthropic.claude-3-5-sonnet-20241022-v2:0
ENV S3_BUCKET_NAME=drhp-assets-prod-onfi
ENV LLM_MODEL_SUMMARIZER=bedrock/mistral.mistral-large-2402-v1:0

ENV EMAIL_PASSWORD=omaqcstxhduytwde
ENV EMAIL_RECEPIENTS_LIST=Sushil.Ostwal@bseindia.com,abhinav@onfinance.in,priyesh@onfinance.in,avantika@onfinance.in,prathamesh.nikam@bsetech.in

# ─── 2) WORKDIR ───────────────────────────────────────────────────────────────
WORKDIR /app

# ─── 3) SYSTEM DEPENDENCIES ───────────────────────────────────────────────────
# Install build tools, tesseract, etc.
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ─── 4) UPGRADE PIP / INSTALL UV ────────────────────────────────────────────────
RUN python -m pip install --upgrade pip  
RUN pip install uv

# ─── 5) COPY & INSTALL PYTHON REQUIREMENTS ────────────────────────────────────
COPY requirements.txt /app/requirements.txt
RUN uv pip install -r requirements.txt --system

# ─── 6) INSTALL BAML-PY AND RUN GENERATOR ─────────────────────────────────────
# Install the baml-py package into the global environment, then execute the CLI generator.
RUN uv pip install baml-py --system
# (Assuming your project has a baml configuration file checked into /app,
#  this will output generated client code into whichever directory baml-cli
#  is configured to write to—often under /app/src or similar.)


# ─── 7) COPY YOUR APP CODE ─────────────────────────────────────────────────────
COPY . /app

RUN uv run baml-cli generate
# ─── 8) CREATE PERSISTENT QUEUE DIRECTORY ────────────────────────────────────
RUN mkdir -p /app/app/drhp_queue

# ─── 9) EXPOSE & CMD ─────────────────────────────────────────────────────────
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
# uvicorn app.main:app --host 0.0.0.0 --port 8001
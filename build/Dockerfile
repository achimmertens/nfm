# NFM Newsfeed Manager - nativ für ARM64 (Raspberry Pi)
FROM python:3.11-slim

# Build-time version baked into the image (see build/build.sh):
#   GIT_VERSION = "$(git describe --tags --always --dirty)-<build-date>"
# Written to /app/VERSION, which main.py reads at runtime for the visible
# version. This keeps the deployed version traceable to a commit without
# manual version bumps in pyproject.toml.
ARG GIT_VERSION=unknown

WORKDIR /app

# Build-Tools für ggf. nötige Source-Kompilierung (aiohttp o.ä.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Python-Abhängigkeiten (ARM64-Wheels)
COPY build/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ML-Modell vorab einbauen (kein Download zur Laufzeit)
RUN mkdir -p /root/.cache/huggingface
COPY build/hf_cache/ /root/.cache/huggingface/

# App-Code
COPY app/ /app/app/
COPY main.py /app/main.py
COPY pyproject.toml /app/pyproject.toml
COPY aux_data/ /app/aux_data/

# Bake the resolved git version into a runtime-readable file
RUN printf '%s' "${GIT_VERSION}" > /app/VERSION

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

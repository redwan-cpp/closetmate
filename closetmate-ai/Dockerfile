FROM python:3.11-slim

# System dependencies required by OpenCV and rembg
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (cached layer — only rebuilds when requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the background-removal model into the image. Cloud Run's filesystem is
# ephemeral, so without this every cold start re-downloads the ONNX model from
# GitHub — slower starts, and a hard runtime dependency on a third-party host.
ENV U2NET_HOME=/opt/u2net
RUN python -c "from rembg import new_session; new_session('u2netp')"

# Copy application code
COPY . .

# Local-fallback upload dirs (production stores images in GCS — see GCS_BUCKET)
RUN mkdir -p uploads/processed uploads/analyzed

# Cloud Run injects PORT — default to 8080
ENV PORT=8080
EXPOSE 8080

# Per-IP rate limits read X-Forwarded-For themselves (ratelimit.client_ip, TRUSTED_PROXY_HOPS).
# Do NOT add uvicorn's --proxy-headers/--forwarded-allow-ips='*': it trusts the LEFTMOST
# entry, which the client controls, and would let anyone dodge every per-IP limit.
# `exec` makes uvicorn PID 1 so it receives SIGTERM from Cloud Run for graceful shutdown.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT}"]

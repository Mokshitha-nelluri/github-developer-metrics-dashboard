# syntax=docker/dockerfile:1.4

# ---- Builder Stage ----
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System packages needed for pip and psycopg2 etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# Install compatible versions to avoid binary incompatibility
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install --no-cache-dir numpy==1.26.4 && \
    pip install --no-cache-dir scipy==1.11.4 && \
    pip install --no-cache-dir scikit-learn==1.3.2 && \
    pip install --no-cache-dir -r requirements.txt

# ---- Runtime Stage ----
FROM python:3.11-slim

# Install only runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && \
    rm -rf /var/lib/apt/lists/* && \
    useradd -m appuser

WORKDIR /home/appuser/app

# Copy Python dependencies (optimized)
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy only necessary application files
COPY --chown=appuser:appuser app.py .
COPY --chown=appuser:appuser config.py .
COPY --chown=appuser:appuser oauth_server.py .
COPY --chown=appuser:appuser auth_server.py .
COPY --chown=appuser:appuser enhanced_github_api.py .
COPY --chown=appuser:appuser requirements.txt .
COPY --chown=appuser:appuser frontend/ frontend/
COPY --chown=appuser:appuser backend/ backend/
COPY --chown=appuser:appuser ml_models/ ml_models/

# Set environment variables
ENV PYTHONPATH=/home/appuser/app
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
ENV AWS_DEPLOYMENT=true

# Create startup script before switching user
RUN echo '#!/bin/bash' > /home/appuser/app/start.sh && \
    echo 'python oauth_server.py &' >> /home/appuser/app/start.sh && \
    echo 'streamlit run frontend/dashboard.py --server.port=8501 --server.address=0.0.0.0' >> /home/appuser/app/start.sh && \
    chmod +x /home/appuser/app/start.sh && \
    chown appuser:appuser /home/appuser/app/start.sh

# Switch to non-root user
USER appuser

# Expose ports  
EXPOSE 8501 5000

# Run both services
CMD ["/bin/bash", "/home/appuser/app/start.sh"]

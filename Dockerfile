# ==============================================================================
# ResolveSync Admin & Management Dashboard - TrueNAS Dockerfile
# ==============================================================================
FROM python:3.12-slim

# Install system utilities (curl for healthcheck, openssh-client for secure SFTP)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install backend dependencies (Headless TrueNAS server does not need desktop GUI packages)
RUN pip install --no-cache-dir \
    paramiko>=3.4.0 \
    tqdm>=4.66.0 \
    flask>=3.0.0

# Copy application source code
COPY resolvesync.py /app/resolvesync.py
COPY web_server.py /app/web_server.py
COPY config.example.json /app/config.example.json
COPY templates/ /app/templates/

# Define volume mount points for TrueNAS ZFS datasets
# /config   -> TrueNAS AppData (stores config.json)
# /media    -> TrueNAS Media Pool (raw footage, b-roll, audio)
# /projects -> TrueNAS Project Files (synced .drp files)
VOLUME ["/config", "/media", "/projects"]

# Environment defaults
ENV PYTHONUNBUFFERED=1 \
    RESOLVESYNC_CONFIG=/config/config.json \
    RESOLVESYNC_MEDIA_PATH=/media \
    RESOLVESYNC_PROJECTS_PATH=/projects \
    PORT=5000

EXPOSE 5000

# Docker Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5000/api/config || exit 1

# Run web management server
CMD ["python", "web_server.py"]

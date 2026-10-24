#!/bin/bash
# ==============================================================================
# ResolveSync TrueNAS Docker Build & Deploy Script
# ==============================================================================
set -e

echo "=========================================================="
echo "  Deploying ResolveSync Admin & Management on TrueNAS"
echo "=========================================================="

# 1. Check for docker / docker compose
if command -v docker &> /dev/null; then
    echo "[+] Docker detected: $(docker --version)"
else
    echo "[!] Error: Docker is not installed or not in PATH."
    exit 1
fi

# 2. Build the Linux Docker Image
echo "[+] Building Docker image: resolvesync-admin:latest ..."
docker build -t resolvesync-admin:latest .

# 3. Create host directories if they don't exist
echo "[+] Ensuring TrueNAS persistent volume directories exist..."
mkdir -p /mnt/tank/appdata/resolvesync || true

# 4. Launch with Docker Compose
echo "[+] Starting ResolveSync Admin container..."
if docker compose version &> /dev/null; then
    docker compose up -d --build
elif command -v docker-compose &> /dev/null; then
    docker-compose up -d --build
else
    echo "[+] Running standalone container via docker run..."
    docker stop resolvesync-admin 2>/dev/null || true
    docker rm resolvesync-admin 2>/dev/null || true
    docker run -d \
        --name resolvesync-admin \
        --restart unless-stopped \
        -p 5000:5000 \
        -v /mnt/tank/appdata/resolvesync:/config \
        -v /mnt/tank/media:/media \
        -v /mnt/tank/projects:/projects \
        resolvesync-admin:latest
fi

echo "=========================================================="
echo "  ResolveSync Admin successfully deployed!"
echo "  Access the web dashboard at: http://<TRUENAS_IP>:5000"
echo "=========================================================="

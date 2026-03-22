#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# AWS EC2 Setup Script — NIFTY Alpha Bot
# Run this once on a fresh Ubuntu 22.04 t3.small in ap-south-1
# ─────────────────────────────────────────────────────────────────
set -e

echo "=== NIFTY Alpha Bot: AWS EC2 Setup ==="
echo "Region: ap-south-1 (Mumbai) — low latency to NSE"

# 1. System updates
apt-get update -y && apt-get upgrade -y

# 2. Install Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker ubuntu

# 3. Install Docker Compose
COMPOSE_VERSION="v2.27.0"
curl -SL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
    -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# 4. Install certbot for HTTPS
apt-get install -y certbot

# 5. Create app directory
mkdir -p /opt/nifty-bot
cd /opt/nifty-bot

echo ""
echo "=== Setup complete. Next steps: ==="
echo ""
echo "1. Upload your project:"
echo "   scp -r ./nifty-alpha-bot ubuntu@YOUR_EC2_IP:/opt/nifty-bot/"
echo ""
echo "2. Create .env file:"
echo "   cp .env.example .env"
echo "   nano .env   # Fill in your Kite credentials"
echo ""
echo "3. (Optional) Setup HTTPS with Let's Encrypt:"
echo "   certbot certonly --standalone -d yourdomain.com"
echo "   # Then update nginx/nginx.conf to enable HTTPS block"
echo ""
echo "4. Start all services:"
echo "   docker-compose up -d --build"
echo ""
echo "5. Check logs:"
echo "   docker-compose logs -f bot"
echo ""
echo "Your Elastic IP is your SEBI-compliant static IP."
echo "Note it down and register it with Zerodha as your API origin."

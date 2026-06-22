#!/usr/bin/env bash
# One-time server setup. Run as root on the Hetzner box:
#   ssh root@YOUR_IP 'bash -s' < scripts/bootstrap.sh
set -euo pipefail

echo "==> Installing Docker..."
apt-get update -qq
apt-get install -y -qq curl rsync
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

echo "==> Creating app directories..."
mkdir -p /app/data /app/logs /app/www

echo ""
echo "======================================================"
echo "Bootstrap complete. Now create /app/.env:"
echo ""
echo "  nano /app/.env"
echo ""
echo "Required contents:"
echo "  OPENROUTER_API_KEY=your-key-here"
echo "  SECRET_KEY=\$(openssl rand -hex 32)"
echo "  ALLOWED_ORIGINS=https://167-233-84-81.sslip.io"
echo ""
echo "Then push to main — GitHub Actions will deploy everything."
echo "======================================================"

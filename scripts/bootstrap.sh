#!/usr/bin/env bash
# One-time server setup. Run as root on the Hetzner box:
#   ssh root@YOUR_IP 'bash -s' < scripts/bootstrap.sh
set -euo pipefail

echo "==> Installing Docker..."
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker

echo "==> Installing git..."
apt-get install -y -qq git

echo "==> Creating app directory..."
mkdir -p /app
cd /app

echo "==> Cloning repo..."
# Replace with your actual repo URL
git clone https://github.com/TuringCollegeSubmissions/fgrani-AE.3.6.git .

echo "==> Creating data and www directories..."
mkdir -p data logs www

echo ""
echo "======================================================"
echo "Bootstrap complete. Now create /app/.env:"
echo ""
echo "  nano /app/.env"
echo ""
echo "Required contents:"
echo "  OPENROUTER_API_KEY=your-key-here"
echo "  SECRET_KEY=\$(openssl rand -hex 32)"
echo "  ALLOWED_ORIGINS=https://YOUR_IP.sslip.io"
echo ""
echo "Then update Caddyfile with your IP:"
echo "  sed -i 's/YOUR_IP/YOUR_ACTUAL_IP_DASHES/g' /app/Caddyfile"
echo "======================================================"

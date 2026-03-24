#!/bin/bash
# deploy-quantvps.sh — Run once on QuantVPS after SSH login
# Usage: bash deploy-quantvps.sh
set -e

echo "=== Poly-Shadow QuantVPS Deployment ==="

echo "[1/6] Installing system packages..."
apt-get update -qq
apt-get install -y python3 python3-pip git

echo "[2/6] Cloning repository..."
cd /home/ubuntu
git clone https://github.com/you/poly-shadow-agent   # ← update with your URL
cd poly-shadow-agent

echo "[3/6] Installing Python packages..."
pip3 install -r requirements.txt

echo "[4/6] Setting up .env..."
if [ ! -f .env ]; then
  cp .env.example .env
  echo ""
  echo "  ⚠️  Edit .env with your real keys now:"
  echo "  nano /home/ubuntu/poly-shadow-agent/.env"
  echo ""
  read -p "  Press Enter once .env is filled in..."
fi

echo "[5/6] Installing systemd service..."
cp poly-shadow.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable poly-shadow
systemctl start poly-shadow

echo "[6/6] Status check..."
sleep 3
systemctl status poly-shadow --no-pager

echo ""
echo "=== Done ==="
echo "  journalctl -u poly-shadow -f     # live logs"
echo "  systemctl restart poly-shadow     # restart"
echo "  curl localhost:8000/api/healthz   # health check"

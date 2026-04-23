#!/bin/bash
# Cognitive Mirror cloud deployment setup script
# Run as root on the Tencent Cloud server

set -e

echo "=== Cognitive Mirror Cloud Setup ==="

# 1. Install nginx if not present
if ! command -v nginx &> /dev/null; then
    echo "[1/5] Installing nginx..."
    apt-get update -qq && apt-get install -y -qq nginx
else
    echo "[1/5] nginx already installed"
fi

# 2. Create directories
echo "[2/5] Creating directories..."
mkdir -p /opt/cognitive-mirror/dist
mkdir -p /opt/cognitive-mirror/data

# 3. Copy files from deploy package
echo "[3/5] Copying files..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp -r "$SCRIPT_DIR/dist/"* /opt/cognitive-mirror/dist/
cp "$SCRIPT_DIR/api_server.py" /opt/cognitive-mirror/
cp "$SCRIPT_DIR/nginx.conf" /etc/nginx/sites-available/cognitive-mirror 2>/dev/null || \
    cp "$SCRIPT_DIR/nginx.conf" /etc/nginx/conf.d/cognitive-mirror.conf

# Enable site (Debian/Ubuntu style)
if [ -d /etc/nginx/sites-enabled ]; then
    ln -sf /etc/nginx/sites-available/cognitive-mirror /etc/nginx/sites-enabled/
    # Remove default if exists
    rm -f /etc/nginx/sites-enabled/default
fi

# 4. Create systemd service for API server
echo "[4/5] Setting up systemd service..."
cat > /etc/systemd/system/cognitive-mirror.service << 'EOF'
[Unit]
Description=Cognitive Mirror Cloud API
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/cognitive-mirror/api_server.py
WorkingDirectory=/opt/cognitive-mirror
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cognitive-mirror
systemctl restart cognitive-mirror

# 5. Restart nginx
echo "[5/5] Starting nginx..."
nginx -t && systemctl restart nginx

echo ""
echo "=== Done! ==="
echo "API server: http://$(hostname -I | awk '{print $1}'):8773"
echo "Nginx proxy: http://$(hostname -I | awk '{print $1}')"
echo ""
echo "Next: configure your subdomain DNS to point to this IP."

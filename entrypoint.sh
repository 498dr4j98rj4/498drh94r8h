#!/bin/bash
set -e

# Setup WireGuard config directory if it doesn't exist
mkdir -p /etc/wireguard

# Make sure iptables works correctly
# (These lines are usually needed in containers to avoid iptables errors)
update-alternatives --set iptables /usr/sbin/iptables-legacy >/dev/null 2>&1 || true
update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy >/dev/null 2>&1 || true

# Initialize WireGuard config using the Python app
echo "Initializing WireGuard configs..."
python -c "import app.wg_utils as wg_utils; wg_utils.init_server()"

# Start WireGuard
echo "Starting WireGuard..."
wg-quick up wg0 || echo "WARNING: Failed to start wg-quick. Ensure container has NET_ADMIN capabilities."

# Start Flask app using gunicorn
echo "Starting Flask web interface..."
exec gunicorn --bind 0.0.0.0:8080 --workers 2 app.main:app
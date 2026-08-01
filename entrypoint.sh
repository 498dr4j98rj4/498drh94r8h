#!/bin/bash
set -e

# Setup WireGuard config directory if it doesn't exist
mkdir -p /etc/wireguard

# Ensure iptables works correctly in the container environment
update-alternatives --set iptables /usr/sbin/iptables-legacy >/dev/null 2>&1 || true
update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy >/dev/null 2>&1 || true

# Enable IP forwarding for VPN routing
sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || echo "WARNING: Failed to enable IPv4 forwarding"
sysctl -w net.ipv6.conf.all.forwarding=1 >/dev/null 2>&1 || echo "WARNING: Failed to enable IPv6 forwarding"

# Initialize WireGuard config using the Python app
echo "[System] Initializing WireGuard configs..."
python -c "import app.wg_utils as wg_utils; wg_utils.init_server()"

# Start WireGuard using WG-QUICK and Userspace (wireguard-go)
echo "[System] Starting WireGuard..."
# Setting WG_QUICK_USERSPACE_IMPLEMENTATION forces wg-quick to use wireguard-go instead of kernel modules
export WG_QUICK_USERSPACE_IMPLEMENTATION=wireguard-go
export WG_I_PREFER_BUGGY_USERSPACE_TO_POLISHED_KMOD=1

wg-quick up wg0 || {
    echo "CRITICAL ERROR: Failed to start WireGuard."
    echo "Check if the container is running with NET_ADMIN privileges."
    ip link || true
}

echo "[System] WireGuard interface started successfully."

# Start Flask app using gunicorn
echo "[System] Starting Web Dashboard..."
exec gunicorn --bind 0.0.0.0:8080 --workers 2 --timeout 120 app.main:app
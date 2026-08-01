#!/bin/bash
set -e

echo "========================================================="
echo "[System] Container Booting..."
echo "========================================================="

# Setup WireGuard config directory
mkdir -p /etc/wireguard

# --- CRITICAL FIX FOR CONTAINERS: Ensure TUN device exists ---
echo "[System] Checking for TUN device..."
if [ ! -d /dev/net ]; then
    mkdir -p /dev/net
fi
if [ ! -c /dev/net/tun ]; then
    echo "[System] Creating /dev/net/tun node..."
    mknod /dev/net/tun c 10 200 || echo "[Warning] Failed to create /dev/net/tun. Requires privileged container."
    chmod 600 /dev/net/tun || true
fi

# Ensure iptables works correctly in the container environment
update-alternatives --set iptables /usr/sbin/iptables-legacy >/dev/null 2>&1 || true
update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy >/dev/null 2>&1 || true

# Enable IP forwarding for VPN routing (ignore errors in unprivileged containers)
sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || echo "[Warning] Failed to enable IPv4 forwarding (needs privileged mode)"
sysctl -w net.ipv6.conf.all.forwarding=1 >/dev/null 2>&1 || true

# Initialize WireGuard config using the Python app
echo "[System] Initializing WireGuard configs..."
python -c "import app.wg_utils as wg_utils; wg_utils.init_server()"

# Start WireGuard using WG-QUICK and Userspace (wireguard-go)
echo "[System] Starting WireGuard..."
export WG_QUICK_USERSPACE_IMPLEMENTATION=wireguard-go
export WG_I_PREFER_BUGGY_USERSPACE_TO_POLISHED_KMOD=1

set +e
WG_START_OUTPUT=$(wg-quick up wg0 2>&1)
WG_EXIT_CODE=$?
set -e

# Save the startup output to a file so Python can read it for the dashboard
echo "$WG_START_OUTPUT" > /etc/wireguard/wg_startup.log
echo "$WG_EXIT_CODE" > /etc/wireguard/wg_exit_code.log

if [ $WG_EXIT_CODE -eq 0 ]; then
    echo "[System] WireGuard interface wg0 started successfully."
else
    echo "========================================================="
    echo "CRITICAL ERROR: Failed to start WireGuard."
    echo "Exit Code: $WG_EXIT_CODE"
    echo "$WG_START_OUTPUT"
    echo "========================================================="

    if echo "$WG_START_OUTPUT" | grep -q -i "iptables"; then
        echo "[Debug] Attempting to start WireGuard WITHOUT iptables rules..."
        cp /etc/wireguard/wg0.conf /etc/wireguard/wg0_no_iptables.conf
        sed -i '/^PostUp/d' /etc/wireguard/wg0_no_iptables.conf
        sed -i '/^PostDown/d' /etc/wireguard/wg0_no_iptables.conf

        set +e
        WG_START_OUTPUT_2=$(wg-quick up /etc/wireguard/wg0_no_iptables.conf 2>&1)
        WG_EXIT_CODE_2=$?
        set -e
        if [ $WG_EXIT_CODE_2 -eq 0 ]; then
             echo "[System] WireGuard started successfully WITHOUT routing rules."
             echo "SUCCESS_NO_ROUTING" > /etc/wireguard/wg_exit_code.log
        else
             echo "[Warning] WireGuard failed to start even without iptables rules. Bypassing to allow panel to run."
             echo "FAILED_FULLY" > /etc/wireguard/wg_exit_code.log
        fi
    else
        echo "[Warning] WireGuard failed to start for a reason other than iptables. Bypassing to allow panel to run."
        echo "FAILED_FULLY" > /etc/wireguard/wg_exit_code.log
    fi
fi

echo "========================================================="
echo "[System] Starting Web Dashboard on port ${PORT:-8080}..."
echo "========================================================="
exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120 app.main:app
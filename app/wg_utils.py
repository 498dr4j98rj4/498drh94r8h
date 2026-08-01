import os
import subprocess
import json
import logging
from typing import Dict, List, Optional
import qrcode
import io
import base64

logger = logging.getLogger(__name__)

WG_DIR = "/etc/wireguard"
WG_CONF = os.path.join(WG_DIR, "wg0.conf")
PEERS_JSON = os.path.join(WG_DIR, "peers.json")

def run_cmd(cmd: List[str], input_data: str = None) -> str:
    """Run a shell command and return output"""
    try:
        kwargs = {"check": True, "capture_output": True, "text": True}
        if input_data:
            kwargs["input"] = input_data
        result = subprocess.run(cmd, **kwargs)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {' '.join(cmd)}\nError: {e.stderr}")
        raise

def get_server_keys():
    """Get or generate server keys"""
    priv_path = os.environ.get("WG_PRIVATE_KEY_PATH", f"{WG_DIR}/server_private_key")
    pub_path = os.environ.get("WG_PUBLIC_KEY_PATH", f"{WG_DIR}/server_public_key")

    if not os.path.exists(priv_path):
        priv_key = run_cmd(["wg", "genkey"])
        with open(priv_path, "w") as f:
            f.write(priv_key)

        # Generate public key
        process = subprocess.Popen(["wg", "pubkey"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        pub_key, _ = process.communicate(input=priv_key)

        with open(pub_path, "w") as f:
            f.write(pub_key.strip())

    with open(priv_path, "r") as f:
        priv_key = f.read().strip()
    with open(pub_path, "r") as f:
        pub_key = f.read().strip()

    return priv_key, pub_key

def init_server():
    """Initialize server configuration and peers JSON"""
    if not os.path.exists(WG_DIR):
        os.makedirs(WG_DIR, exist_ok=True)

    if not os.path.exists(PEERS_JSON):
        with open(PEERS_JSON, "w") as f:
            json.dump([], f)

    if not os.path.exists(WG_CONF):
        priv_key, _ = get_server_keys()
        wg_port = os.environ.get("WG_PORT", "51820")

        conf = f"""[Interface]
Address = 172.16.0.1/24, 2606:4700:110:85a7:4188:ff40:80ff:8880/120
ListenPort = {wg_port}
PrivateKey = {priv_key}
MTU = 1280
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE; ip6tables -A FORWARD -i %i -j ACCEPT; ip6tables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE; ip6tables -D FORWARD -i %i -j ACCEPT; ip6tables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
"""
        with open(WG_CONF, "w") as f:
            f.write(conf)

def get_peers() -> List[Dict]:
    """Get list of configured peers from JSON and merge with live stats"""
    if not os.path.exists(PEERS_JSON):
        return []

    with open(PEERS_JSON, "r") as f:
        try:
            peers = json.load(f)
        except json.JSONDecodeError:
            peers = []

    # Try to get live stats from wg
    try:
        stats_output = run_cmd(["wg", "show", "wg0", "dump"])
        lines = stats_output.split('\n')[1:] # Skip header

        stats = {}
        for line in lines:
            if not line: continue
            parts = line.split('\t')
            if len(parts) >= 8:
                pubkey = parts[1]
                stats[pubkey] = {
                    "endpoint": parts[3] if parts[3] != "(none)" else None,
                    "allowed_ips": parts[4],
                    "latest_handshake": int(parts[5]),
                    "transfer_rx": int(parts[6]),
                    "transfer_tx": int(parts[7])
                }

        # Merge stats into peers
        for peer in peers:
            pubkey = peer.get("public_key")
            if pubkey in stats:
                peer["stats"] = stats[pubkey]
            else:
                peer["stats"] = None

    except Exception as e:
        logger.warning(f"Failed to get live stats: {e}")
        # Return peers without stats if wg command fails
        for peer in peers:
            peer["stats"] = None

    return peers

def get_next_ip(peers: List[Dict]) -> tuple[str, str]:
    """Find next available IPv4 and IPv6"""
    used_ips_v4 = [peer.get("ip_v4") for peer in peers if peer.get("ip_v4")]
    used_ips_v6 = [peer.get("ip_v6") for peer in peers if peer.get("ip_v6")]

    ip_v4, ip_v6 = None, None

    # IPv4 (172.16.0.2 - 172.16.0.254)
    for i in range(2, 254):
        ip = f"172.16.0.{i}"
        if ip not in used_ips_v4:
            ip_v4 = ip
            break

    # IPv6 (offset from 8881)
    for i in range(1, 254):
        # 888d = 8880 + 13
        # Using a simple hex addition logic for the last part
        hex_suffix = hex(0x8880 + i)[2:]
        ip = f"2606:4700:110:85a7:4188:ff40:80ff:{hex_suffix}"
        if ip not in used_ips_v6:
            ip_v6 = ip
            break

    if not ip_v4 or not ip_v6:
        raise Exception("No more IP addresses available in subnet")

    return ip_v4, ip_v6

def add_peer(name: str) -> Dict:
    """Add a new peer"""
    peers = get_peers()

    # Generate keys for peer
    priv_key = run_cmd(["wg", "genkey"])
    process = subprocess.Popen(["wg", "pubkey"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    pub_key, _ = process.communicate(input=priv_key)
    pub_key = pub_key.strip()

    ip_v4, ip_v6 = get_next_ip(peers)

    new_peer = {
        "id": os.urandom(8).hex(),
        "name": name,
        "ip_v4": ip_v4,
        "ip_v6": ip_v6,
        "public_key": pub_key,
        "private_key": priv_key,
        "created_at": run_cmd(["date", "-Iseconds"])
    }

    peers.append(new_peer)

    # Save to JSON
    with open(PEERS_JSON, "w") as f:
        json.dump(peers, f, indent=2)

    # Append to wg0.conf
    peer_conf = f"""
[Peer]
PublicKey = {pub_key}
AllowedIPs = {ip_v4}/32, {ip_v6}/128
"""
    with open(WG_CONF, "a") as f:
        f.write(peer_conf)

    # Apply changes to running interface if it's up
    try:
        run_cmd(["wg", "set", "wg0", "peer", pub_key, "allowed-ips", f"{ip_v4}/32,{ip_v6}/128"])
    except Exception as e:
        logger.warning(f"Failed to update running wg interface (it might be down): {e}")

    return new_peer

def remove_peer(peer_id: str) -> bool:
    """Remove a peer by ID"""
    peers = get_peers()
    peer_to_remove = next((p for p in peers if p.get("id") == peer_id), None)

    if not peer_to_remove:
        return False

    pubkey = peer_to_remove.get("public_key")

    # Remove from running interface
    try:
        run_cmd(["wg", "set", "wg0", "peer", pubkey, "remove"])
    except Exception as e:
        logger.warning(f"Failed to remove peer from running interface: {e}")

    # Rewrite peers list
    peers = [p for p in peers if p.get("id") != peer_id]
    with open(PEERS_JSON, "w") as f:
        json.dump(peers, f, indent=2)

    # Rewrite wg0.conf
    rewrite_wg_conf(peers)
    return True

def rewrite_wg_conf(peers: List[Dict]):
    """Rewrite entire wg0.conf with current peers"""
    priv_key, _ = get_server_keys()
    wg_port = os.environ.get("WG_PORT", "51820")

    conf = f"""[Interface]
Address = 172.16.0.1/24, 2606:4700:110:85a7:4188:ff40:80ff:8880/120
ListenPort = {wg_port}
PrivateKey = {priv_key}
MTU = 1280
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE; ip6tables -A FORWARD -i %i -j ACCEPT; ip6tables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE; ip6tables -D FORWARD -i %i -j ACCEPT; ip6tables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
"""

    for peer in peers:
        ip_v4 = peer.get('ip_v4') or peer.get('ip') # fallback for old configs
        ip_v6 = peer.get('ip_v6') or '::/128' # fallback
        conf += f"""
[Peer]
PublicKey = {peer.get('public_key')}
AllowedIPs = {ip_v4}/32, {ip_v6}/128
"""

    with open(WG_CONF, "w") as f:
        f.write(conf)

def generate_client_config(peer: Dict) -> str:
    """Generate configuration string for client"""
    _, server_pub = get_server_keys()

    # Allow overriding via environment variables for Railway / Wiresock
    host = os.environ.get("WG_HOST", "498drh94r8h-production.up.railway.app")
    port = os.environ.get("WG_PORT", "51820")

    # Check if Wiresock/Socks parameters are provided via env
    socks_port = os.environ.get("WG_SOCKS_PORT", "")

    ip_v4 = peer.get('ip_v4') or peer.get('ip') # fallback for old configs
    ip_v6 = peer.get('ip_v6') or '::/128'

    config = f"""[Interface]
PrivateKey = {peer.get('private_key')}
Address = {ip_v4}/32, {ip_v6}/128
DNS = 1.1.1.1, 1.0.0.1, 2606:4700:4700::1111, 2606:4700:4700::1001
MTU = 1280
"""

    if socks_port:
        config += f"SocksPort = {socks_port}\n"

    config += f"""
[Peer]
PublicKey = {server_pub}
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = {host}:{port}
PersistentKeepalive = 25
"""
    return config

def generate_qr_b64(config_str: str) -> str:
    """Generate QR code base64 string from config"""
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(config_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"


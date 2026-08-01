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

def run_cmd(cmd: List[str]) -> str:
    """Run a shell command and return output"""
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
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
Address = 10.8.0.1/24
ListenPort = {wg_port}
PrivateKey = {priv_key}
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
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

def get_next_ip(peers: List[Dict]) -> str:
    """Find next available IP in 10.8.0.0/24 subnet"""
    used_ips = [peer.get("ip") for peer in peers if peer.get("ip")]
    # Start from 10.8.0.2 since .1 is the server
    for i in range(2, 254):
        ip = f"10.8.0.{i}"
        if ip not in used_ips:
            return ip
    raise Exception("No more IP addresses available in subnet")

def add_peer(name: str) -> Dict:
    """Add a new peer"""
    peers = get_peers()

    # Generate keys for peer
    priv_key = run_cmd(["wg", "genkey"])
    process = subprocess.Popen(["wg", "pubkey"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    pub_key, _ = process.communicate(input=priv_key)
    pub_key = pub_key.strip()

    # Get pre-shared key for extra security
    psk = run_cmd(["wg", "genpsk"])

    ip = get_next_ip(peers)

    new_peer = {
        "id": os.urandom(8).hex(),
        "name": name,
        "ip": ip,
        "public_key": pub_key,
        "private_key": priv_key,
        "preshared_key": psk,
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
PresharedKey = {psk}
AllowedIPs = {ip}/32
"""
    with open(WG_CONF, "a") as f:
        f.write(peer_conf)

    # Apply changes to running interface if it's up
    try:
        run_cmd(["wg", "set", "wg0", "peer", pub_key, "preshared-key", "/dev/stdin", "allowed-ips", f"{ip}/32"], input_data=psk)
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
Address = 10.8.0.1/24
ListenPort = {wg_port}
PrivateKey = {priv_key}
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
"""

    for peer in peers:
        conf += f"""
[Peer]
PublicKey = {peer.get('public_key')}
PresharedKey = {peer.get('preshared_key')}
AllowedIPs = {peer.get('ip')}/32
"""

    with open(WG_CONF, "w") as f:
        f.write(conf)

def generate_client_config(peer: Dict) -> str:
    """Generate configuration string for client"""
    _, server_pub = get_server_keys()
    host = os.environ.get("WG_HOST", "localhost")
    port = os.environ.get("WG_PORT", "51820")

    return f"""[Interface]
PrivateKey = {peer.get('private_key')}
Address = {peer.get('ip')}/24
DNS = 1.1.1.1, 1.0.0.1

[Peer]
PublicKey = {server_pub}
PresharedKey = {peer.get('preshared_key')}
Endpoint = {host}:{port}
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""

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

# Need slightly modified run_cmd for input data
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

import os
import subprocess
import json
import logging
from typing import Dict, List, Tuple, Any
import qrcode
import io
import base64
import uuid
import datetime
import shutil

logger = logging.getLogger(__name__)

WG_DIR = "/etc/wireguard"
WG_CONF = os.path.join(WG_DIR, "wg0.conf")
PEERS_JSON = os.path.join(WG_DIR, "peers.json")

def run_cmd(cmd: List[str], input_data: str = None, check_err: bool = True) -> str:
    """Run a shell command and return output safely."""
    try:
        kwargs = {"check": check_err, "capture_output": True, "text": True}
        if input_data:
            kwargs["input"] = input_data
        result = subprocess.run(cmd, **kwargs)
        if result.returncode != 0 and check_err:
            raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)
        return result.stdout.strip()
    except Exception as e:
        logger.error(f"Command execution failed: {' '.join(cmd)} | Error: {str(e)}")
        if check_err:
            raise
        return ""

def get_core_info() -> Dict[str, Any]:
    """Gather comprehensive WireGuard Core information and diagnostics."""
    info = {
        "version": "Unknown",
        "implementation": "Unknown",
        "path": "Not Found",
        "status": "Stopped",
        "interface": "wg0",
        "port": "Unknown",
        "diagnostics": []
    }

    # 1. Get Version & Implementation
    wg_path = shutil.which("wg")
    if wg_path:
        info["path"] = wg_path
        ver_out = run_cmd(["wg", "--version"], check_err=False)
        info["version"] = ver_out if ver_out else "Installed (Version Unknown)"

    if shutil.which("wireguard-go"):
        info["implementation"] = "Userspace (wireguard-go)"
    else:
        info["implementation"] = "Kernel Module (wg)"

    # 2. Check System Diagnostics (Why might it be failing?)
    tun_exists = os.path.exists('/dev/net/tun')
    if not tun_exists:
        info["diagnostics"].append("Error: /dev/net/tun device is missing. Hosting provider restricts network interfaces.")

    # Read the startup logs captured by entrypoint.sh
    try:
        if os.path.exists("/etc/wireguard/wg_exit_code.log"):
            with open("/etc/wireguard/wg_exit_code.log", "r") as f:
                exit_code = f.read().strip()

            if exit_code == "0":
                info["status"] = "Active & Running"
            elif exit_code == "SUCCESS_NO_ROUTING":
                info["status"] = "Running (No Internet Routing)"
                info["diagnostics"].append("Warning: iptables failed. VPN connects, but clients cannot browse the internet. Requires NET_ADMIN privileges.")
            else:
                info["status"] = "Failed to Start"
                if os.path.exists("/etc/wireguard/wg_startup.log"):
                    with open("/etc/wireguard/wg_startup.log", "r") as f:
                        err_log = f.read().strip()
                        if "Operation not permitted" in err_log:
                            info["diagnostics"].append("Fatal: Operation not permitted. The container lacks NET_ADMIN or privileged capabilities required to run a VPN.")
                        elif err_log:
                            # Just show the first line of the error to keep it clean
                            info["diagnostics"].append(f"Startup Error: {err_log.splitlines()[0]}")
    except Exception:
        pass

    # 3. Check Live Running Status (double check)
    try:
        ip_link = run_cmd(["ip", "link", "show", "wg0"], check_err=False)
        if "wg0:" in ip_link and "state UNKNOWN" not in ip_link and "state DOWN" not in ip_link:
            info["status"] = "Active & Running"
            port_info = run_cmd(["wg", "show", "wg0", "listen-port"], check_err=False)
            if port_info.isdigit():
                info["port"] = port_info
    except Exception:
        pass

    return info

def get_server_keys() -> Tuple[str, str]:
    """Get or generate master server keys."""
    priv_path = os.environ.get("WG_PRIVATE_KEY_PATH", f"{WG_DIR}/server_private_key")
    pub_path = os.environ.get("WG_PUBLIC_KEY_PATH", f"{WG_DIR}/server_public_key")

    if not os.path.exists(priv_path):
        priv_key = run_cmd(["wg", "genkey"])
        with open(priv_path, "w") as f:
            f.write(priv_key)

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
    """Initialize server configuration ensuring robust defaults."""
    os.makedirs(WG_DIR, exist_ok=True)

    if not os.path.exists(PEERS_JSON):
        with open(PEERS_JSON, "w") as f:
            json.dump([], f)

    if not os.path.exists(WG_CONF):
        priv_key, _ = get_server_keys()
        wg_port = os.environ.get("WG_PORT", "51820")

        # Create base config
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
        logger.info("Generated new wg0.conf base.")

def get_peers() -> List[Dict]:
    """Get list of configured peers from JSON and merge with live wg stats."""
    if not os.path.exists(PEERS_JSON):
        return []

    try:
        with open(PEERS_JSON, "r") as f:
            peers = json.load(f)
    except json.JSONDecodeError:
        logger.error("Corrupted peers.json. Resetting list.")
        peers = []

    # Get live stats from wg
    try:
        stats_output = run_cmd(["wg", "show", "wg0", "dump"], check_err=False)
        if stats_output:
            lines = stats_output.split('\n')[1:] # Skip header
            stats = {}
            for line in lines:
                if not line.strip(): continue
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

            for peer in peers:
                peer["stats"] = stats.get(peer.get("public_key"))
        else:
            for peer in peers: peer["stats"] = None
    except Exception as e:
        logger.warning(f"Stats fetch failed: {e}")
        for peer in peers: peer["stats"] = None

    return peers

def get_next_ips(peers: List[Dict]) -> Tuple[str, str]:
    """Find next available IPv4 and IPv6 ensuring zero overlap."""
    used_v4 = {p.get("ip_v4") for p in peers if p.get("ip_v4")}
    used_v6 = {p.get("ip_v6") for p in peers if p.get("ip_v6")}

    for p in peers:
        if p.get("ip") and not p.get("ip_v4"):
            used_v4.add(p.get("ip"))

    ip_v4 = None
    for i in range(2, 254):
        ip = f"172.16.0.{i}"
        if ip not in used_v4:
            ip_v4 = ip
            break

    ip_v6 = None
    for i in range(1, 254):
        hex_val = hex(0x8880 + i)[2:]
        ip = f"2606:4700:110:85a7:4188:ff40:80ff:{hex_val}"
        if ip not in used_v6:
            ip_v6 = ip
            break

    if not ip_v4 or not ip_v6:
        raise RuntimeError("No available IP addresses in subnet pool.")

    return ip_v4, ip_v6

def add_peer(name: str) -> Dict:
    """Safely create a new peer, generate configs, and apply to system."""
    peers = get_peers()

    priv_key = run_cmd(["wg", "genkey"])
    process = subprocess.Popen(["wg", "pubkey"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    pub_key, _ = process.communicate(input=priv_key)
    pub_key = pub_key.strip()
    psk = run_cmd(["wg", "genpsk"])

    ip_v4, ip_v6 = get_next_ips(peers)
    peer_id = str(uuid.uuid4())

    new_peer = {
        "id": peer_id,
        "name": name,
        "ip_v4": ip_v4,
        "ip_v6": ip_v6,
        "public_key": pub_key,
        "private_key": priv_key,
        "preshared_key": psk,
        "created_at": datetime.datetime.now().isoformat()
    }

    peers.append(new_peer)
    with open(PEERS_JSON, "w") as f:
        json.dump(peers, f, indent=2)

    rewrite_wg_conf(peers)

    # Sync live interface (don't fail if wg0 is down, just sync file)
    try:
        run_cmd(["wg", "set", "wg0", "peer", pub_key, "preshared-key", "/dev/stdin", "allowed-ips", f"{ip_v4}/32,{ip_v6}/128"], input_data=psk, check_err=False)
    except Exception as e:
        logger.warning(f"Could not apply to live interface (may be down): {e}")

    return new_peer

def remove_peer(peer_id: str) -> bool:
    """Remove a peer safely."""
    peers = get_peers()
    peer = next((p for p in peers if p.get("id") == peer_id), None)
    if not peer:
        return False

    try:
        run_cmd(["wg", "set", "wg0", "peer", peer["public_key"], "remove"], check_err=False)
    except Exception:
        pass

    peers = [p for p in peers if p.get("id") != peer_id]
    with open(PEERS_JSON, "w") as f:
        json.dump(peers, f, indent=2)

    rewrite_wg_conf(peers)
    return True

def rewrite_wg_conf(peers: List[Dict]):
    """Rebuild wg0.conf from scratch ensuring no corruption."""
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
    for p in peers:
        v4 = p.get('ip_v4') or p.get('ip')
        v6 = p.get('ip_v6') or '::/128'
        psk = p.get('preshared_key', '')

        conf += f"\n[Peer]\nPublicKey = {p['public_key']}\n"
        if psk:
            conf += f"PresharedKey = {psk}\n"
        conf += f"AllowedIPs = {v4}/32, {v6}/128\n"

    with open(WG_CONF, "w") as f:
        f.write(conf)

def generate_client_config(peer: Dict) -> str:
    """Generate perfect, error-free WireGuard/Wiresock config for client."""
    _, server_pub = get_server_keys()
    host = os.environ.get("WG_HOST", "endpoint.server.com")
    port = os.environ.get("WG_PORT", "51820")
    socks_port = os.environ.get("WG_SOCKS_PORT", "")

    v4 = peer.get('ip_v4') or peer.get('ip')
    v6 = peer.get('ip_v6') or '::/128'

    config = f"""[Interface]
PrivateKey = {peer.get('private_key')}
Address = {v4}/32, {v6}/128
DNS = 1.1.1.1, 1.0.0.1, 2606:4700:4700::1111, 2606:4700:4700::1001
MTU = 1280
"""
    if socks_port:
        config += f"SocksPort = {socks_port}\n"

    config += f"""
[Peer]
PublicKey = {server_pub}"""

    if peer.get('preshared_key'):
        config += f"\nPresharedKey = {peer.get('preshared_key')}"

    config += f"""
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = {host}:{port}
PersistentKeepalive = 25
"""
    return config

def generate_qr_b64(config_str: str) -> str:
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(config_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffered.getvalue()).decode()}"



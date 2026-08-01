import os
import logging
from flask import Flask, render_template, request, jsonify, send_file, Response
import app.wg_utils as wg_utils
import io

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

@app.route('/')
def index():
    """Dashboard view"""
    peers = wg_utils.get_peers()
    server_pub = ""
    try:
        _, server_pub = wg_utils.get_server_keys()
    except Exception as e:
        logger.error(f"Error getting server keys: {e}")

    host = os.environ.get("WG_HOST", "Not configured (Set WG_HOST env var)")
    return render_template('index.html', peers=peers, server_pub=server_pub, host=host)

@app.route('/api/peers', methods=['GET'])
def api_get_peers():
    """API endpoint to get peers with stats"""
    return jsonify(wg_utils.get_peers())

@app.route('/api/peers', methods=['POST'])
def api_add_peer():
    """API endpoint to add a peer"""
    data = request.json
    name = data.get('name', '').strip()

    if not name:
        return jsonify({"error": "Name is required"}), 400

    try:
        peer = wg_utils.add_peer(name)
        return jsonify(peer), 201
    except Exception as e:
        logger.error(f"Error adding peer: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/peers/<peer_id>', methods=['DELETE'])
def api_remove_peer(peer_id):
    """API endpoint to remove a peer"""
    try:
        success = wg_utils.remove_peer(peer_id)
        if success:
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Peer not found"}), 404
    except Exception as e:
        logger.error(f"Error removing peer: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/peer/<peer_id>/config')
def download_config(peer_id):
    """Download peer configuration file"""
    peers = wg_utils.get_peers()
    peer = next((p for p in peers if p.get("id") == peer_id), None)

    if not peer:
        return "Peer not found", 404

    config_str = wg_utils.generate_client_config(peer)

    # Return as downloadable file
    return Response(
        config_str,
        mimetype="text/plain",
        headers={"Content-disposition": f"attachment; filename=wg-client-{peer.get('name')}.conf"}
    )

@app.route('/peer/<peer_id>/qr')
def get_qr_code(peer_id):
    """Get peer configuration as QR code (HTML page)"""
    peers = wg_utils.get_peers()
    peer = next((p for p in peers if p.get("id") == peer_id), None)

    if not peer:
        return "Peer not found", 404

    config_str = wg_utils.generate_client_config(peer)
    qr_b64 = wg_utils.generate_qr_b64(config_str)

    return render_template('qr.html', peer=peer, qr_b64=qr_b64)

if __name__ == '__main__':
    # Initialize server if needed
    try:
        wg_utils.init_server()
    except Exception as e:
        logger.error(f"Failed to initialize server: {e}")

    app.run(host='0.0.0.0', port=8080)

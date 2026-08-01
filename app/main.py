import os
import logging
from flask import Flask, render_template, request, jsonify, send_file, Response
import app.wg_utils as wg_utils

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

@app.route('/')
def index():
    """Main Dashboard View"""
    peers = wg_utils.get_peers()
    server_pub = ""
    try:
        _, server_pub = wg_utils.get_server_keys()
    except Exception as e:
        logger.error(f"Error getting server keys: {e}")

    host = os.environ.get("WG_HOST", "Not configured")
    wg_info = wg_utils.get_core_info()

    return render_template(
        'index.html',
        peers=peers,
        server_pub=server_pub,
        host=host,
        wg_info=wg_info
    )

@app.route('/api/peers', methods=['GET'])
def api_get_peers():
    return jsonify(wg_utils.get_peers())

@app.route('/api/peers', methods=['POST'])
def api_add_peer():
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
    try:
        success = wg_utils.remove_peer(peer_id)
        if success:
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Peer not found"}), 404
    except Exception as e:
        logger.error(f"Error removing peer: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/regenerate_config', methods=['POST'])
def api_regenerate_config():
    """Force regenerate wg0.conf from JSON database to fix broken states."""
    try:
        peers = wg_utils.get_peers()
        wg_utils.rewrite_wg_conf(peers)
        return jsonify({"success": True, "message": "Config regenerated successfully."})
    except Exception as e:
        logger.error(f"Error regenerating config: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/core_status', methods=['GET'])
def api_core_status():
    """Endpoint for AJAX polling of core status."""
    return jsonify(wg_utils.get_core_info())

@app.route('/peer/<peer_id>/config')
def download_config(peer_id):
    peers = wg_utils.get_peers()
    peer = next((p for p in peers if p.get("id") == peer_id), None)

    if not peer:
        return "Peer not found", 404

    config_str = wg_utils.generate_client_config(peer)

    return Response(
        config_str,
        mimetype="text/plain",
        headers={"Content-disposition": f"attachment; filename=wg-client-{peer.get('name')}.conf"}
    )

@app.route('/peer/<peer_id>/qr')
def get_qr_code(peer_id):
    peers = wg_utils.get_peers()
    peer = next((p for p in peers if p.get("id") == peer_id), None)

    if not peer:
        return "Peer not found", 404

    config_str = wg_utils.generate_client_config(peer)
    qr_b64 = wg_utils.generate_qr_b64(config_str)

    return render_template('qr.html', peer=peer, qr_b64=qr_b64)

if __name__ == '__main__':
    try:
        wg_utils.init_server()
    except Exception as e:
        logger.error(f"Failed to initialize server: {e}")

    app.run(host='0.0.0.0', port=8080)

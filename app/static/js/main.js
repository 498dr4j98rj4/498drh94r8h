// Main JavaScript functionality

// Format bytes to human readable format
function formatBytes(bytes, decimals = 2) {
    if (!+bytes) return '0 B';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}

// Format timestamp to relative time
function formatHandshake(timestamp) {
    if (!timestamp || timestamp === 0) return 'Never';
    const now = Math.floor(Date.now() / 1000);
    const diff = now - timestamp;

    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
    return `${Math.floor(diff/86400)}d ago`;
}

// Apply formatters to DOM elements
function applyFormatting() {
    document.querySelectorAll('.rx-bytes, .tx-bytes').forEach(el => {
        const bytes = el.getAttribute('data-bytes');
        if (bytes) el.textContent = formatBytes(bytes);
    });

    document.querySelectorAll('.handshake-time').forEach(el => {
        const time = el.getAttribute('data-time');
        if (time) el.textContent = formatHandshake(time);
    });
}

// Poll API for stats updates
async function pollStats() {
    try {
        const res = await fetch('/api/peers');
        if (!res.ok) return;

        const peers = await res.json();

        peers.forEach(peer => {
            if (peer.stats) {
                const card = document.querySelector(`.peer-item[data-id="${peer.id}"]`);
                if (card) {
                    const rx = card.querySelector('.rx-bytes');
                    const tx = card.querySelector('.tx-bytes');
                    const hs = card.querySelector('.handshake-time');
                    const badge = card.querySelector('.card-header .badge');

                    if (rx) {
                        rx.textContent = formatBytes(peer.stats.transfer_rx);
                        rx.setAttribute('data-bytes', peer.stats.transfer_rx);
                    }
                    if (tx) {
                        tx.textContent = formatBytes(peer.stats.transfer_tx);
                        tx.setAttribute('data-bytes', peer.stats.transfer_tx);
                    }
                    if (hs) {
                        hs.textContent = formatHandshake(peer.stats.latest_handshake);
                        hs.setAttribute('data-time', peer.stats.latest_handshake);
                    }

                    if (badge && peer.stats.latest_handshake > 0) {
                        badge.classList.remove('bg-secondary');
                        badge.classList.add('bg-success');
                    }
                }
            }
        });
    } catch (e) {
        console.error("Polling failed", e);
    }
}

// Add new peer
async function submitAddPeer() {
    const nameInput = document.getElementById('peerName');
    const name = nameInput.value.trim();
    if (!name) return;

    const btn = document.getElementById('addBtn');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span> Adding...';

    try {
        const res = await fetch('/api/peers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });

        if (res.ok) {
            window.location.reload();
        } else {
            const data = await res.json();
            alert(data.error || 'Failed to add peer');
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    } catch (e) {
        alert('Connection error');
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// Delete peer
async function deletePeer(id, name) {
    if (!confirm(`Are you sure you want to delete client "${name}"? This action cannot be undone.`)) return;

    try {
        const res = await fetch(`/api/peers/${id}`, { method: 'DELETE' });

        if (res.ok) {
            const el = document.querySelector(`.peer-item[data-id="${id}"]`);
            if (el) {
                // Fade out animation
                el.style.transition = 'all 0.3s ease';
                el.style.opacity = '0';
                el.style.transform = 'scale(0.9)';

                setTimeout(() => {
                    el.remove();
                    // Reload if we just deleted the last item to show empty state
                    if (document.querySelectorAll('.peer-item').length === 0) {
                        window.location.reload();
                    }
                }, 300);
            } else {
                window.location.reload();
            }
        } else {
            const data = await res.json();
            alert(data.error || 'Failed to delete peer');
        }
    } catch (e) {
        alert('Connection error');
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    applyFormatting();
    // Add staggered animation delay to peer cards
    document.querySelectorAll('.peer-item').forEach((el, index) => {
        el.style.animationDelay = `${index * 0.05}s`;
    });

    // Poll every 5 seconds instead of 10 for more responsive UI
    setInterval(pollStats, 5000);

    // Handle enter key in add peer modal
    document.getElementById('peerName')?.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            submitAddPeer();
        }
    });
});
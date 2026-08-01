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

// Show Toast
function showToast(message, type = 'success') {
    const toastEl = document.getElementById('liveToast');
    const toastBody = document.getElementById('toastMsg');

    toastBody.textContent = message;

    toastEl.classList.remove('bg-primary', 'bg-danger', 'bg-success', 'bg-warning');
    if (type === 'error') toastEl.classList.add('bg-danger');
    else if (type === 'warning') toastEl.classList.add('bg-warning', 'text-dark');
    else toastEl.classList.add('bg-success');

    const toast = new bootstrap.Toast(toastEl);
    toast.show();
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

// Poll API for stats and core updates
async function pollData() {
    try {
        const [peersRes, coreRes] = await Promise.all([
            fetch('/api/peers'),
            fetch('/api/core_status')
        ]);

        if (peersRes.ok) {
            const peers = await peersRes.json();
            peers.forEach(peer => {
                if (peer.stats) {
                    const card = document.querySelector(`.peer-item[data-id="${peer.id}"]`);
                    if (card) {
                        const rx = card.querySelector('.rx-bytes');
                        const tx = card.querySelector('.tx-bytes');
                        const hs = card.querySelector('.handshake-time');
                        const indicator = card.querySelector('.status-indicator');

                        if (rx) { rx.textContent = formatBytes(peer.stats.transfer_rx); rx.setAttribute('data-bytes', peer.stats.transfer_rx); }
                        if (tx) { tx.textContent = formatBytes(peer.stats.transfer_tx); tx.setAttribute('data-bytes', peer.stats.transfer_tx); }
                        if (hs) { hs.textContent = formatHandshake(peer.stats.latest_handshake); hs.setAttribute('data-time', peer.stats.latest_handshake); }

                        if (indicator && peer.stats.latest_handshake > 0) {
                            indicator.classList.remove('inactive');
                            indicator.classList.add('active');
                        }
                    }
                }
            });
        }

        if (coreRes.ok) {
            const core = await coreRes.json();
            const statusEl = document.getElementById('coreStatus');
            if (statusEl) {
                statusEl.innerHTML = `<i class="bi bi-circle-fill me-1" style="font-size:0.6rem"></i> ${core.status}`;
                statusEl.className = `core-val ${core.status.includes('Running') ? 'text-success' : 'text-danger'}`;
            }
        }
    } catch (e) {
        console.error("Polling failed", e);
    }
}

async function regenerateConfig() {
    const btn = document.getElementById('btnRegen');
    const originalHtml = btn.innerHTML;
    btn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i> Working...';
    btn.disabled = true;

    try {
        const res = await fetch('/api/regenerate_config', { method: 'POST' });
        const data = await res.json();

        if (res.ok) {
            showToast('Configurations successfully regenerated and applied.');
        } else {
            showToast(data.error || 'Failed to regenerate configs', 'error');
        }
    } catch (e) {
        showToast('Connection error during regeneration.', 'error');
    } finally {
        btn.innerHTML = originalHtml;
        btn.disabled = false;
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
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Generating...';

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
            showToast(data.error || 'Failed to generate peer config.', 'error');
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    } catch (e) {
        showToast('Connection error', 'error');
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
                el.style.transition = 'all 0.3s ease';
                el.style.opacity = '0';
                el.style.transform = 'scale(0.9)';
                setTimeout(() => {
                    el.remove();
                    if (document.querySelectorAll('.peer-item').length === 0) window.location.reload();
                }, 300);
                showToast(`Peer ${name} deleted.`);
            } else {
                window.location.reload();
            }
        } else {
            const data = await res.json();
            showToast(data.error || 'Failed to delete peer', 'error');
        }
    } catch (e) {
        showToast('Connection error', 'error');
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    applyFormatting();

    document.querySelectorAll('.peer-item').forEach((el, index) => {
        el.style.animationDelay = `${index * 0.05}s`;
    });

    setInterval(pollData, 5000);

    document.getElementById('peerName')?.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            submitAddPeer();
        }
    });
});
// Popup UI logic

async function loadBlockedSites() {
  const storage = await chrome.storage.local.get(['blockedSites']);
  const blockedSites = storage.blockedSites || {};
  
  const statusEl = document.getElementById('status');
  const blockedSitesEl = document.getElementById('blockedSites');
  
  const blockCount = Object.keys(blockedSites).length;
  
  if (blockCount === 0) {
    statusEl.textContent = 'No active blocks';
    blockedSitesEl.innerHTML = '<div class="empty-state">No websites currently blocked</div>';
    return;
  }
  
  statusEl.textContent = `${blockCount} website${blockCount > 1 ? 's' : ''} blocked`;
  
  // Build sites list
  let html = '';
  const now = Date.now() / 1000;
  
  for (const [blockId, blockInfo] of Object.entries(blockedSites)) {
    const remainingSeconds = Math.max(0, blockInfo.unblockTimestamp - now);
    const timeStr = formatTime(remainingSeconds);
    
    const domainsStr = blockInfo.domains.join(', ');
    
    html += `
      <div class="site-item">
        <div class="site-domain">${domainsStr}</div>
        <div class="site-time">Unblocks in ${timeStr}</div>
      </div>
    `;
  }
  
  blockedSitesEl.innerHTML = html;
}

function formatTime(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  } else if (minutes > 0) {
    return `${minutes}m ${secs}s`;
  } else {
    return `${secs}s`;
  }
}

// Load on popup open
loadBlockedSites();

// Refresh every second
setInterval(loadBlockedSites, 1000);

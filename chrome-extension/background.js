// Personal Assistant Website Blocker - Background Service Worker

const COMMAND_FILE_PATH = 'C:/Users/aidan/OneDrive/Documents/personal-assistant/.extension-data/block-commands.json';
const POLL_INTERVAL_MS = 2000; // Poll every 2 seconds
const DYNAMIC_RULE_ID_START = 1000;

let nextRuleId = DYNAMIC_RULE_ID_START;
let lastCommandTimestamp = 0;

// Initialize extension
chrome.runtime.onInstalled.addListener(() => {
  console.log('Personal Assistant Website Blocker installed');
  
  // Initialize storage
  chrome.storage.local.get(['blockedSites'], (result) => {
    if (!result.blockedSites) {
      chrome.storage.local.set({ blockedSites: {} });
    }
  });
  
  // Start polling for commands
  startCommandPolling();
});

// Start polling on startup
chrome.runtime.onStartup.addListener(() => {
  console.log('Personal Assistant Website Blocker started');
  startCommandPolling();
  restoreBlockingRules();
});

function startCommandPolling() {
  setInterval(checkForCommands, POLL_INTERVAL_MS);
}

async function checkForCommands() {
  try {
    const response = await fetch(`file:///${COMMAND_FILE_PATH}?t=${Date.now()}`);
    if (!response.ok) return;
    
    const command = await response.json();
    
    // Check if this is a new command (by timestamp)
    if (command.timestamp && command.timestamp > lastCommandTimestamp) {
      lastCommandTimestamp = command.timestamp;
      await executeCommand(command);
    }
  } catch (error) {
    // File might not exist yet, silently ignore
    // console.log('No command file found or error reading it:', error);
  }
}

async function executeCommand(command) {
  console.log('Executing command:', command);
  
  if (command.command === 'block') {
    await blockWebsites(command.domains, command.unblock_timestamp, command.block_id);
  } else if (command.command === 'unblock') {
    await unblockWebsites(command.domains, command.block_id);
  }
}

async function blockWebsites(domains, unblockTimestamp, blockId) {
  const storage = await chrome.storage.local.get(['blockedSites']);
  const blockedSites = storage.blockedSites || {};
  
  // Create blocking rules
  const rules = [];
  const ruleIds = [];
  
  for (const domain of domains) {
    const ruleId = nextRuleId++;
    ruleIds.push(ruleId);
    
    // Block the domain
    rules.push({
      id: ruleId,
      priority: 1,
      action: {
        type: 'redirect',
        redirect: {
          extensionPath: '/blocked.html'
        }
      },
      condition: {
        urlFilter: `*://*.${domain}/*`,
        resourceTypes: ['main_frame']
      }
    });
    
    // Also block without www
    const ruleId2 = nextRuleId++;
    ruleIds.push(ruleId2);
    
    rules.push({
      id: ruleId2,
      priority: 1,
      action: {
        type: 'redirect',
        redirect: {
          extensionPath: '/blocked.html'
        }
      },
      condition: {
        urlFilter: `*://${domain}/*`,
        resourceTypes: ['main_frame']
      }
    });
  }
  
  // Add rules
  await chrome.declarativeNetRequest.updateDynamicRules({
    addRules: rules
  });
  
  // Store block info
  blockedSites[blockId] = {
    domains: domains,
    ruleIds: ruleIds,
    unblockTimestamp: unblockTimestamp,
    blockId: blockId
  };
  
  await chrome.storage.local.set({ blockedSites });
  
  // Set alarm for auto-unblock
  const alarmName = `unblock_${blockId}`;
  const when = unblockTimestamp * 1000; // Convert to milliseconds
  chrome.alarms.create(alarmName, { when });
  
  console.log(`Blocked ${domains.join(', ')} until ${new Date(when).toLocaleString()}`);
  
  // Update badge to show number of active blocks
  updateBadge();
}

async function unblockWebsites(domains, blockId) {
  const storage = await chrome.storage.local.get(['blockedSites']);
  const blockedSites = storage.blockedSites || {};
  
  const blockInfo = blockedSites[blockId];
  if (!blockInfo) {
    console.log(`Block ${blockId} not found`);
    return;
  }
  
  // Remove blocking rules
  await chrome.declarativeNetRequest.updateDynamicRules({
    removeRuleIds: blockInfo.ruleIds
  });
  
  // Remove from storage
  delete blockedSites[blockId];
  await chrome.storage.local.set({ blockedSites });
  
  // Clear alarm
  const alarmName = `unblock_${blockId}`;
  chrome.alarms.clear(alarmName);
  
  console.log(`Unblocked ${domains.join(', ')}`);
  
  // Update badge
  updateBadge();
  
  // Show notification
  chrome.notifications.create({
    type: 'basic',
    iconUrl: 'icons/icon48.png',
    title: 'Websites Unblocked',
    message: `Access restored to: ${domains.join(', ')}`
  });
}

// Handle alarms (auto-unblock)
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name.startsWith('unblock_')) {
    const blockId = parseInt(alarm.name.replace('unblock_', ''));
    
    const storage = await chrome.storage.local.get(['blockedSites']);
    const blockedSites = storage.blockedSites || {};
    const blockInfo = blockedSites[blockId];
    
    if (blockInfo) {
      await unblockWebsites(blockInfo.domains, blockId);
    }
  }
});

// Restore blocking rules on startup
async function restoreBlockingRules() {
  const storage = await chrome.storage.local.get(['blockedSites']);
  const blockedSites = storage.blockedSites || {};
  
  const now = Date.now() / 1000;
  
  for (const [blockId, blockInfo] of Object.entries(blockedSites)) {
    // Check if block has expired
    if (blockInfo.unblockTimestamp <= now) {
      // Expired, remove it
      await unblockWebsites(blockInfo.domains, parseInt(blockId));
    } else {
      // Still active, recreate the alarm
      const alarmName = `unblock_${blockId}`;
      const when = blockInfo.unblockTimestamp * 1000;
      chrome.alarms.create(alarmName, { when });
      
      console.log(`Restored block for ${blockInfo.domains.join(', ')}`);
    }
  }
  
  updateBadge();
}

async function updateBadge() {
  const storage = await chrome.storage.local.get(['blockedSites']);
  const blockedSites = storage.blockedSites || {};
  const count = Object.keys(blockedSites).length;
  
  if (count > 0) {
    chrome.action.setBadgeText({ text: count.toString() });
    chrome.action.setBadgeBackgroundColor({ color: '#F44336' });
  } else {
    chrome.action.setBadgeText({ text: '' });
  }
}

const PUBLIC_API_URL = "https://ddj1ndsf-8000.inc1.devtunnels.ms/"; // <-- ⚠️ PASTE YOUR PUBLIC API TUNNEL URL HERE
const LOCAL_API_URL = "http://localhost:8000";

// Automatically determine the correct API URL.
// If the frontend is accessed via a dev tunnel, use the public API URL.
// Otherwise (e.g., on localhost), use the local API URL.
const API_BASE_URL = window.location.hostname.includes('devtunnels.ms') ? PUBLIC_API_URL : LOCAL_API_URL;


const alertsContainer = document.getElementById('alerts-container');
const successContainer = document.getElementById('success-container');

async function fetchStatusAndStats() {
    // Fetch system status (traffic light)
    try {
        const statusRes = await fetch(`${API_BASE_URL}/status`);
        if (!statusRes.ok) throw new Error(`API error: ${statusRes.status}`);
        const statusData = await statusRes.json();
        const statusLight = document.getElementById('status-light');
        if (statusData.status === 'INCIDENT') {
            statusLight.textContent = 'INCIDENT';
            statusLight.className = 'status-light incident';
        } else {
            statusLight.textContent = 'ALL GOOD';
            statusLight.className = 'status-light good';
        }
    } catch (error) {
        console.error('Failed to fetch system status:', error);
        document.getElementById('status-light').textContent = 'Error';
    }

    // Fetch key metrics
    try {
        const statsRes = await fetch(`${API_BASE_URL}/stats`);
        if (!statsRes.ok) throw new Error(`API error: ${statsRes.status}`);
        const statsData = await statsRes.json();
        document.getElementById('attempts-blocked').textContent = statsData.attempts_blocked;
        document.getElementById('recent-incidents').textContent = statsData.recent_incidents_24h;
        document.getElementById('uptime').textContent = statsData.uptime_pct + '%';
    } catch (error) {
        console.error('Failed to fetch stats:', error);
    }
}

async function fetchData() {
    // Fetch failed attempts (anomalies)
    fetchAndDisplay(
        `${API_BASE_URL}/alerts?is_anomaly=true`, 
        alertsContainer, 
        'alert', 
        'No new alerts found.'
    );

    // Fetch successful attempts
    fetchAndDisplay(
        `${API_BASE_URL}/alerts?is_anomaly=false`, 
        successContainer, 
        'log', 
        'No successful attempts found.'
    );
}

async function fetchAndDisplay(url, container, itemClass, emptyMessage) {
    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`API responded with status ${response.status}`);
        const items = await response.json();

        container.innerHTML = ''; // Clear previous items

        if (items.length === 0) {
            container.innerHTML = `<p class="no-alerts">${emptyMessage}</p>`;
        } else {
            items.forEach(item => {
                const itemDiv = document.createElement('div');
                itemDiv.className = item.status === 'resolved' ? `${itemClass} alert-resolved` : itemClass;

                const timestamp = new Date(item.timestamp * 1000).toLocaleString();
                const prefix = item.is_anomaly ? 'ALERT' : 'SUCCESS';

                // Extract IP for the block button
                const ipMatch = item.message.match(/\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b/);
                const sourceIp = ipMatch ? ipMatch[0] : null;

                let content = `<strong>[${prefix}]</strong> [${timestamp}] [Status: ${item.status}] ${item.message.replace(/</g, "&lt;").replace(/>/g, "&gt;")}`;

                if (item.is_anomaly && item.status === 'new') {
                    content += ` <button onclick="updateStatus('${item.id}', 'resolved')">Resolve</button>`;
                    if (sourceIp) {
                        content += ` <button onclick="addIpToBlocklist('${sourceIp}')" class="block-btn">Block IP</button>`;
                    }
                } else if (item.is_anomaly && item.status === 'resolved' && !item.reason.includes('blocked IP')) {
                    content += ` <button onclick="updateStatus('${item.id}', 'new')">Re-open</button>`;
                }

                itemDiv.innerHTML = content;
                container.appendChild(itemDiv);
            });
        }
    } catch (error) {
        console.error(`Failed to fetch from ${url}:`, error);
        container.innerHTML = '<p class="no-alerts" style="color: red;">Error fetching data from the API.</p>';
    }
}

async function updateStatus(alertId, newStatus) {
    try {
        const response = await fetch(`${API_BASE_URL}/alerts/${alertId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });
        if (!response.ok) throw new Error(`API responded with status ${response.status}`);
        fetchData(); // Refresh the data immediately after an action
    } catch (error) {
        console.error(`Failed to update status for alert ${alertId}:`, error);
    }
}

async function resolveAllAlerts() {
    if (!confirm('Are you sure you want to resolve all "new" alerts? This action cannot be undone.')) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/alerts/resolve-all`, { method: 'POST' });
        if (!response.ok) throw new Error(`API responded with status ${response.status}`);
        const result = await response.json();
        alert(`${result.updated_count} alerts have been resolved.`);
        fetchData(); // Refresh the data immediately
    } catch (error) {
        console.error('Failed to resolve all alerts:', error);
        alert('An error occurred while resolving alerts. See console for details.');
    }
}

async function fetchIpList(listType) {
    const container = document.getElementById(`${listType}-container`);
    try {
        const response = await fetch(`${API_BASE_URL}/${listType}`);
        if (!response.ok) throw new Error(`API responded with status ${response.status}`);
        const data = await response.json();
        const ips = data[`${listType}ed_ips`];

        container.innerHTML = ''; // Clear previous items

        if (ips.length === 0) {
            container.innerHTML = `<p class="no-alerts">No IPs are currently in this list.</p>`;
        } else {
            ips.forEach(ip => {
                const itemDiv = document.createElement('div');
                itemDiv.className = 'ip-list-item';
                itemDiv.innerHTML = `<span>${ip}</span><button onclick="removeIpFromList('${listType}', '${ip}')">Remove</button>`;
                container.appendChild(itemDiv);
            });
        }
    } catch (error) {
        console.error(`Failed to fetch ${listType}:`, error);
        container.innerHTML = `<p class="no-alerts" style="color: red;">Error fetching ${listType} from the API.</p>`;
    }
}

async function addIpToBlocklist(ipFromAlert = null) {
    const ipInput = document.getElementById('block-ip-input');
    const ip = ipFromAlert || ipInput.value.trim();
    if (!ip) return alert('Please enter an IP address to block.');
    if (ipFromAlert && !confirm(`Are you sure you want to block IP: ${ip}?`)) return;

    await addIpToList('blocklist', ip);
    ipInput.value = ''; // Clear input
}

async function addIpToWhitelist(ipFromAlert = null) {
    const ipInput = document.getElementById('ip-input'); // Assuming you have an input for whitelist
    const ip = ipInput.value.trim();
    if (!ip) return alert('Please enter an IP address to whitelist.');

    await addIpToList('whitelist', ip);
    ipInput.value = ''; // Clear input
}

async function addIpToList(listType, ip) {
    try {
        const response = await fetch(`${API_BASE_URL}/${listType}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip: ip })
        });
        if (!response.ok) throw new Error(`API responded with status ${response.status}`);
        fetchIpList(listType); // Refresh the list
    } catch (error) {
        console.error(`Failed to add IP ${ip} to ${listType}:`, error);
        alert(`Failed to add IP to ${listType}. See console for details.`);
    }
}

async function removeIpFromList(listType, ip) {
    if (!confirm(`Are you sure you want to remove ${ip} from the ${listType}?`)) return;

    try {
        const response = await fetch(`${API_BASE_URL}/${listType}/${ip}`, { method: 'DELETE' });
        if (!response.ok) throw new Error(`API responded with status ${response.status}`);
        fetchIpList(listType); // Refresh the list
    } catch (error) {
        console.error(`Failed to remove IP ${ip} from ${listType}:`, error);
        alert(`Failed to remove IP from ${listType}. See console for details.`);
    }
}

async function updateWebhookUrl() {
    const typeSelect = document.getElementById('webhook-type-select');
    const urlInput = document.getElementById('webhook-url-input');
    const type = typeSelect.value;
    const url = urlInput.value.trim();

    let isValid = false;
    if (type === 'slack' && url.startsWith("https://hooks.slack.com/")) isValid = true;
    if (type === 'discord' && url.startsWith("https://discord.com/api/webhooks/")) isValid = true;

    if (!isValid) {
        return alert(`Please enter a valid ${type.charAt(0).toUpperCase() + type.slice(1)} Webhook URL.`);
    }

    try {
        const response = await fetch(`${API_BASE_URL}/config/webhook`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: type, url: url })
        });
        if (!response.ok) throw new Error(`API responded with status ${response.status}`);
        alert('Webhook URL has been updated successfully!');
    } catch (error) {
        console.error(`Failed to update webhook URL:`, error);
        alert(`Failed to update webhook. See console for details.`);
    }
}

async function fetchWebhookConfig() {
    try {
        const response = await fetch(`${API_BASE_URL}/config/webhook`);
        if (!response.ok) throw new Error(`API responded with status ${response.status}`);
        
        // The endpoint can return an empty body with 200 OK if no config is set
        const text = await response.text();
        if (!text) return; // Nothing to do if no config is saved

        const config = JSON.parse(text);
        if (config && config.url) {
            document.getElementById('webhook-type-select').value = config.type;
            document.getElementById('webhook-url-input').value = config.url;
        }
    } catch (error) {
        console.error('Failed to fetch webhook config:', error);
    }
}

function initializeDashboard() {
    // Set intervals for polling
    setInterval(fetchStatusAndStats, 5000);
    setInterval(fetchData, 5000);

    // Initial fetch
    fetchWebhookConfig();
    fetchStatusAndStats();
    fetchData();
    fetchIpList('whitelist');
    fetchIpList('blocklist');
}

// Run the initialization function when the DOM is fully loaded
document.addEventListener('DOMContentLoaded', initializeDashboard);
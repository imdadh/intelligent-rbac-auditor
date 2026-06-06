"use strict";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let datasetId = null;
let auditId = null;

// ---------------------------------------------------------------------------
// DOM References  (expected IDs from index.html)
// ---------------------------------------------------------------------------
const loadBtn = document.getElementById('load-data-btn');
const runBtn = document.getElementById('run-audit-btn');
const statusMsg = document.getElementById('status-message');
const findingsContainer = document.getElementById('findings-container');
const reportToggle = document.getElementById('report-toggle');
const reportContent = document.getElementById('report-content');
const chatInput = document.getElementById('chat-input');
const chatSendBtn = document.getElementById('chat-send-btn');
const chatOutput = document.getElementById('chat-output');
const datasetIdSpan = document.getElementById('dataset-id');
const auditIdSpan = document.getElementById('audit-id');

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function setStatus(msg, type) {
    if (!statusMsg) return;
    statusMsg.textContent = msg;
    statusMsg.className = 'status-message';
    if (type) statusMsg.classList.add(type);
}

function showError(msg) {
    setStatus(msg, 'error');
}

function showInfo(msg) {
    setStatus(msg, 'info');
}

function showSuccess(msg) {
    setStatus(msg, 'success');
}

function disableBtn(btn, disabled) {
    if (!btn) return;
    btn.disabled = disabled;
}

async function apiRequest(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) {
        // Try to extract error message
        const errMsg = data?.error?.detail || data?.detail || `HTTP ${response.status}`;
        throw new Error(errMsg);
    }
    return data;
}

// ---------------------------------------------------------------------------
// 1. Load Sample Data
// ---------------------------------------------------------------------------
window.loadSampleData = async function loadSampleData() {
    if (loadBtn) {
        loadBtn.disabled = true;
        loadBtn.textContent = 'Loading...';
    }
    showInfo('Loading sample dataset...');

    try {
        // Fetch the sample dataset JSON file served at /data/sample_dataset.json
        const sampleResp = await fetch('/data/sample_dataset.json');
        if (!sampleResp.ok) throw new Error('Failed to fetch sample dataset file');
        const sampleData = await sampleResp.json();

        // POST to the datasets endpoint
        const result = await apiRequest('/api/v1/datasets', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(sampleData)
        });

        datasetId = result.data?.id;
        if (!datasetId) throw new Error('Dataset ID not returned');

        if (datasetIdSpan) datasetIdSpan.textContent = datasetId;
        showSuccess(`Dataset loaded successfully (ID: ${datasetId})`);

        // Enable audit button
        if (runBtn) runBtn.disabled = false;
        if (chatSendBtn) chatSendBtn.disabled = false;
    } catch (err) {
        showError(`Error loading dataset: ${err.message}`);
    } finally {
        if (loadBtn) {
            loadBtn.disabled = false;
            loadBtn.textContent = 'Load Sample Data';
        }
    }
};

// ---------------------------------------------------------------------------
// 2. Trigger Audit
// ---------------------------------------------------------------------------
window.runAudit = async function runAudit() {
    if (!datasetId) {
        showError('No dataset loaded. Please load sample data first.');
        return;
    }

    if (runBtn) {
        runBtn.disabled = true;
        runBtn.textContent = 'Running...';
    }
    // Clear previous results
    if (findingsContainer) findingsContainer.innerHTML = '';
    if (reportContent) reportContent.innerHTML = '';

    showInfo('Triggering audit...');

    try {
        // Create audit
        const createResult = await apiRequest('/api/v1/audits', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dataset_id: datasetId })
        });

        auditId = createResult.data?.id;
        if (!auditId) throw new Error('Audit ID not returned');

        if (auditIdSpan) auditIdSpan.textContent = auditId;
        showInfo(`Audit created (ID: ${auditId}). Waiting for completion...`);

        // Poll until completed or failed
        let status = 'pending';
        let pollCount = 0;
        const maxPolls = 60; // 2 minutes max

        while (status === 'pending' || status === 'running') {
            await sleep(2000);
            pollCount++;
            if (pollCount > maxPolls) {
                throw new Error('Audit timed out. Please try again.');
            }

            const statusResult = await apiRequest(`/api/v1/audits/${auditId}`);
            status = statusResult.data?.status;
            showInfo(`Audit status: ${status}`);

            if (status === 'completed') {
                showSuccess('Audit completed.');
                // Render findings
                const findings = statusResult.data?.findings || [];
                renderFindings(findings);
                // Enable report toggle and chat
                if (reportToggle) reportToggle.disabled = false;
                if (chatSendBtn) chatSendBtn.disabled = false;
                return;
            } else if (status === 'failed') {
                throw new Error('Audit processing failed.');
            }
        }
    } catch (err) {
        showError(`Audit error: ${err.message}`);
    } finally {
        if (runBtn) {
            runBtn.disabled = false;
            runBtn.textContent = 'Run Audit';
        }
    }
};

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// 3. Render Findings
// ---------------------------------------------------------------------------
function renderFindings(findings) {
    if (!findingsContainer) return;
    findingsContainer.innerHTML = '';

    if (!findings || findings.length === 0) {
        findingsContainer.innerHTML = '<p>No findings were produced. All accounts appear correctly provisioned.</p>';
        return;
    }

    // Group by severity for display
    const severityOrder = ['critical', 'high', 'medium', 'low'];
    const grouped = {};
    severityOrder.forEach(sev => grouped[sev] = []);
    findings.forEach(f => {
        const sev = (f.severity || 'low').toLowerCase();
        if (grouped[sev]) grouped[sev].push(f);
        else grouped['low'].push(f);
    });

    const severityLabels = {
        critical: { class: 'severity-critical', label: 'Critical' },
        high: { class: 'severity-high', label: 'High' },
        medium: { class: 'severity-medium', label: 'Medium' },
        low: { class: 'severity-low', label: 'Low' }
    };

    severityOrder.forEach(sev => {
        const items = grouped[sev];
        if (items.length === 0) return;

        const heading = document.createElement('h3');
        heading.textContent = `${sev.charAt(0).toUpperCase() + sev.slice(1)} (${items.length})`;
        heading.className = `finding-group-heading ${sev}`;
        findingsContainer.appendChild(heading);

        items.forEach((finding, idx) => {
            const card = document.createElement('div');
            card.className = 'finding-card';

            const sevInfo = severityLabels[sev] || severityLabels.low;

            card.innerHTML = `
                <div class="finding-header">
                    <span class="severity-badge ${sevInfo.class}">${sevInfo.label}</span>
                    <span class="principal-name">${escapeHtml(finding.principal_name)}</span>
                    <span class="principal-id">(${escapeHtml(finding.principal_id)})</span>
                </div>
                <div class="finding-details">
                    <p><strong>Category:</strong> ${escapeHtml(finding.category)}</p>
                    <p><strong>Principal Type:</strong> ${escapeHtml(finding.principal_type)}</p>
                    <p><strong>Roles:</strong> ${(finding.role_assignments || []).map(ra => escapeHtml(ra.role_name)).join(', ')}</p>
                    <p><strong>Evidence:</strong></p>
                    <ul>
                        ${Object.entries(finding.evidence || {}).map(([k, v]) => `<li>${escapeHtml(k)}: ${escapeHtml(String(v))}</li>`).join('')}
                    </ul>
                    <p><strong>Remediation:</strong> ${escapeHtml(finding.remediation)}</p>
                    <details>
                        <summary>Narrative</summary>
                        <p>${escapeHtml(finding.narrative)}</p>
                    </details>
                </div>
            `;
            findingsContainer.appendChild(card);
        });
    });
}

// ---------------------------------------------------------------------------
// 4. Fetch & Show Report
// ---------------------------------------------------------------------------
window.toggleReport = async function toggleReport(show) {
    if (!auditId) {
        showError('No audit completed. Please run an audit first.');
        return;
    }

    if (show === undefined) {
        // Toggle visibility
        if (reportContent && reportContent.style.display !== 'none') {
            reportContent.style.display = 'none';
            if (reportToggle) reportToggle.textContent = 'Show Report';
            return;
        }
    }

    if (!reportContent) return;

    try {
        const response = await fetch(`/api/v1/audits/${auditId}/report?format=markdown`);
        if (!response.ok) throw new Error(`Report fetch failed: ${response.status}`);
        const markdown = await response.text();

        // Simple markdown-to-HTML conversion (basic) – for demo we'll just render as pre
        // A production version would use a library, but we'll keep it simple.
        // We can use a basic converter or just display as pre-formatted text.
        // The PRD expects the report to be displayed as HTML, we'll do a light conversion:
        const html = simpleMarkdownToHtml(markdown);
        reportContent.innerHTML = html;
        reportContent.style.display = 'block';
        if (reportToggle) reportToggle.textContent = 'Hide Report';
    } catch (err) {
        showError(`Error fetching report: ${err.message}`);
    }
};

// Very basic Markdown → HTML converter for headings, bold, lists, code, lines
function simpleMarkdownToHtml(md) {
    let html = md
        .replace(/^### (.+)$/gm, '<h3>$1</h3>')
        .replace(/^## (.+)$/gm, '<h2>$1</h2>')
        .replace(/^# (.+)$/gm, '<h1>$1</h1>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/^- (.+)$/gm, '<li>$1</li>')
        .replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>')
        .replace(/\n{2,}/g, '</p><p>')
        .trim();
    return `<p>${html}</p>`;
}

// ---------------------------------------------------------------------------
// 5. Send Query
// ---------------------------------------------------------------------------
window.sendQuery = async function sendQuery() {
    if (!datasetId) {
        showError('No dataset loaded. Please load sample data first.');
        return;
    }
    const question = chatInput?.value?.trim();
    if (!question) return;

    if (chatSendBtn) chatSendBtn.disabled = true;
    showInfo('Processing query...');

    try {
        const result = await apiRequest('/api/v1/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dataset_id: datasetId, question })
        });

        const queryResponse = result.data;

        // Display in chat output
        const userMsg = document.createElement('div');
        userMsg.className = 'chat-message user';
        userMsg.textContent = question;
        chatOutput.appendChild(userMsg);

        const botMsg = document.createElement('div');
        botMsg.className = 'chat-message bot';
        botMsg.innerHTML = queryResponse.answerable
            ? `<p>${escapeHtml(queryResponse.natural_language_summary)}</p>`
            : `<p><em>${escapeHtml(queryResponse.natural_language_summary)}</em></p>`;
        if (queryResponse.structured_data?.length) {
            const pre = document.createElement('pre');
            pre.textContent = JSON.stringify(queryResponse.structured_data, null, 2);
            botMsg.appendChild(pre);
        }
        chatOutput.appendChild(botMsg);
        chatOutput.scrollTop = chatOutput.scrollHeight;

        // Clear input
        chatInput.value = '';
        showSuccess('Query answered.');
    } catch (err) {
        showError(`Query error: ${err.message}`);
    } finally {
        if (chatSendBtn) chatSendBtn.disabled = false;
    }
};

// ---------------------------------------------------------------------------
// Utility: Escape HTML
// ---------------------------------------------------------------------------
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Initialization: disable buttons until data is loaded
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', function() {
    if (runBtn) runBtn.disabled = true;
    if (reportToggle) reportToggle.disabled = true;
    if (chatSendBtn) chatSendBtn.disabled = true;
});

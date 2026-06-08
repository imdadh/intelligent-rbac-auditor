// Intelligent RBAC Policy Auditor — Web UI interactivity
// Vanilla JavaScript, no framework dependencies.

(function () {
  'use strict';

  // ------------------------------------------------------------------
  // State
  // ------------------------------------------------------------------
  let currentDatasetId = null;
  let currentAuditId = null;
  let pollingInterval = null;

  // ------------------------------------------------------------------
  // DOM references
  // ------------------------------------------------------------------
  const btnLoadSample = document.getElementById('btn-load-sample');
  const btnRunAudit = document.getElementById('btn-run-audit');
  const btnQuery = document.getElementById('btn-query');
  const inputQuery = document.getElementById('query-input');
  const loadStatus = document.getElementById('load-status');
  const auditStatus = document.getElementById('audit-status');
  const findingsContainer = document.getElementById('findings-container');
  const reportDetails = document.getElementById('report-details');
  const reportContent = document.getElementById('report-content');
  const queryResponse = document.getElementById('query-response');

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------

  function setStatus(el, text, isError) {
    el.textContent = text;
    el.className = 'status-text' + (isError ? ' error' : ' success');
  }

  function enableButton(btn, enabled) {
    btn.disabled = !enabled;
  }

  function showPlaceholder(container, text) {
    container.innerHTML = '<p class="placeholder">' + escapeHtml(text) + '</p>';
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  // ------------------------------------------------------------------
  // API base
  // ------------------------------------------------------------------
  const API_BASE = '/api/v1';

  async function apiPost(endpoint, body) {
    const res = await fetch(API_BASE + endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.error?.message || 'Request failed');
    }
    return res.json();
  }

  async function apiGet(endpoint) {
    const res = await fetch(API_BASE + endpoint);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.error?.message || 'Request failed');
    }
    return res.json();
  }

  // ------------------------------------------------------------------
  // Step 1 — Load Sample Dataset
  // ------------------------------------------------------------------

  btnLoadSample.addEventListener('click', async function () {
    btnLoadSample.disabled = true;
    setStatus(loadStatus, 'Loading...');
    try {
      const res = await fetch('/api/v1/datasets/sample', { method: 'POST' });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to load sample dataset');
      }
      const data = await res.json();
      currentDatasetId = data.data.id;
      setStatus(loadStatus, '✅ Dataset loaded (' + data.data.user_count + ' users)');
      enableButton(btnRunAudit, true);
      enableButton(inputQuery, false);
      enableButton(btnQuery, false);
      showPlaceholder(findingsContainer, 'Run an audit to see findings.');
    } catch (err) {
      setStatus(loadStatus, '❌ ' + err.message, true);
    } finally {
      btnLoadSample.disabled = false;
    }
  });

  // ------------------------------------------------------------------
  // Step 2 — Run Audit
  // ------------------------------------------------------------------

  btnRunAudit.addEventListener('click', async function () {
    if (!currentDatasetId) return;
    btnRunAudit.disabled = true;
    setStatus(auditStatus, 'Triggering audit...');
    try {
      const res = await fetch('/api/v1/audits', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dataset_id: currentDatasetId })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to trigger audit');
      }
      const data = await res.json();
      currentAuditId = data.data.id;
      setStatus(auditStatus, '⏳ Audit pending...');
      // Poll for completion
      pollAuditStatus(currentAuditId);
    } catch (err) {
      setStatus(auditStatus, '❌ ' + err.message, true);
      btnRunAudit.disabled = false;
    }
  });

  function pollAuditStatus(auditId) {
    if (pollingInterval) clearInterval(pollingInterval);
    pollingInterval = setInterval(async function () {
      try {
        const data = await apiGet('/audits/' + auditId);
        const audit = data.data;
        switch (audit.status) {
          case 'pending':
          case 'running':
            setStatus(auditStatus, '⏳ Audit ' + audit.status + '...');
            break;
          case 'completed':
            clearInterval(pollingInterval);
            pollingInterval = null;
            setStatus(auditStatus, '✅ Audit completed (' + audit.summary?.total_findings + ' findings)');
            renderFindings(audit.findings);
            // Enable query interface
            enableButton(inputQuery, true);
            enableButton(btnQuery, true);
            inputQuery.focus();
            // Load the narrative report (content inside <details>)
            loadReport(auditId);
            break;
          case 'failed':
            clearInterval(pollingInterval);
            pollingInterval = null;
            setStatus(auditStatus, '❌ Audit failed', true);
            enableButton(btnRunAudit, true);
            break;
        }
      } catch (err) {
        clearInterval(pollingInterval);
        pollingInterval = null;
        setStatus(auditStatus, '❌ Polling error: ' + err.message, true);
        enableButton(btnRunAudit, true);
      }
    }, 2000);
  }

  // ------------------------------------------------------------------
  // Step 3 — Render Findings
  // ------------------------------------------------------------------

  function renderFindings(findings) {
    if (!findings || findings.length === 0) {
      findingsContainer.innerHTML = '<p class="placeholder">No findings — all accounts appear correctly provisioned.</p>';
      return;
    }

    const severityColors = { critical: '#e53935', high: '#fb8c00', medium: '#fdd835', low: '#bdbdbd' };
    const severityLabels = { critical: 'CRITICAL', high: 'HIGH', medium: 'MEDIUM', low: 'LOW' };

    let html = '';
    findings.forEach(function (f) {
      const color = severityColors[f.severity] || '#bdbdbd';
      const label = severityLabels[f.severity] || 'UNKNOWN';
      html += '<div class="finding-card" style="border-left: 4px solid ' + color + ';">';
      html += '<div class="finding-header">';
      html += '<span class="severity-badge" style="background:' + color + ';">' + escapeHtml(label) + '</span>';
      html += '<strong>' + escapeHtml(f.principal_name) + '</strong>';
      html += '</div>';
      html += '<div class="finding-details" style="display:none;">';
      html += '<p><em>' + escapeHtml(f.category) + '</em> — ' + escapeHtml(f.remediation) + '</p>';
      html += '<p>' + escapeHtml(f.narrative) + '</p>';
      html += '</div>';
      html += '</div>';
    });

    findingsContainer.innerHTML = html;

    // Add click to expand details
    var cards = findingsContainer.querySelectorAll('.finding-header');
    cards.forEach(function (header) {
      header.addEventListener('click', function () {
        var details = this.nextElementSibling;
        if (details && details.classList.contains('finding-details')) {
          details.style.display = details.style.display === 'none' ? 'block' : 'none';
        }
      });
    });
  }

  // ------------------------------------------------------------------
  // Load and Display Markdown Report (rendered as HTML)
  // ------------------------------------------------------------------

  async function loadReport(auditId) {
    try {
      const res = await fetch('/api/v1/audits/' + auditId + '/report?format=markdown');
      if (!res.ok) {
        reportContent.innerHTML = '<p class="placeholder">Failed to load report.</p>';
        return;
      }
      const markdown = await res.text();
      // Render using marked (included via CDN)
      const html = marked.parse(markdown, { breaks: true, gfm: true });
      reportContent.innerHTML = '<div class="report-html">' + html + '</div>';
      // Automatically open the collapsible section
      reportDetails.open = true;
    } catch (err) {
      reportContent.innerHTML = '<p class="placeholder">Error loading report: ' + escapeHtml(err.message) + '</p>';
    }
  }

  // ------------------------------------------------------------------
  // Step 4 — Query
  // ------------------------------------------------------------------

  btnQuery.addEventListener('click', async function () {
    var question = inputQuery.value.trim();
    if (!question || !currentDatasetId) return;
    btnQuery.disabled = true;
    queryResponse.innerHTML = '<p class="placeholder">Thinking...</p>';
    try {
      var res = await fetch('/api/v1/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dataset_id: currentDatasetId, question: question })
      });
      if (!res.ok) {
        var err = await res.json();
        throw new Error(err.detail || 'Query failed');
      }
      var data = await res.json();
      var ans = data.data;
      if (ans.answerable) {
        var html = '<div class="query-result">' +
          '<p><strong>' + escapeHtml(ans.natural_language_summary) + '</strong></p>';
        if (ans.structured_data && ans.structured_data.length > 0) {
          html += '<pre>' + escapeHtml(JSON.stringify(ans.structured_data, null, 2)) + '</pre>';
        }
        html += '</div>';
        queryResponse.innerHTML = html;
      } else {
        queryResponse.innerHTML = '<p class="placeholder">' + escapeHtml(ans.natural_language_summary) + '</p>';
      }
    } catch (err) {
      queryResponse.innerHTML = '<p class="placeholder error">❌ ' + escapeHtml(err.message) + '</p>';
    } finally {
      btnQuery.disabled = false;
    }
  });

  // Also allow Enter key in query input
  inputQuery.addEventListener('keypress', function (e) {
    if (e.key === 'Enter' && !btnQuery.disabled) {
      btnQuery.click();
    }
  });

  // ------------------------------------------------------------------
  // Initial state
  // ------------------------------------------------------------------

  enableButton(btnRunAudit, false);
  enableButton(inputQuery, false);
  enableButton(btnQuery, false);

})();

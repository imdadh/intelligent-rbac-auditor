// -----------------------------------------------------------------------
// RBAC Policy Auditor — Single‑Page Application Logic
// -----------------------------------------------------------------------

// State
let currentDatasetId = null;
let currentAuditId = null;

// DOM references (cached once on load)
const loadSampleBtn = document.getElementById("load-sample-btn");
const loadStatusEl = document.getElementById("load-status");
const runAuditBtn = document.getElementById("run-audit-btn");
const auditStatusEl = document.getElementById("audit-status");
const findingsContainer = document.getElementById("findings-container");
const reportDetails = document.getElementById("report-details");
const reportContent = document.getElementById("report-content");
const queryInput = document.getElementById("query-input");
const queryBtn = document.getElementById("query-btn");
const queryResponse = document.getElementById("query-response");

// -----------------------------------------------------------------------
// Utility: build full API URL
// -----------------------------------------------------------------------
function apiUrl(path) {
  return `/api/v1${path}`;
}

// -----------------------------------------------------------------------
// Utility: show status message
// -----------------------------------------------------------------------
function setStatus(el, message, type) {
  el.textContent = message;
  el.className = `status-message status-${type}`;
}

// -----------------------------------------------------------------------
// 1. Load Sample Data
// -----------------------------------------------------------------------
loadSampleBtn.addEventListener("click", loadSampleData);

async function loadSampleData() {
  setStatus(loadStatusEl, "Loading sample dataset...", "info");
  try {
    const resp = await fetch(apiUrl("/datasets/sample"), {
      method: "POST",
      headers: { "Accept": "application/json" },
    });
    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      const detail = errData.detail || `HTTP ${resp.status}`;
      throw new Error(detail);
    }
    const json = await resp.json();
    currentDatasetId = json.data.id;
    setStatus(
      loadStatusEl,
      `✅ Sample dataset loaded (ID: ${currentDatasetId}, users: ${json.data.user_count})`,
      "success"
    );
    // Enable the audit button and clear previous audit/findings
    runAuditBtn.disabled = false;
    auditStatusEl.textContent = "";
    findingsContainer.innerHTML =
      '<p class="placeholder">Run an audit to see findings.</p>';
    reportDetails.removeAttribute("open");
    reportContent.innerHTML = "";
    queryInput.disabled = true;
    queryBtn.disabled = true;
    queryResponse.textContent = "";
  } catch (err) {
    setStatus(loadStatusEl, `❌ Failed to load sample data: ${err.message}`, "error");
  }
}

// -----------------------------------------------------------------------
// 2. Run Audit
// -----------------------------------------------------------------------
runAuditBtn.addEventListener("click", runAudit);

async function runAudit() {
  if (!currentDatasetId) {
    setStatus(auditStatusEl, "No dataset loaded. Please load sample data first.", "error");
    return;
  }

  setStatus(auditStatusEl, "Triggering audit...", "info");
  runAuditBtn.disabled = true;

  try {
    const resp = await fetch(apiUrl("/audits"), {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ dataset_id: currentDatasetId }),
    });
    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${resp.status}`);
    }
    const json = await resp.json();
    currentAuditId = json.data.id;
    setStatus(auditStatusEl, `Audit started (ID: ${currentAuditId}). Polling for results...`, "info");

    // Poll until completed or failed
    await pollAuditStatus(currentAuditId);
  } catch (err) {
    setStatus(auditStatusEl, `❌ Audit failed: ${err.message}`, "error");
    runAuditBtn.disabled = false;
  }
}

async function pollAuditStatus(auditId) {
  const maxAttempts = 30;  // roughly 60 seconds
  let attempts = 0;

  while (attempts < maxAttempts) {
    await new Promise((r) => setTimeout(r, 2000));
    attempts++;

    try {
      const resp = await fetch(apiUrl(`/audits/${auditId}`), {
        headers: { "Accept": "application/json" },
      });
      if (!resp.ok) continue;
      const json = await resp.json();
      const status = json.data.status;

      if (status === "completed") {
        setStatus(auditStatusEl, `✅ Audit completed (${json.data.findings?.length || 0} findings).`, "success");
        displayFindings(json.data);
        fetchMarkdownReport(auditId);
        runAuditBtn.disabled = false;
        queryInput.disabled = false;
        queryBtn.disabled = false;
        queryResponse.textContent = "";
        return;
      } else if (status === "failed") {
        throw new Error("Audit processing failed.");
      }
      // else "running" or "pending" — keep polling
      setStatus(auditStatusEl, `Processing... (attempt ${attempts})`, "info");
    } catch (err) {
      setStatus(auditStatusEl, `❌ Error polling audit: ${err.message}`, "error");
      runAuditBtn.disabled = false;
      return;
    }
  }

  setStatus(auditStatusEl, "❌ Audit did not finish within the expected time.", "error");
  runAuditBtn.disabled = false;
}

// -----------------------------------------------------------------------
// 3. Display Findings
// -----------------------------------------------------------------------
function displayFindings(auditData) {
  const findings = auditData.findings || [];
  if (findings.length === 0) {
    findingsContainer.innerHTML = '<p class="placeholder">No findings — all accounts appear correctly provisioned.</p>';
    return;
  }

  const severityOrder = ["critical", "high", "medium", "low"];
  const severityEmoji = { critical: "🔴", high: "🟠", medium: "🟡", low: "⚪" };

  let html = "<ul class='findings-list'>";
  for (const sev of severityOrder) {
    const items = findings.filter((f) => f.severity === sev);
    if (items.length === 0) continue;
    html += `<li><h3 class="severity-group severity-${sev}">${severityEmoji[sev]} ${sev.charAt(0).toUpperCase() + sev.slice(1)} (${items.length})</h3><ul>`;
    for (const f of items) {
      html += `
        <li class="finding-card">
          <div class="finding-header">
            <span class="severity-badge severity-${f.severity}">${f.severity}</span>
            <strong>${f.principal_name}</strong> (${f.principal_id.slice(0, 8)}…)
          </div>
          <div class="finding-body">
            <p><strong>Category:</strong> ${f.category}</p>
            <p><strong>Roles:</strong> ${f.role_assignments.map(ra => ra.role_name).join(", ")}</p>
            <p><strong>Evidence:</strong></p>
            <ul>${Object.entries(f.evidence).map(([k, v]) => `<li>${k}: ${v}</li>`).join("")}</ul>
            <p><strong>Remediation:</strong> ${f.remediation}</p>
            <details>
              <summary>📝 Narrative</summary>
              <p>${f.narrative}</p>
            </details>
          </div>
        </li>`;
    }
    html += "</ul></li>";
  }
  html += "</ul>";

  findingsContainer.innerHTML = html;
}

// -----------------------------------------------------------------------
// 3b. Fetch and render Markdown narrative report
// -----------------------------------------------------------------------
async function fetchMarkdownReport(auditId) {
  try {
    const resp = await fetch(`/api/v1/audits/${auditId}/report?format=markdown`);
    if (!resp.ok) {
      reportContent.innerHTML = `<p class="error">Failed to fetch report (HTTP ${resp.status})</p>`;
      return;
    }
    const md = await resp.text();
    // Simple markdown-to-HTML conversion for the most common patterns
    const html = md
      .replace(/^### (.+)$/gm, "<h4>$1</h4>")
      .replace(/^## (.+)$/gm, "<h3>$1</h3>")
      .replace(/^# (.+)$/gm, "<h2>$1</h2>")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/^- (.+)$/gm, "<li>$1</li>")
      .replace(/\n{2,}/g, "\n<br>\n");
    reportContent.innerHTML = html;
    reportDetails.setAttribute("open", "");
  } catch (err) {
    reportContent.innerHTML = `<p class="error">Error loading report: ${err.message}</p>`;
  }
}

// -----------------------------------------------------------------------
// 4. Query Interface
// -----------------------------------------------------------------------
queryBtn.addEventListener("click", askQuestion);
queryInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") askQuestion();
});

async function askQuestion() {
  const question = queryInput.value.trim();
  if (!question) {
    queryResponse.textContent = "Please enter a question.";
    return;
  }

  queryResponse.textContent = "Thinking...";
  queryBtn.disabled = true;

  try {
    const resp = await fetch(apiUrl("/query"), {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ dataset_id: currentDatasetId, question }),
    });
    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${resp.status}`);
    }
    const json = await resp.json();
    const data = json.data;
    let output = "";
    if (data.answerable) {
      output += `<p><strong>Answer:</strong> ${data.natural_language_summary}</p>`;
      if (data.structured_data && data.structured_data.length > 0) {
        output += "<pre>" + JSON.stringify(data.structured_data, null, 2) + "</pre>";
      }
    } else {
      output = `<p class="warning">⚠️ ${data.natural_language_summary}</p>`;
    }
    queryResponse.innerHTML = output;
  } catch (err) {
    queryResponse.innerHTML = `<p class="error">❌ ${err.message}</p>`;
  } finally {
    queryBtn.disabled = false;
  }
}

// -----------------------------------------------------------------------
// Initial state: disable interactive sections
// -----------------------------------------------------------------------
runAuditBtn.disabled = true;
queryInput.disabled = true;
queryBtn.disabled = true;

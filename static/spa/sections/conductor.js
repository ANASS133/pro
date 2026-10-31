/**
 * JobScout Conductor — Central Autonomous Orchestration Dashboard
 * Manages client automation toggles, daily search cycles, staged application approvals,
 * recruitment email inbox monitoring, WhatsApp liaison triggers, task queues, and emergency stop.
 */
(function () {
    window.SPASections = window.SPASections || {};

    function escapeHtml(str) {
        return String(str == null ? "" : str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function formatIsoTime(isoStr) {
        if (!isoStr) return "—";
        try {
            const d = new Date(isoStr);
            if (isNaN(d.getTime())) return escapeHtml(isoStr);
            return d.toLocaleString("de-DE", {
                day: "2-digit",
                month: "2-digit",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit",
            });
        } catch (_) {
            return escapeHtml(isoStr);
        }
    }

    window.SPASections.createConductorSection = function () {
        const root = document.getElementById("conductor-dashboard-root");
        let pollTimer = null;
        let activeTab = "clients";
        let state = {
            status: null,
            matches: [],
            matchFilterClient: "",
            matchFilterStatus: "",
            toastMessage: "",
            toastType: "info",
            loading: false,
        };

        function showToast(msg, type = "info") {
            state.toastMessage = msg;
            state.toastType = type;
            renderToastOnly();
            setTimeout(() => {
                if (state.toastMessage === msg) {
                    state.toastMessage = "";
                    renderToastOnly();
                }
            }, 4500);
        }

        function renderToastOnly() {
            const toastEl = document.getElementById("conductor-toast-banner");
            if (!toastEl) return;
            if (!state.toastMessage) {
                toastEl.hidden = true;
                toastEl.textContent = "";
                return;
            }
            toastEl.hidden = false;
            toastEl.textContent = state.toastMessage;
            toastEl.className = `conductor-toast is-${state.toastType}`;
        }

        async function fetchAllData() {
            try {
                const params = new URLSearchParams();
                if (state.matchFilterClient) params.set("client_id", state.matchFilterClient);
                if (state.matchFilterStatus) params.set("status", state.matchFilterStatus);
                params.set("limit", "100");

                const [statusRes, matchesRes] = await Promise.all([
                    fetch("/api/conductor/status"),
                    fetch(`/api/conductor/matches?${params.toString()}`),
                ]);
                const statusJson = await statusRes.json();
                const matchesJson = await matchesRes.json();

                if (statusJson && statusJson.success) {
                    state.status = statusJson.data;
                }
                if (matchesJson && matchesJson.success) {
                    state.matches = matchesJson.matches || [];
                }
                render();
            } catch (err) {
                console.error("Failed loading Conductor status:", err);
            }
        }

        function buildShellHtml() {
            const st = state.status || {};
            const metrics = st.metrics || {};
            const isRunning = Boolean(st.is_running);
            const emergencyStop = Boolean(st.emergency_stop);
            const clients = st.clients || [];
            const tasks = st.recent_tasks || [];
            const logs = st.recent_logs || [];
            const inboxLogs = st.recent_inbox_logs || [];
            const settings = st.settings || {};

            const badgeClass = emergencyStop
                ? "is-emergency"
                : isRunning
                ? "is-running"
                : "is-stopped";
            const badgeLabel = emergencyStop
                ? "EMERGENCY STOP ACTIVE"
                : isRunning
                ? "Autopilot Active"
                : "Worker Paused";

            return `
                <div class="wa-dashboard-container conductor-wrap">
                    <!-- Header -->
                    <header class="wa-header">
                        <div class="wa-header-left">
                            <div class="wa-title-row">
                                <span class="wa-badge-live ${badgeClass}">
                                    <span class="wa-pulse-dot"></span>
                                    <span>${badgeLabel}</span>
                                </span>
                                <h1 class="wa-title">JobScout Conductor — Autonomous Orchestrator</h1>
                            </div>
                            <p class="wa-subtitle">Central multi-agent engine coordinating onboarding, daily job &amp; Ausbildung discovery, cover letters, IMAP reply classification, and WhatsApp candidate updates.</p>
                        </div>
                        <div class="wa-header-actions" style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
                            <button type="button" class="wa-btn-secondary" data-cond-action="refresh">
                                ↻ Refresh
                            </button>
                            <button type="button" class="wa-btn-secondary" data-cond-action="toggle-engine">
                                ${isRunning ? "⏸ Pause Daemon" : "▶ Start Daemon"}
                            </button>
                            <button type="button" class="wa-btn-primary" data-cond-action="run-global-cycle" ${emergencyStop ? "disabled" : ""}>
                                ⚡ Run Global Cycle Now
                            </button>
                            <button type="button" class="wa-btn-secondary" data-cond-action="check-inbox" ${emergencyStop ? "disabled" : ""}>
                                📬 Check Email Inbox
                            </button>
                            <button
                                type="button"
                                class="${emergencyStop ? "wa-btn-primary" : "wa-btn-danger"}"
                                style="${emergencyStop ? "background:#10b981;border-color:#059669;" : "background:#ef4444;color:#fff;border:none;padding:8px 14px;border-radius:8px;font-weight:700;cursor:pointer;"}"
                                data-cond-action="emergency-stop"
                                data-enabled="${emergencyStop ? "false" : "true"}"
                            >
                                ${emergencyStop ? "✅ Resume Operations (Clear Stop)" : "🛑 EMERGENCY STOP"}
                            </button>
                        </div>
                    </header>

                    <div id="conductor-toast-banner" class="conductor-toast" hidden></div>

                    <!-- KPI Metrics -->
                    <div class="wa-metrics-grid" style="margin-bottom:18px;">
                        <div class="wa-metric-card">
                            <div class="wa-metric-icon" style="background:rgba(59,130,246,0.15); color:#3b82f6;">👥</div>
                            <div class="wa-metric-info">
                                <span class="wa-metric-title">Managed Clients</span>
                                <span class="wa-metric-number">${metrics.total_managed_clients || 0}</span>
                                <span class="wa-metric-sub">Linked by client_id</span>
                            </div>
                        </div>
                        <div class="wa-metric-card">
                            <div class="wa-metric-icon" style="background:rgba(99,102,241,0.15); color:#6366f1;">🔍</div>
                            <div class="wa-metric-info">
                                <span class="wa-metric-title">Staged for Approval</span>
                                <span class="wa-metric-number">${metrics.staged_for_approval || 0}</span>
                                <span class="wa-metric-sub">Cover letters ready</span>
                            </div>
                        </div>
                        <div class="wa-metric-card">
                            <div class="wa-metric-icon" style="background:rgba(16,185,129,0.15); color:#10b981;">✉️</div>
                            <div class="wa-metric-info">
                                <span class="wa-metric-title">Authorized &amp; Applied</span>
                                <span class="wa-metric-number">${metrics.applied_total || 0}</span>
                                <span class="wa-metric-sub">Submitted applications</span>
                            </div>
                        </div>
                        <div class="wa-metric-card">
                            <div class="wa-metric-icon" style="background:rgba(245,158,11,0.15); color:#f59e0b;">🎉</div>
                            <div class="wa-metric-info">
                                <span class="wa-metric-title">Interviews Detected</span>
                                <span class="wa-metric-number">${metrics.interviews_total || 0}</span>
                                <span class="wa-metric-sub">Via AI Email Monitor</span>
                            </div>
                        </div>
                    </div>

                    <!-- Navigation Tabs -->
                    <div class="wa-tabs" role="tablist" style="margin-bottom:16px;">
                        <button type="button" class="wa-tab ${activeTab === "clients" ? "is-active" : ""}" data-cond-tab="clients">
                            👥 Client Automation Controls (${clients.length})
                        </button>
                        <button type="button" class="wa-tab ${activeTab === "matches" ? "is-active" : ""}" data-cond-tab="matches">
                            📄 Pipeline &amp; Approval Queue (${state.matches.length})
                        </button>
                        <button type="button" class="wa-tab ${activeTab === "inbox" ? "is-active" : ""}" data-cond-tab="inbox">
                            📬 Email Reply Monitor (${inboxLogs.length})
                        </button>
                        <button type="button" class="wa-tab ${activeTab === "logs" ? "is-active" : ""}" data-cond-tab="logs">
                            ⚙️ Task Queue, Logs &amp; Settings
                        </button>
                    </div>

                    <!-- Tab Content -->
                    <div class="conductor-tab-body">
                        ${activeTab === "clients" ? renderClientsTab(clients, emergencyStop) : ""}
                        ${activeTab === "matches" ? renderMatchesTab(clients) : ""}
                        ${activeTab === "inbox" ? renderInboxTab(inboxLogs, clients) : ""}
                        ${activeTab === "logs" ? renderLogsAndSettingsTab(tasks, logs, settings) : ""}
                    </div>
                </div>
            `;
        }

        function renderClientsTab(clients, emergencyStop) {
            if (!clients.length) {
                return `
                    <div class="wa-card">
                        <p class="wa-td-empty">No clients found. Onboard a candidate from the Applications section to start autonomous workflows.</p>
                    </div>
                `;
            }

            const rows = clients.map((c) => {
                const cid = escapeHtml(c.id);
                const auto = c.automation || {};
                const stats = c.matches_stats || {};
                const isPaused = Boolean(auto.is_paused);
                const stagedCount = (stats.staged_for_approval || 0) + (stats.discovered || 0);
                const appliedCount = stats.applied || 0;
                const interviewCount = stats.interview || 0;

                return `
                    <tr>
                        <td>
                            <div style="font-weight:700; color:#f8fafc;">${escapeHtml(c.name || c.id)}</div>
                            <div style="font-size:11.5px; color:#94a3b8; font-family:monospace;">ID: ${cid}</div>
                            <div style="font-size:12px; color:#cbd5e1;">${escapeHtml(c.title || "Fachinformatiker")} • ${escapeHtml(c.city || "Köln")}</div>
                        </td>
                        <td>
                            <span class="wa-verify-pill" style="background:${isPaused ? "rgba(245,158,11,0.2);color:#fbbf24;" : "rgba(16,185,129,0.2);color:#34d399;"}">
                                ${isPaused ? "⏸ Paused" : "● Active"}
                            </span>
                            <div style="font-size:11px; color:#64748b; margin-top:4px;">Last Search: ${formatIsoTime(auto.last_search_at)}</div>
                        </td>
                        <td>
                            <div style="display:flex; gap:8px; font-size:12px;">
                                <span title="Staged for approval" style="color:#818cf8; font-weight:600;">Staged: ${stagedCount}</span>
                                <span title="Applied" style="color:#34d399; font-weight:600;">Applied: ${appliedCount}</span>
                                <span title="Interviews" style="color:#fbbf24; font-weight:600;">Interviews: ${interviewCount}</span>
                            </div>
                        </td>
                        <td>
                            <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:12px;">
                                <label style="display:flex; align-items:center; gap:5px; cursor:pointer;">
                                    <input type="checkbox" data-client-toggle="auto_search" data-client-id="${cid}" ${auto.auto_search ? "checked" : ""}>
                                    <span>Auto-Search</span>
                                </label>
                                <label style="display:flex; align-items:center; gap:5px; cursor:pointer;">
                                    <input type="checkbox" data-client-toggle="auto_cover_letter" data-client-id="${cid}" ${auto.auto_cover_letter ? "checked" : ""}>
                                    <span>Cover Letter</span>
                                </label>
                                <label style="display:flex; align-items:center; gap:5px; cursor:pointer;" title="Authorize automatic submission without manual staging">
                                    <input type="checkbox" data-client-toggle="auto_apply" data-client-id="${cid}" ${auto.auto_apply ? "checked" : ""}>
                                    <span>Auto-Apply Auth</span>
                                </label>
                                <label style="display:flex; align-items:center; gap:5px; cursor:pointer;">
                                    <input type="checkbox" data-client-toggle="auto_notify_whatsapp" data-client-id="${cid}" ${auto.auto_notify_whatsapp ? "checked" : ""}>
                                    <span>WhatsApp Alerts</span>
                                </label>
                            </div>
                        </td>
                        <td>
                            <input
                                type="number"
                                class="wa-input"
                                style="width:70px; padding:4px 8px; font-size:12px;"
                                min="1"
                                max="50"
                                value="${Number(auto.max_daily_applications || 5)}"
                                data-client-max-daily="${cid}"
                            >
                        </td>
                        <td>
                            <div style="display:flex; gap:6px; flex-wrap:wrap;">
                                <button
                                    type="button"
                                    class="wa-btn-sm-primary"
                                    data-cond-action="run-client"
                                    data-client-id="${cid}"
                                    ${emergencyStop ? "disabled" : ""}
                                    title="Run daily search &amp; cover letter generation for this client now"
                                >
                                    ▶ Run Cycle
                                </button>
                                <button
                                    type="button"
                                    class="wa-btn-sm-secondary"
                                    data-cond-action="pause-client"
                                    data-client-id="${cid}"
                                    data-paused="${isPaused ? "false" : "true"}"
                                >
                                    ${isPaused ? "Resume" : "Pause"}
                                </button>
                                <button
                                    type="button"
                                    class="wa-btn-sm-secondary"
                                    data-cond-action="send-digest"
                                    data-client-id="${cid}"
                                    title="Send WhatsApp progress summary"
                                >
                                    📊 WA Digest
                                </button>
                                <button
                                    type="button"
                                    class="wa-btn-sm-secondary"
                                    data-cond-action="request-docs"
                                    data-client-id="${cid}"
                                    title="Check and request missing documents via WhatsApp"
                                >
                                    📄 Req Docs
                                </button>
                            </div>
                        </td>
                    </tr>
                `;
            }).join("");

            return `
                <div class="wa-card">
                    <div class="wa-card-header">
                        <div>
                            <h3>Per-Client Autonomous Workflow Controls</h3>
                            <p style="font-size:12.5px; color:#94a3b8; margin:2px 0 0;">Each client operates in an isolated pipeline keyed by <code>client_id</code>. Applications require approval unless <strong>Auto-Apply Auth</strong> is enabled.</p>
                        </div>
                    </div>
                    <div class="wa-table-responsive">
                        <table class="wa-table">
                            <thead>
                                <tr>
                                    <th>Client &amp; Profession</th>
                                    <th>State</th>
                                    <th>Pipeline Metrics</th>
                                    <th>Automation Switches</th>
                                    <th>Daily Limit</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${rows}
                            </tbody>
                        </table>
                    </div>
                </div>
            `;
        }

        function renderMatchesTab(clients) {
            const clientOptions = clients.map((c) => {
                const selected = state.matchFilterClient === c.id ? "selected" : "";
                return `<option value="${escapeHtml(c.id)}" ${selected}>${escapeHtml(c.name || c.id)} (${escapeHtml(c.id)})</option>`;
            }).join("");

            const matchRows = state.matches.length
                ? state.matches.map((m) => {
                      const mid = escapeHtml(m.id);
                      const status = String(m.status || "discovered");
                      const hasPdf = Boolean(m.cover_letter_path);
                      let statusBadge = `<span class="wa-verify-pill">${escapeHtml(status)}</span>`;
                      if (status === "staged_for_approval") {
                          statusBadge = `<span class="wa-verify-pill" style="background:rgba(99,102,241,0.2);color:#818cf8;">⏳ Staged for Approval</span>`;
                      } else if (status === "applied") {
                          statusBadge = `<span class="wa-verify-pill" style="background:rgba(16,185,129,0.2);color:#34d399;">✓ Applied</span>`;
                      } else if (status === "interview") {
                          statusBadge = `<span class="wa-verify-pill" style="background:rgba(245,158,11,0.25);color:#fbbf24;">🎉 Interview</span>`;
                      } else if (status === "rejected") {
                          statusBadge = `<span class="wa-verify-pill" style="background:rgba(239,68,68,0.2);color:#f87171;">✕ Rejected</span>`;
                      }

                      return `
                          <tr>
                              <td><code style="font-size:12px;">${escapeHtml(m.client_id)}</code></td>
                              <td>
                                  <div style="font-weight:600; color:#f8fafc;">${escapeHtml(m.job_title)}</div>
                                  <div style="font-size:11.5px; color:#94a3b8;">Source: ${escapeHtml(m.source || "dataset")}</div>
                              </td>
                              <td>
                                  <div>${escapeHtml(m.company)}</div>
                                  <div style="font-size:11.5px; color:#94a3b8;">${escapeHtml(m.location || "")} ${m.email ? "• " + escapeHtml(m.email) : ""}</div>
                              </td>
                              <td><strong>${Math.round(Number(m.score || 0.85) * 100)}%</strong></td>
                              <td>${hasPdf ? `<span style="color:#34d399; font-size:12px;">✓ PDF Ready</span>` : `<span style="color:#94a3b8; font-size:12px;">—</span>`}</td>
                              <td>${statusBadge}</td>
                              <td>
                                  ${
                                      status === "staged_for_approval" || status === "discovered"
                                          ? `<button type="button" class="wa-btn-sm-primary" data-cond-action="approve-match" data-match-id="${mid}">✓ Authorize &amp; Apply</button>`
                                          : `<span style="font-size:11.5px; color:#64748b;">Updated ${formatIsoTime(m.updated_at)}</span>`
                                  }
                              </td>
                          </tr>
                      `;
                  }).join("")
                : `<tr><td colspan="7" class="wa-td-empty">No matching opportunities in pipeline for current filter. Click "Run Cycle" to discover &amp; stage matches.</td></tr>`;

            return `
                <div class="wa-card">
                    <div class="wa-card-header" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                        <div>
                            <h3>Discovered Opportunities &amp; Authorization Queue</h3>
                            <p style="font-size:12.5px; color:#94a3b8; margin:2px 0 0;">Review generated cover letters and authorize staged applications per client.</p>
                        </div>
                        <div style="display:flex; gap:8px; align-items:center;">
                            <select id="cond-filter-client" class="wa-select-sm">
                                <option value="">All Clients</option>
                                ${clientOptions}
                            </select>
                            <select id="cond-filter-status" class="wa-select-sm">
                                <option value="" ${state.matchFilterStatus === "" ? "selected" : ""}>All Statuses</option>
                                <option value="staged_for_approval" ${state.matchFilterStatus === "staged_for_approval" ? "selected" : ""}>Staged for Approval</option>
                                <option value="applied" ${state.matchFilterStatus === "applied" ? "selected" : ""}>Applied</option>
                                <option value="interview" ${state.matchFilterStatus === "interview" ? "selected" : ""}>Interview</option>
                                <option value="rejected" ${state.matchFilterStatus === "rejected" ? "selected" : ""}>Rejected</option>
                            </select>
                        </div>
                    </div>
                    <div class="wa-table-responsive">
                        <table class="wa-table">
                            <thead>
                                <tr>
                                    <th>Client ID</th>
                                    <th>Position / Title</th>
                                    <th>Company &amp; Contact</th>
                                    <th>Match</th>
                                    <th>Cover Letter</th>
                                    <th>Status</th>
                                    <th>Authorization</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${matchRows}
                            </tbody>
                        </table>
                    </div>
                </div>
            `;
        }

        function renderInboxTab(inboxLogs, clients) {
            const clientOptions = clients.map((c) => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name || c.id)} (${escapeHtml(c.id)})</option>`).join("");

            const rows = inboxLogs.length
                ? inboxLogs.map((item) => {
                      const intent = String(item.intent || "other");
                      let intentColor = "#94a3b8";
                      if (intent === "interview_invitation") intentColor = "#34d399";
                      else if (intent === "rejection") intentColor = "#f87171";
                      else if (intent === "info_request") intentColor = "#fbbf24";
                      else if (intent === "confirmation_of_receipt") intentColor = "#60a5fa";

                      return `
                          <tr>
                              <td style="font-size:12px;">${formatIsoTime(item.received_at)}</td>
                              <td>
                                  <div style="font-weight:600;">${escapeHtml(item.matched_company || item.sender)}</div>
                                  <div style="font-size:11.5px; color:#94a3b8;">${escapeHtml(item.sender)}</div>
                              </td>
                              <td>
                                  <span class="wa-verify-pill" style="color:${intentColor}; border:1px solid ${intentColor};">
                                      ${escapeHtml(intent)} (${Math.round(Number(item.confidence || 0.85) * 100)}%)
                                  </span>
                              </td>
                              <td><code>${escapeHtml(item.matched_client_id || "—")}</code></td>
                              <td>
                                  <div style="font-weight:600; font-size:12.5px;">${escapeHtml(item.subject)}</div>
                                  <div style="font-size:12px; color:#cbd5e1; margin-top:2px;">${escapeHtml(item.summary)}</div>
                                  ${
                                      item.suggested_reply
                                          ? `<div style="margin-top:6px; padding:6px 8px; background:rgba(15,23,42,0.6); border-left:3px solid #6366f1; font-size:11.5px; color:#e2e8f0;"><strong>Draft Reply:</strong> ${escapeHtml(item.suggested_reply)}</div>`
                                          : ""
                                  }
                              </td>
                              <td style="font-size:12px; color:#cbd5e1;">${escapeHtml(item.action_taken)}</td>
                          </tr>
                      `;
                  }).join("")
                : `<tr><td colspan="6" class="wa-td-empty">No recruiter replies processed yet. Use "Check Email Inbox" or test with the simulator below.</td></tr>`;

            return `
                <div class="wa-setup-grid" style="margin-bottom:18px;">
                    <div class="wa-card wa-grid-full">
                        <div class="wa-card-header">
                            <h3>Recruiter Email Reply Simulator (Test AI Classification, Pipeline Sync &amp; WhatsApp Alerts)</h3>
                        </div>
                        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:10px; margin-bottom:10px;">
                            <div>
                                <label class="wa-label">Target Client (Optional):</label>
                                <select id="cond-sim-client" class="wa-select">
                                    <option value="">Auto-Correlate by Company/Domain</option>
                                    ${clientOptions}
                                </select>
                            </div>
                            <div>
                                <label class="wa-label">Recruiter Sender Email:</label>
                                <input type="text" id="cond-sim-sender" class="wa-input" value="karriere@alpha-tech.de">
                            </div>
                            <div>
                                <label class="wa-label">Subject Line:</label>
                                <input type="text" id="cond-sim-subject" class="wa-input" value="Einladung zum Vorstellungsgespräch - Alpha Solutions GmbH">
                            </div>
                        </div>
                        <div class="wa-form-group">
                            <label class="wa-label">Email Body:</label>
                            <textarea id="cond-sim-body" class="wa-textarea" rows="2">Sehr geehrte(r) Bewerber(in), vielen Dank für Ihre Bewerbung! Wir möchten Sie herzlich zu einem Vorstellungsgespräch am kommenden Dienstag um 10:00 Uhr einladen.</textarea>
                        </div>
                        <div style="display:flex; gap:8px; flex-wrap:wrap;">
                            <button type="button" class="wa-btn-primary" data-cond-action="simulate-email">
                                🧪 Classify &amp; Process Email
                            </button>
                            <button type="button" class="wa-btn-secondary" data-cond-preset="interview">
                                Preset: Interview Invitation
                            </button>
                            <button type="button" class="wa-btn-secondary" data-cond-preset="info_request">
                                Preset: Missing Document Request
                            </button>
                            <button type="button" class="wa-btn-secondary" data-cond-preset="confirmation">
                                Preset: Receipt Confirmation
                            </button>
                            <button type="button" class="wa-btn-secondary" data-cond-preset="rejection">
                                Preset: Rejection
                            </button>
                        </div>
                    </div>
                </div>

                <div class="wa-card">
                    <div class="wa-card-header">
                        <h3>Processed Recruiter Replies &amp; AI Follow-Up Drafts</h3>
                    </div>
                    <div class="wa-table-responsive">
                        <table class="wa-table">
                            <thead>
                                <tr>
                                    <th>Received</th>
                                    <th>Company / Sender</th>
                                    <th>AI Intent</th>
                                    <th>Client</th>
                                    <th>Subject, Summary &amp; Follow-up Draft</th>
                                    <th>Action Taken</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${rows}
                            </tbody>
                        </table>
                    </div>
                </div>
            `;
        }

        function renderLogsAndSettingsTab(tasks, logs, settings) {
            const taskRows = tasks.length
                ? tasks.map((t) => `
                    <tr>
                        <td><code style="font-size:11.5px;">${escapeHtml(t.id)}</code></td>
                        <td><strong>${escapeHtml(t.task_type)}</strong></td>
                        <td><code>${escapeHtml(t.client_id)}</code></td>
                        <td>
                            <span class="wa-verify-pill" style="color:${t.status === "completed" ? "#34d399" : t.status === "failed" ? "#f87171" : "#60a5fa"};">
                                ${escapeHtml(t.status)} ${t.retry_count ? `(Retries: ${t.retry_count})` : ""}
                            </span>
                        </td>
                        <td style="font-size:12px;">${escapeHtml(t.result_summary || t.error_message || "—")}</td>
                        <td style="font-size:11.5px;">${formatIsoTime(t.created_at)}</td>
                        <td>
                            ${
                                t.status === "failed"
                                    ? `<button type="button" class="wa-btn-sm-secondary" data-cond-action="retry-task" data-task-id="${escapeHtml(t.id)}">↻ Retry</button>`
                                    : ""
                            }
                        </td>
                    </tr>
                `).join("")
                : `<tr><td colspan="7" class="wa-td-empty">No tasks executed yet.</td></tr>`;

            const logRows = logs.length
                ? logs.map((l) => `
                    <tr>
                        <td style="font-size:11.5px;">${formatIsoTime(l.created_at)}</td>
                        <td><span class="wa-verify-pill">${escapeHtml(l.level)}</span></td>
                        <td><code>${escapeHtml(l.module)}</code></td>
                        <td><code>${escapeHtml(l.client_id || "system")}</code></td>
                        <td style="font-size:12.5px;">${escapeHtml(l.message)}</td>
                    </tr>
                `).join("")
                : `<tr><td colspan="5" class="wa-td-empty">No activity logs recorded yet.</td></tr>`;

            return `
                <div class="wa-config-grid" style="margin-bottom:18px;">
                    <div class="wa-card wa-grid-full">
                        <div class="wa-card-header">
                            <h3>Global Conductor Schedule &amp; Safety Settings</h3>
                        </div>
                        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:14px;">
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="cond-set-auto-search" ${String(settings.auto_daily_search || "true") === "true" ? "checked" : ""}>
                                <span>Enable Scheduled Daily Searches</span>
                            </label>
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="cond-set-auto-email" ${String(settings.auto_email_monitoring || "true") === "true" ? "checked" : ""}>
                                <span>Enable Scheduled IMAP Email Monitoring</span>
                            </label>
                            <label style="display:flex; align-items:center; gap:8px;">
                                <input type="checkbox" id="cond-set-auto-wa" ${String(settings.auto_whatsapp_updates || "true") === "true" ? "checked" : ""}>
                                <span>Enable Proactive WhatsApp Updates</span>
                            </label>
                            <div>
                                <label class="wa-label">Daily Search Interval (Hours):</label>
                                <input type="number" id="cond-set-search-hours" class="wa-input" min="1" max="168" value="${escapeHtml(settings.daily_search_interval_hours || "24")}">
                            </div>
                            <div>
                                <label class="wa-label">Email Check Interval (Minutes):</label>
                                <input type="number" id="cond-set-email-mins" class="wa-input" min="1" max="1440" value="${escapeHtml(settings.email_monitor_interval_minutes || "15")}">
                            </div>
                            <div>
                                <label class="wa-label">Max Consecutive Errors (Circuit Breaker):</label>
                                <input type="number" id="cond-set-max-errors" class="wa-input" min="1" max="50" value="${escapeHtml(settings.max_consecutive_errors || "5")}">
                            </div>
                        </div>
                        <div style="margin-top:12px; display:flex; justify-content:flex-end;">
                            <button type="button" class="wa-btn-primary" data-cond-action="save-settings">Save Global Settings</button>
                        </div>
                    </div>
                </div>

                <div class="wa-card" style="margin-bottom:18px;">
                    <div class="wa-card-header">
                        <h3>Orchestration Task Queue &amp; Execution History</h3>
                    </div>
                    <div class="wa-table-responsive">
                        <table class="wa-table">
                            <thead>
                                <tr>
                                    <th>Task ID</th>
                                    <th>Type</th>
                                    <th>Client</th>
                                    <th>Status</th>
                                    <th>Summary / Error</th>
                                    <th>Created</th>
                                    <th>Action</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${taskRows}
                            </tbody>
                        </table>
                    </div>
                </div>

                <div class="wa-card">
                    <div class="wa-card-header">
                        <h3>Real-Time Activity &amp; Audit Logs</h3>
                    </div>
                    <div class="wa-table-responsive">
                        <table class="wa-table">
                            <thead>
                                <tr>
                                    <th>Timestamp</th>
                                    <th>Level</th>
                                    <th>Module</th>
                                    <th>Client ID</th>
                                    <th>Event Message</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${logRows}
                            </tbody>
                        </table>
                    </div>
                </div>
            `;
        }

        function render() {
            if (!root) return;
            root.innerHTML = buildShellHtml();
            renderToastOnly();
        }

        async function handleActionClick(e) {
            const tabBtn = e.target.closest("[data-cond-tab]");
            if (tabBtn) {
                activeTab = tabBtn.getAttribute("data-cond-tab") || "clients";
                render();
                return;
            }

            const presetBtn = e.target.closest("[data-cond-preset]");
            if (presetBtn) {
                const preset = presetBtn.getAttribute("data-cond-preset");
                const subjEl = document.getElementById("cond-sim-subject");
                const bodyEl = document.getElementById("cond-sim-body");
                if (preset === "interview") {
                    if (subjEl) subjEl.value = "Einladung zum Vorstellungsgespräch - Alpha Solutions GmbH";
                    if (bodyEl) bodyEl.value = "Sehr geehrte(r) Bewerber(in), wir laden Sie herzlich zu einem Vorstellungsgespräch für die Ausbildung am Dienstag um 10:00 Uhr ein.";
                } else if (preset === "info_request") {
                    if (subjEl) subjEl.value = "Rückfrage zu Ihrer Bewerbung - Fehlende Unterlagen";
                    if (bodyEl) bodyEl.value = "Sehr geehrte Damen und Herren, bitte senden Sie uns noch Ihr aktuelles B2-Sprachzertifikat sowie Ihr Abschlusszeugnis zu.";
                } else if (preset === "confirmation") {
                    if (subjEl) subjEl.value = "Eingangsbestätigung Ihrer Bewerbung";
                    if (bodyEl) bodyEl.value = "Vielen Dank für Ihre Bewerbung! Wir haben Ihre Unterlagen erhalten und prüfen diese derzeit.";
                } else if (preset === "rejection") {
                    if (subjEl) subjEl.value = "Ihre Bewerbung bei Bavaria Systems AG";
                    if (bodyEl) bodyEl.value = "Leider müssen wir Ihnen mitteilen, dass wir uns für das kommende Ausbildungsjahr anderweitig entschieden haben.";
                }
                return;
            }

            const actionBtn = e.target.closest("[data-cond-action]");
            if (!actionBtn) return;

            const action = actionBtn.getAttribute("data-cond-action");
            const clientId = actionBtn.getAttribute("data-client-id");

            try {
                if (action === "refresh") {
                    await fetchAllData();
                    showToast("Conductor dashboard refreshed.", "info");
                } else if (action === "toggle-engine") {
                    const res = await fetch("/api/conductor/engine/toggle", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
                    const data = await res.json();
                    showToast(data.message || "Updated engine state.", "info");
                    await fetchAllData();
                } else if (action === "emergency-stop") {
                    const enabled = actionBtn.getAttribute("data-enabled") === "true";
                    const res = await fetch("/api/conductor/emergency-stop", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ enabled }),
                    });
                    const data = await res.json();
                    showToast(data.message || "Emergency stop updated.", enabled ? "warn" : "success");
                    await fetchAllData();
                } else if (action === "run-global-cycle") {
                    showToast("Running global autonomous cycle across all active clients...", "info");
                    const res = await fetch("/api/conductor/run-cycle", { method: "POST" });
                    const data = await res.json();
                    if (data.success) {
                        showToast(`Global cycle complete: ${data.total_new_matches} matches, ${data.total_cover_letters} cover letters.`, "success");
                    } else {
                        showToast(data.error || "Global cycle failed.", "warn");
                    }
                    await fetchAllData();
                } else if (action === "check-inbox") {
                    const res = await fetch("/api/conductor/email-monitor/check-now", { method: "POST" });
                    const data = await res.json();
                    showToast(`Inbox check finished (${data.status || "ok"}): ${data.processed_count || 0} message(s) processed.`, "info");
                    await fetchAllData();
                } else if (action === "run-client" && clientId) {
                    showToast(`Running search & staging cycle for ${clientId}...`, "info");
                    const res = await fetch(`/api/conductor/clients/${encodeURIComponent(clientId)}/run`, { method: "POST" });
                    const data = await res.json();
                    if (data.success) {
                        showToast(`Cycle finished for ${clientId}: ${data.new_matches_count} new matches, ${data.cover_letters_created} cover letters.`, "success");
                    } else {
                        showToast(data.error || "Cycle skipped or failed.", "warn");
                    }
                    await fetchAllData();
                } else if (action === "pause-client" && clientId) {
                    const paused = actionBtn.getAttribute("data-paused") === "true";
                    const res = await fetch(`/api/conductor/clients/${encodeURIComponent(clientId)}/pause`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ paused }),
                    });
                    const data = await res.json();
                    showToast(data.message || "Updated client pause state.", "info");
                    await fetchAllData();
                } else if (action === "send-digest" && clientId) {
                    const res = await fetch(`/api/conductor/whatsapp/digest/${encodeURIComponent(clientId)}`, { method: "POST" });
                    const data = await res.json();
                    showToast(data.message || "WhatsApp digest triggered.", data.success ? "success" : "warn");
                    await fetchAllData();
                } else if (action === "request-docs" && clientId) {
                    const res = await fetch(`/api/conductor/whatsapp/request-docs/${encodeURIComponent(clientId)}`, { method: "POST" });
                    const data = await res.json();
                    showToast(data.message || "Document check completed.", data.success ? "success" : "info");
                    await fetchAllData();
                } else if (action === "approve-match") {
                    const matchId = actionBtn.getAttribute("data-match-id");
                    const res = await fetch(`/api/conductor/matches/${encodeURIComponent(matchId)}/approve`, { method: "POST" });
                    const data = await res.json();
                    showToast(data.message || "Match approved.", data.success ? "success" : "warn");
                    await fetchAllData();
                } else if (action === "simulate-email") {
                    const sender = (document.getElementById("cond-sim-sender") || {}).value || "";
                    const subject = (document.getElementById("cond-sim-subject") || {}).value || "";
                    const body = (document.getElementById("cond-sim-body") || {}).value || "";
                    const simClient = (document.getElementById("cond-sim-client") || {}).value || "";
                    const res = await fetch("/api/conductor/email-monitor/simulate", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ sender, subject, body, client_id: simClient }),
                    });
                    const data = await res.json();
                    if (data.success && data.message) {
                        showToast(`Classified email as '${data.message.intent}' (${data.message.action_taken}).`, "success");
                    }
                    await fetchAllData();
                } else if (action === "save-settings") {
                    const payload = {
                        auto_daily_search: document.getElementById("cond-set-auto-search")?.checked ? "true" : "false",
                        auto_email_monitoring: document.getElementById("cond-set-auto-email")?.checked ? "true" : "false",
                        auto_whatsapp_updates: document.getElementById("cond-set-auto-wa")?.checked ? "true" : "false",
                        daily_search_interval_hours: document.getElementById("cond-set-search-hours")?.value || "24",
                        email_monitor_interval_minutes: document.getElementById("cond-set-email-mins")?.value || "15",
                        max_consecutive_errors: document.getElementById("cond-set-max-errors")?.value || "5",
                    };
                    const res = await fetch("/api/conductor/settings", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload),
                    });
                    const data = await res.json();
                    showToast(data.message || "Saved settings.", "success");
                    await fetchAllData();
                } else if (action === "retry-task") {
                    const taskId = actionBtn.getAttribute("data-task-id");
                    const res = await fetch(`/api/conductor/tasks/${encodeURIComponent(taskId)}/retry`, { method: "POST" });
                    const data = await res.json();
                    showToast(data.success ? `Task ${taskId} retried successfully.` : (data.error || "Retry failed."), data.success ? "success" : "warn");
                    await fetchAllData();
                }
            } catch (err) {
                showToast("Operation failed: " + err.message, "warn");
            }
        }

        async function handleChange(e) {
            const toggleInput = e.target.closest("[data-client-toggle]");
            if (toggleInput) {
                const cid = toggleInput.getAttribute("data-client-id");
                const field = toggleInput.getAttribute("data-client-toggle");
                const val = toggleInput.checked ? 1 : 0;
                await fetch(`/api/conductor/clients/${encodeURIComponent(cid)}`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ [field]: val }),
                });
                showToast(`Updated ${field} for ${cid}.`, "info");
                await fetchAllData();
                return;
            }

            const maxDailyInput = e.target.closest("[data-client-max-daily]");
            if (maxDailyInput) {
                const cid = maxDailyInput.getAttribute("data-client-max-daily");
                const maxVal = parseInt(maxDailyInput.value, 10) || 5;
                await fetch(`/api/conductor/clients/${encodeURIComponent(cid)}`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ max_daily_applications: maxVal }),
                });
                showToast(`Updated daily application limit for ${cid} to ${maxVal}.`, "info");
                await fetchAllData();
                return;
            }

            if (e.target.id === "cond-filter-client") {
                state.matchFilterClient = e.target.value;
                await fetchAllData();
            } else if (e.target.id === "cond-filter-status") {
                state.matchFilterStatus = e.target.value;
                await fetchAllData();
            }
        }

        if (root) {
            root.addEventListener("click", handleActionClick);
            root.addEventListener("change", handleChange);
        }

        return {
            show() {
                fetchAllData();
                if (!pollTimer) {
                    pollTimer = setInterval(fetchAllData, 15000);
                }
            },
            hide() {
                if (pollTimer) {
                    clearInterval(pollTimer);
                    pollTimer = null;
                }
            },
        };
    };
})();


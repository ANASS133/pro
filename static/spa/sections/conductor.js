/**
 * JobScout Conductor — Central Autonomous Orchestration Dashboard
 * Redesigned Modern SaaS Control Center (Dark Theme)
 * Manages client automation toggles, daily search cycles, staged application approvals,
 * recruitment email inbox monitoring, WhatsApp candidate updates, and emergency stop.
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
            return d.toLocaleString("en-US", {
                month: "short",
                day: "2-digit",
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
            clientSearchQuery: "",
            clientFilterStatus: "all",
            toastMessage: "",
            toastType: "info",
            loading: false,
            expandedClients: new Set(),
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
            toastEl.className = `cond-toast is-${state.toastType}`;
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
                ? "Emergency Stop Active"
                : isRunning
                    ? "Autopilot Active"
                    : "Worker Paused";

            return `
                <div class="cond-dashboard-container">
                    <!-- Compact Top Header -->
                    <header class="cond-header">
                        <div class="cond-header-main">
                            <div class="cond-title-area">
                                <div class="cond-title-row">
                                    <span class="cond-worker-badge ${badgeClass}">
                                        <span class="cond-pulse-dot"></span>
                                        <span>${badgeLabel}</span>
                                    </span>
                                    <h1 class="cond-title">Conductor Autopilot</h1>
                                </div>
                                <p class="cond-subtitle">Central autonomous engine orchestrating client discovery, cover letters, IMAP reply classification, and WhatsApp updates.</p>
                            </div>
                            <div class="cond-header-actions">
                                <div class="cond-action-group">
                                    <button type="button" class="cond-btn cond-btn-secondary" data-cond-action="refresh" title="Refresh all live status and metrics">
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>
                                        <span>Refresh</span>
                                    </button>
                                    <button type="button" class="cond-btn cond-btn-secondary" data-cond-action="sync-applications" title="Synchronize paid applications from Supabase into Conductor">
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
                                        <span>Sync Applications</span>
                                    </button>
                                    <button type="button" class="cond-btn cond-btn-secondary" data-cond-action="toggle-engine" title="Start or pause background scheduler daemon">
                                        ${isRunning
                    ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg><span>Pause Daemon</span>`
                    : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><span>Start Daemon</span>`
                }
                                    </button>
                                    <button type="button" class="cond-btn cond-btn-secondary" data-cond-action="check-inbox" ${emergencyStop ? "disabled" : ""} title="Check IMAP email inbox for recruiter replies">
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>
                                        <span>Check Inbox</span>
                                    </button>
                                    <button type="button" class="cond-btn cond-btn-primary" data-cond-action="run-global-cycle" ${emergencyStop ? "disabled" : ""} title="Run autonomous daily discovery & cover letter generation across all clients">
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
                                        <span>Run Global Cycle</span>
                                    </button>
                                </div>
                                <div class="cond-action-sep"></div>
                                <div class="cond-action-emergency">
                                    <button
                                        type="button"
                                        class="cond-btn ${emergencyStop ? "cond-btn-resume" : "cond-btn-danger"}"
                                        data-cond-action="emergency-stop"
                                        data-enabled="${emergencyStop ? "false" : "true"}"
                                        title="${emergencyStop ? "Resume all paused automated tasks and operations" : "Immediately halt all automated tasks, scraping, and applications"}"
                                    >
                                        ${emergencyStop
                    ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg><span>Resume Operations</span>`
                    : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"></line></svg><span>Emergency Stop</span>`
                }
                                    </button>
                                </div>
                            </div>
                        </div>
                    </header>

                    <div id="conductor-toast-banner" class="cond-toast" hidden></div>

                    <!-- Modern KPI Overview Cards -->
                    <div class="cond-kpi-grid">
                        <div class="cond-kpi-card">
                            <div class="cond-kpi-icon cond-kpi-icon-blue">
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>
                            </div>
                            <div class="cond-kpi-body">
                                <span class="cond-kpi-lbl">Managed Clients</span>
                                <div class="cond-kpi-val">${metrics.total_managed_clients || 0}</div>
                                <span class="cond-kpi-sub">Linked candidate dossiers</span>
                            </div>
                        </div>
                        <div class="cond-kpi-card">
                            <div class="cond-kpi-icon cond-kpi-icon-indigo">
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
                            </div>
                            <div class="cond-kpi-body">
                                <span class="cond-kpi-lbl">Staged for Approval</span>
                                <div class="cond-kpi-val">${metrics.staged_for_approval || 0}</div>
                                <span class="cond-kpi-sub">Cover letters ready</span>
                            </div>
                        </div>
                        <div class="cond-kpi-card">
                            <div class="cond-kpi-icon cond-kpi-icon-green">
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
                            </div>
                            <div class="cond-kpi-body">
                                <span class="cond-kpi-lbl">Authorized &amp; Applied</span>
                                <div class="cond-kpi-val">${metrics.applied_total || 0}</div>
                                <span class="cond-kpi-sub">Submitted applications</span>
                            </div>
                        </div>
                        <div class="cond-kpi-card">
                            <div class="cond-kpi-icon cond-kpi-icon-amber">
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="7"></circle><polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"></polyline></svg>
                            </div>
                            <div class="cond-kpi-body">
                                <span class="cond-kpi-lbl">Interviews Detected</span>
                                <div class="cond-kpi-val">${metrics.interviews_total || 0}</div>
                                <span class="cond-kpi-sub">Via AI Email Monitor</span>
                            </div>
                        </div>
                    </div>

                    <!-- Navigation Tabs -->
                    <div class="cond-tabs-nav" role="tablist">
                        <button type="button" class="cond-tab-btn ${activeTab === "clients" ? "is-active" : ""}" data-cond-tab="clients">
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle></svg>
                            <span>Client Automation (${clients.length})</span>
                        </button>
                        <button type="button" class="cond-tab-btn ${activeTab === "matches" ? "is-active" : ""}" data-cond-tab="matches">
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
                            <span>Pipeline &amp; Approvals (${state.matches.length})</span>
                        </button>
                        <button type="button" class="cond-tab-btn ${activeTab === "inbox" ? "is-active" : ""}" data-cond-tab="inbox">
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>
                            <span>Email Reply Monitor (${inboxLogs.length})</span>
                        </button>
                        <button type="button" class="cond-tab-btn ${activeTab === "logs" ? "is-active" : ""}" data-cond-tab="logs">
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
                            <span>Queue &amp; Settings</span>
                        </button>
                    </div>

                    <!-- Tab Content -->
                    <div class="cond-tab-content">
                        ${activeTab === "clients" ? renderClientsTab(clients, emergencyStop) : ""}
                        ${activeTab === "matches" ? renderMatchesTab(clients) : ""}
                        ${activeTab === "inbox" ? renderInboxTab(inboxLogs, clients) : ""}
                        ${activeTab === "logs" ? renderLogsAndSettingsTab(tasks, logs, settings) : ""}
                    </div>
                </div>
            `;
        }

        function formatAddress(addr, fallbackCity) {
            if (!addr || typeof addr !== "object") return fallbackCity || "Germany";
            const parts = [
                `${addr.street || ""} ${addr.house_number || ""}`.trim(),
                `${addr.postal_code || ""} ${addr.city || fallbackCity || ""}`.trim(),
                addr.country || "Deutschland"
            ].filter(Boolean);
            return parts.length ? parts.join(", ") : fallbackCity || "Germany";
        }

        function formatLanguages(langs) {
            if (!Array.isArray(langs) || !langs.length) return "Deutsch";
            return langs.map(l => `${l.language || l.code || ""}${l.level ? ` (${l.level})` : ""}`).filter(Boolean).join(", ");
        }

        function renderClientsTab(clients, emergencyStop) {
            if (!clients.length) {
                return `
                    <div class="cond-card cond-empty-card">
                        <div class="cond-empty-icon">👥</div>
                        <h3>No Managed Clients Found</h3>
                        <p>Click "Sync Applications" above or onboard a candidate from the Applications page to begin autonomous search and outreach.</p>
                        <button type="button" class="cond-btn cond-btn-primary" data-cond-action="sync-applications">
                            🔄 Sync Applications Now
                        </button>
                    </div>
                `;
            }

            // Client filtering & search
            const query = (state.clientSearchQuery || "").toLowerCase().trim();
            const filter = state.clientFilterStatus || "all";

            const filteredClients = clients.filter(c => {
                if (filter === "active" && c.automation && c.automation.is_paused) return false;
                if (filter === "paused" && (!c.automation || !c.automation.is_paused)) return false;
                if (filter === "paid" && (!c.payment || !c.payment.is_paid)) return false;
                if (filter === "ausbildung" && (c.opportunity_type || "Ausbildung").toLowerCase() !== "ausbildung") return false;
                if (filter === "job" && (c.opportunity_type || "").toLowerCase() !== "job") return false;
                if (query) {
                    const name = (c.name || "").toLowerCase();
                    const prof = (c.target_profession || c.title || "").toLowerCase();
                    const city = (c.city || "").toLowerCase();
                    const cid = (c.id || "").toLowerCase();
                    if (!name.includes(query) && !prof.includes(query) && !city.includes(query) && !cid.includes(query)) return false;
                }
                return true;
            });

            const rows = filteredClients.map((c) => {
                const cid = escapeHtml(c.id);
                const auto = c.automation || {};
                const stats = c.matches_stats || {};
                const quota = c.quota || {};
                const payment = c.payment || {};
                const readiness = c.readiness || {};
                const dataset = c.dataset_availability || {};
                const channel = c.channel_stats || {};
                const isPaused = Boolean(auto.is_paused);
                const isExpanded = state.expandedClients && state.expandedClients.has(c.id);
                const stagedCount = (stats.staged_for_approval || 0) + (stats.discovered || 0);
                const appliedCount = stats.applied || 0;
                const interviewCount = stats.interview || 0;
                const oppType = c.opportunity_type || "Ausbildung";
                const oppTypeClass = oppType.toLowerCase().replace(/[^a-z0-9]/g, "-");

                return `
                    <tr class="cond-client-row">
                        <!-- 1. Candidate Info -->
                        <td class="cond-td-candidate">
                            <div class="cond-cand-cell">
                                <div class="cond-avatar">
                                    ${escapeHtml((c.name || c.id).slice(0, 2).toUpperCase())}
                                </div>
                                <div class="cond-cand-meta">
                                    <div class="cond-cand-name-row">
                                        <span class="cond-cand-name">${escapeHtml(c.name || c.id)}</span>
                                        <span class="cond-type-pill cond-type-${oppTypeClass}">${escapeHtml(oppType)}</span>
                                    </div>
                                    <div class="cond-cand-role">
                                        <span>${escapeHtml(c.target_profession || c.title || "Fachinformatiker")}</span>
                                        <span class="cond-dot">•</span>
                                        <span class="cond-cand-city">${escapeHtml(c.city || "Köln")}</span>
                                    </div>
                                    <div class="cond-cand-id">
                                        <code>${cid}</code>
                                        ${c.supabase_application_id ? `<span class="cond-cand-app-id">• App: ${escapeHtml(c.supabase_application_id.slice(0, 8))}…</span>` : ""}
                                    </div>
                                </div>
                            </div>
                        </td>

                        <!-- 2. Status -->
                        <td class="cond-td-status">
                            <span class="cond-status-pill ${isPaused ? "is-paused" : "is-active"}">
                                <span class="cond-status-dot"></span>
                                <span>${isPaused ? "Paused" : "Active"}</span>
                            </span>
                            <div class="cond-time-sub">Last: ${formatIsoTime(auto.last_search_at)}</div>
                        </td>

                        <!-- 3. Package & Quota -->
                        <td class="cond-td-quota">
                            <div class="cond-quota-cell">
                                <div class="cond-quota-header">
                                    <span class="cond-quota-pkg">${escapeHtml(quota.package_name || "Standard (500)")}</span>
                                    <span class="cond-pay-pill ${payment.is_paid ? "is-paid" : "is-pending"}">
                                        ${payment.is_paid ? "✓ Paid" : "⏳ Pending"}
                                    </span>
                                </div>
                                <div class="cond-quota-counts">
                                    <span>${quota.applied || 0} / ${quota.total_limit || 500}</span>
                                    <span class="cond-quota-rem">(${quota.remaining || 0} left)</span>
                                </div>
                                <div class="cond-quota-bar-track">
                                    <div class="cond-quota-bar-fill" style="width:${quota.percent_used || 0}%;"></div>
                                </div>
                            </div>
                        </td>

                        <!-- 4. Pipeline Stats -->
                        <td class="cond-td-pipeline">
                            <div class="cond-pipeline-mini">
                                <div class="cond-pipe-badge cond-pipe-staged" title="Staged for approval">
                                    <span class="cond-pipe-lbl">Staged</span>
                                    <span class="cond-pipe-val">${stagedCount}</span>
                                </div>
                                <div class="cond-pipe-badge cond-pipe-applied" title="Submitted applications">
                                    <span class="cond-pipe-lbl">Applied</span>
                                    <span class="cond-pipe-val">${appliedCount}</span>
                                </div>
                                <div class="cond-pipe-badge cond-pipe-interviews" title="Interviews detected">
                                    <span class="cond-pipe-lbl">Interviews</span>
                                    <span class="cond-pipe-val">${interviewCount}</span>
                                </div>
                            </div>
                        </td>

                        <!-- 5. Workflow Switches -->
                        <td class="cond-td-switches">
                            <div class="cond-switches-grid">
                                <label class="cond-switch-wrap" title="Auto-Search: Automatically discover daily matching positions">
                                    <input type="checkbox" class="cond-switch-input" data-client-toggle="auto_search" data-client-id="${cid}" ${auto.auto_search ? "checked" : ""}>
                                    <span class="cond-switch-track"></span>
                                    <span class="cond-switch-lbl">Search</span>
                                </label>
                                <label class="cond-switch-wrap" title="Cover Letter: Automatically generate tailored cover letters">
                                    <input type="checkbox" class="cond-switch-input" data-client-toggle="auto_cover_letter" data-client-id="${cid}" ${auto.auto_cover_letter ? "checked" : ""}>
                                    <span class="cond-switch-track"></span>
                                    <span class="cond-switch-lbl">Cover Letter</span>
                                </label>
                                <label class="cond-switch-wrap" title="Auto-Apply Auth: Automatically submit without requiring manual staging">
                                    <input type="checkbox" class="cond-switch-input" data-client-toggle="auto_apply" data-client-id="${cid}" ${auto.auto_apply ? "checked" : ""}>
                                    <span class="cond-switch-track"></span>
                                    <span class="cond-switch-lbl">Auto-Apply</span>
                                </label>
                                <label class="cond-switch-wrap" title="WhatsApp Alerts: Send automated candidate updates via WhatsApp">
                                    <input type="checkbox" class="cond-switch-input" data-client-toggle="auto_notify_whatsapp" data-client-id="${cid}" ${auto.auto_notify_whatsapp ? "checked" : ""}>
                                    <span class="cond-switch-track"></span>
                                    <span class="cond-switch-lbl">WhatsApp</span>
                                </label>
                            </div>
                        </td>

                        <!-- 6. Daily Limit -->
                        <td class="cond-td-limit" style="text-align:center;">
                            <input
                                type="number"
                                class="cond-limit-input"
                                min="1"
                                max="50"
                                value="${Number(auto.max_daily_applications || 5)}"
                                data-client-max-daily="${cid}"
                                title="Max applications per day for this client"
                            >
                        </td>

                        <!-- 7. Actions -->
                        <td class="cond-td-actions" style="text-align:right;">
                            <div class="cond-actions-wrap">
                                <button
                                    type="button"
                                    class="cond-act-btn cond-act-primary"
                                    data-cond-action="run-client"
                                    data-client-id="${cid}"
                                    ${emergencyStop ? "disabled" : ""}
                                    title="Run daily search & cover letter generation for this client now"
                                >
                                    ▶ Run
                                </button>
                                <button
                                    type="button"
                                    class="cond-act-btn cond-act-secondary"
                                    data-cond-action="pause-client"
                                    data-client-id="${cid}"
                                    data-paused="${isPaused ? "false" : "true"}"
                                    title="${isPaused ? "Resume automation for this client" : "Pause automation for this client"}"
                                >
                                    ${isPaused ? "Resume" : "Pause"}
                                </button>
                                <button
                                    type="button"
                                    class="cond-act-btn cond-act-secondary"
                                    data-cond-action="send-digest"
                                    data-client-id="${cid}"
                                    title="Send WhatsApp progress digest to candidate"
                                >
                                    💬 WA
                                </button>
                                <button
                                    type="button"
                                    class="cond-act-btn cond-act-secondary"
                                    data-cond-action="request-docs"
                                    data-client-id="${cid}"
                                    title="Check dossier and request missing documents via WhatsApp"
                                >
                                    📄 Docs
                                </button>
                                <button
                                    type="button"
                                    class="cond-act-btn cond-act-details ${isExpanded ? "is-expanded" : ""}"
                                    data-cond-action="toggle-details"
                                    data-client-id="${cid}"
                                    title="Toggle client dossier details, package quota, documents, and preferences"
                                >
                                    <span class="cond-drawer-arrow">${isExpanded ? "▲" : "▼"}</span> Details
                                </button>
                            </div>
                        </td>
                    </tr>

                    <!-- Expandable Client Details Drawer Row -->
                    <tr class="cond-client-drawer-row" id="cond-drawer-${cid}" ${isExpanded ? "" : 'style="display:none;"'}>
                        <td colspan="7">
                            <div class="cond-drawer-container">
                                <div class="cond-drawer-grid">
                                    <!-- Card 1: Candidate Dossier & Contact -->
                                    <div class="cond-drawer-card">
                                        <div class="cond-drawer-card-title">
                                            <span>👤 Candidate Dossier</span>
                                            ${c.supabase_application_id ? '<span class="cond-sync-badge">✓ Synced with Supabase</span>' : '<span class="cond-sync-badge is-muted">Standalone Dossier</span>'}
                                        </div>
                                        <div class="cond-info-row">
                                            <span class="cond-info-label">Full Name:</span>
                                            <span class="cond-info-value">${escapeHtml(c.name || "—")}</span>
                                        </div>
                                        <div class="cond-info-row">
                                            <span class="cond-info-label">Email:</span>
                                            <span class="cond-info-value">${escapeHtml(c.email || "—")}</span>
                                        </div>
                                        <div class="cond-info-row">
                                            <span class="cond-info-label">Phone / WA:</span>
                                            <span class="cond-info-value">${escapeHtml(c.phone || "—")}</span>
                                        </div>
                                        <div class="cond-info-row">
                                            <span class="cond-info-label">Address:</span>
                                            <span class="cond-info-value">${escapeHtml(formatAddress(c.address, c.city))}</span>
                                        </div>
                                        <div class="cond-info-row">
                                            <span class="cond-info-label">Languages:</span>
                                            <span class="cond-info-value">${escapeHtml(formatLanguages(c.languages))}</span>
                                        </div>
                                        <div class="cond-info-row">
                                            <span class="cond-info-label">Supabase UUID:</span>
                                            <span class="cond-info-value" style="font-family:monospace; font-size:11px;">${escapeHtml(c.supabase_application_id || "None")}</span>
                                        </div>
                                    </div>

                                    <!-- Card 2: Opportunity & Target Preferences -->
                                    <div class="cond-drawer-card">
                                        <div class="cond-drawer-card-title">
                                            <span>🎯 Opportunity &amp; Target</span>
                                            <span class="cond-type-pill cond-type-${oppTypeClass}">${escapeHtml(oppType)}</span>
                                        </div>
                                        <div class="cond-info-row">
                                            <span class="cond-info-label">Target Role:</span>
                                            <span class="cond-info-value" style="color:var(--accent-secondary);">${escapeHtml(c.target_profession || c.title || "—")}</span>
                                        </div>
                                        <div class="cond-info-row">
                                            <span class="cond-info-label">Target Cities:</span>
                                            <span class="cond-info-value">${escapeHtml((c.target_cities || []).join(", ") || c.city || "bundesweit")}</span>
                                        </div>
                                        <div class="cond-info-row">
                                            <span class="cond-info-label">Relocation:</span>
                                            <span class="cond-info-value">${c.willing_to_relocate ? "✓ Yes (bundesweit)" : "Local only"}</span>
                                        </div>
                                        <div class="cond-info-row">
                                            <span class="cond-info-label">Availability:</span>
                                            <span class="cond-info-value">${escapeHtml(c.availability || "Sofort")}</span>
                                        </div>
                                        <div class="cond-info-row">
                                            <span class="cond-info-label">Suitable Fields:</span>
                                            <div class="cond-chip-group">
                                                ${(c.primary_fields || []).map(f => `<span class="cond-chip">${escapeHtml(f)}</span>`).join("") || '<span style="color:#64748b; font-size:11.5px;">Standard matching</span>'}
                                            </div>
                                        </div>
                                    </div>

                                    <!-- Card 3: Package, Quota & Channels -->
                                    <div class="cond-drawer-card">
                                        <div class="cond-drawer-card-title">
                                            <span>📦 Package &amp; Quota</span>
                                            <span class="cond-pay-pill ${payment.is_paid ? "is-paid" : "is-pending"}">${payment.is_paid ? "✓ Paid &amp; Verified" : "⏳ Pending Payment"}</span>
                                        </div>
                                        <div class="cond-info-row">
                                            <span class="cond-info-label">Package Name:</span>
                                            <span class="cond-info-value">${escapeHtml(quota.package_name || "Standard (500)")}</span>
                                        </div>
                                        <div class="cond-info-row">
                                            <span class="cond-info-label">Quota Progress:</span>
                                            <span class="cond-info-value">${quota.applied || 0} / ${quota.total_limit || 500} applied (${quota.remaining || 0} left)</span>
                                        </div>
                                        <div class="cond-quota-progress-wrap">
                                            <div class="cond-quota-bar-track">
                                                <div class="cond-quota-bar-fill" style="width:${quota.percent_used || 0}%;"></div>
                                            </div>
                                        </div>
                                        <div class="cond-info-row" style="margin-top:6px;">
                                            <span class="cond-info-label">Direct vs Portal:</span>
                                            <span class="cond-info-value">${channel.email_leads || 0} Direct Email • ${channel.portal_leads || 0} Portal Forms</span>
                                        </div>
                                        <div class="cond-info-row">
                                            <span class="cond-info-label">Autopilot Ready:</span>
                                            <span class="cond-info-value" style="color:${readiness.is_ready_for_automation ? 'var(--status-success)' : 'var(--status-warning)'};">
                                                ${readiness.is_ready_for_automation ? "✓ Ready for cycle execution" : `⚠ Blocked: ${(readiness.blocking_reasons || []).join(", ")}`}
                                            </span>
                                        </div>
                                    </div>

                                    <!-- Card 4: Documents Vault & Dataset Availability -->
                                    <div class="cond-drawer-card">
                                        <div class="cond-drawer-card-title">
                                            <span>📁 Documents Vault &amp; Leads</span>
                                            <span class="cond-doc-count-badge">${(c.documents || []).length} Document(s)</span>
                                        </div>
                                        <div class="cond-doc-list">
                                            ${(c.documents || []).length ? (c.documents || []).map(d => `
                                                <div class="cond-doc-item">
                                                    <span class="cond-doc-badge cond-doc-badge-${(d.category || 'sonstiges').toLowerCase()}">${escapeHtml(d.category || 'Doc')}</span>
                                                    <span class="cond-doc-filename" title="${escapeHtml(d.filename)}">${escapeHtml(d.filename)}</span>
                                                    <span class="cond-doc-size">${d.size_kb || 0} KB</span>
                                                    <a href="/api/clients/${encodeURIComponent(c.id)}/documents/${encodeURIComponent(d.filename)}" class="cond-btn cond-btn-sm" download>Download</a>
                                                </div>
                                            `).join("") : `
                                                <div class="cond-doc-empty">
                                                    ⚠ No documents in dossier. Candidate needs CV.
                                                </div>
                                            `}
                                        </div>
                                        <div class="cond-drawer-sub-row">
                                            <div class="cond-info-row">
                                                <span class="cond-info-label">Dataset Leads:</span>
                                                <span class="cond-info-value" style="color:${dataset.status === 'available' ? 'var(--status-success)' : 'var(--status-warning)'};">
                                                    ${dataset.status === 'available' ? `✓ ${dataset.available_listings} leads (${dataset.matched_files_count} dataset file(s))` : '⚠ No matching dataset (Scrape required)'}
                                                </span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </td>
                    </tr>
                `;
            }).join("");

            return `
                <div class="cond-card">
                    <!-- Client Table Toolbar -->
                    <div class="cond-card-header">
                        <div class="cond-card-heading">
                            <h3>Managed Clients &amp; Orchestration Controls</h3>
                            <p class="cond-card-sub">Control daily discovery, automated cover letter generation, submission authorization, and WhatsApp liaisons per client.</p>
                        </div>
                        <!-- Search and Filter Bar -->
                        <div class="cond-filter-toolbar">
                            <div class="cond-search-wrap">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                                <input
                                    type="text"
                                    id="cond-client-search"
                                    class="cond-search-input"
                                    placeholder="Search candidate, profession, or city..."
                                    value="${escapeHtml(state.clientSearchQuery || "")}"
                                >
                            </div>
                            <select id="cond-client-filter-status" class="cond-select-sm">
                                <option value="all" ${state.clientFilterStatus === "all" ? "selected" : ""}>All Clients (${clients.length})</option>
                                <option value="active" ${state.clientFilterStatus === "active" ? "selected" : ""}>Active Only</option>
                                <option value="paused" ${state.clientFilterStatus === "paused" ? "selected" : ""}>Paused Only</option>
                                <option value="paid" ${state.clientFilterStatus === "paid" ? "selected" : ""}>Paid Only</option>
                                <option value="ausbildung" ${state.clientFilterStatus === "ausbildung" ? "selected" : ""}>Ausbildung</option>
                                <option value="job" ${state.clientFilterStatus === "job" ? "selected" : ""}>Jobs</option>
                            </select>
                        </div>
                    </div>

                    <!-- Client Table -->
                    <div class="cond-table-responsive">
                        <table class="cond-table">
                            <thead>
                                <tr>
                                    <th style="min-width:210px;">Candidate &amp; Target Opportunity</th>
                                    <th style="min-width:110px;">Worker Status</th>
                                    <th style="min-width:155px;">Package &amp; Quota</th>
                                    <th style="min-width:115px;">Pipeline</th>
                                    <th style="min-width:185px;">Automation Switches</th>
                                    <th style="min-width:75px; text-align:center;">Daily Limit</th>
                                    <th style="min-width:210px; text-align:right;">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${rows || `<tr><td colspan="7" class="cond-td-empty">No candidates match your search filter.</td></tr>`}
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
                    let statusBadge = `<span class="cond-pill-status">${escapeHtml(status)}</span>`;
                    if (status === "staged_for_approval") {
                        statusBadge = `<span class="cond-pill-status is-staged">⏳ Staged for Approval</span>`;
                    } else if (status === "applied") {
                        statusBadge = `<span class="cond-pill-status is-applied">✓ Applied</span>`;
                    } else if (status === "interview") {
                        statusBadge = `<span class="cond-pill-status is-interview">🎉 Interview</span>`;
                    } else if (status === "rejected") {
                        statusBadge = `<span class="cond-pill-status is-rejected">✕ Rejected</span>`;
                    }

                    return `
                          <tr>
                              <td><code class="cond-code">${escapeHtml(m.client_id)}</code></td>
                              <td>
                                  <div style="font-weight:600; color:var(--text-primary);">${escapeHtml(m.job_title)}</div>
                                  <div style="font-size:11.5px; color:var(--text-secondary);">Source: ${escapeHtml(m.source || "dataset")}</div>
                              </td>
                              <td>
                                  <div style="color:var(--text-primary); font-weight:500;">${escapeHtml(m.company)}</div>
                                  <div style="font-size:11.5px; color:var(--text-secondary);">${escapeHtml(m.location || "")} ${m.email ? "• " + escapeHtml(m.email) : ""}</div>
                              </td>
                              <td><strong style="color:var(--accent-secondary);">${Math.round(Number(m.score || 0.85) * 100)}%</strong></td>
                              <td>${hasPdf ? `<span style="color:var(--status-success); font-size:12px; font-weight:600;">✓ PDF Ready</span>` : `<span style="color:var(--text-muted); font-size:12px;">—</span>`}</td>
                              <td>${statusBadge}</td>
                              <td style="text-align:right;">
                                  ${status === "staged_for_approval" || status === "discovered"
                            ? `<button type="button" class="cond-btn cond-btn-sm cond-btn-primary" data-cond-action="approve-match" data-match-id="${mid}">✓ Authorize &amp; Apply</button>`
                            : `<span style="font-size:11.5px; color:var(--text-muted);">Updated ${formatIsoTime(m.updated_at)}</span>`
                        }
                              </td>
                          </tr>
                      `;
                }).join("")
                : `<tr><td colspan="7" class="cond-td-empty">No matching opportunities in pipeline for current filter. Click "Run Cycle" to discover &amp; stage matches.</td></tr>`;

            return `
                <div class="cond-card">
                    <div class="cond-card-header">
                        <div class="cond-card-heading">
                            <h3>Discovered Opportunities &amp; Authorization Queue</h3>
                            <p class="cond-card-sub">Review generated cover letters and authorize staged applications per client.</p>
                        </div>
                        <div class="cond-filter-toolbar">
                            <select id="cond-filter-client" class="cond-select-sm">
                                <option value="">All Clients</option>
                                ${clientOptions}
                            </select>
                            <select id="cond-filter-status" class="cond-select-sm">
                                <option value="" ${state.matchFilterStatus === "" ? "selected" : ""}>All Statuses</option>
                                <option value="staged_for_approval" ${state.matchFilterStatus === "staged_for_approval" ? "selected" : ""}>Staged for Approval</option>
                                <option value="applied" ${state.matchFilterStatus === "applied" ? "selected" : ""}>Applied</option>
                                <option value="interview" ${state.matchFilterStatus === "interview" ? "selected" : ""}>Interview</option>
                                <option value="rejected" ${state.matchFilterStatus === "rejected" ? "selected" : ""}>Rejected</option>
                            </select>
                        </div>
                    </div>
                    <div class="cond-table-responsive">
                        <table class="cond-table">
                            <thead>
                                <tr>
                                    <th>Client ID</th>
                                    <th>Position / Title</th>
                                    <th>Company &amp; Contact</th>
                                    <th>Match</th>
                                    <th>Cover Letter</th>
                                    <th>Status</th>
                                    <th style="text-align:right;">Authorization</th>
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
                    let intentClass = "is-other";
                    if (intent === "interview_invitation") intentClass = "is-interview";
                    else if (intent === "rejection") intentClass = "is-rejection";
                    else if (intent === "info_request") intentClass = "is-info";
                    else if (intent === "confirmation_of_receipt") intentClass = "is-confirm";

                    return `
                          <tr>
                              <td style="font-size:12px; color:var(--text-secondary);">${formatIsoTime(item.received_at)}</td>
                              <td>
                                  <div style="font-weight:600; color:var(--text-primary);">${escapeHtml(item.matched_company || item.sender)}</div>
                                  <div style="font-size:11.5px; color:var(--text-secondary);">${escapeHtml(item.sender)}</div>
                              </td>
                              <td>
                                  <span class="cond-pill-status ${intentClass}">
                                      ${escapeHtml(intent)} (${Math.round(Number(item.confidence || 0.85) * 100)}%)
                                  </span>
                              </td>
                              <td><code class="cond-code">${escapeHtml(item.matched_client_id || "—")}</code></td>
                              <td>
                                  <div style="font-weight:600; font-size:12.5px; color:var(--text-primary);">${escapeHtml(item.subject)}</div>
                                  <div style="font-size:12px; color:var(--text-secondary); margin-top:2px;">${escapeHtml(item.summary)}</div>
                                  ${item.suggested_reply
                            ? `<div class="cond-draft-box"><strong>Draft Reply:</strong> ${escapeHtml(item.suggested_reply)}</div>`
                            : ""
                        }
                              </td>
                              <td style="font-size:12px; color:var(--text-secondary);">${escapeHtml(item.action_taken)}</td>
                          </tr>
                      `;
                }).join("")
                : `<tr><td colspan="6" class="cond-td-empty">No recruiter replies processed yet. Use "Check Email Inbox" or test with the simulator below.</td></tr>`;

            return `
                <div class="cond-setup-grid">
                    <!-- Recruiter Email Simulator -->
                    <div class="cond-card">
                        <div class="cond-card-header">
                            <div class="cond-card-heading">
                                <h3>Recruiter Email Reply Simulator</h3>
                                <p class="cond-card-sub">Test AI intent classification, pipeline status synchronization, and candidate WhatsApp notifications.</p>
                            </div>
                        </div>
                        <div class="cond-form-grid">
                            <div class="cond-field">
                                <label class="cond-label">Target Client (Optional):</label>
                                <select id="cond-sim-client" class="cond-select">
                                    <option value="">Auto-Correlate by Company/Domain</option>
                                    ${clientOptions}
                                </select>
                            </div>
                            <div class="cond-field">
                                <label class="cond-label">Recruiter Sender Email:</label>
                                <input type="text" id="cond-sim-sender" class="cond-input" value="karriere@alpha-tech.de">
                            </div>
                            <div class="cond-field">
                                <label class="cond-label">Subject Line:</label>
                                <input type="text" id="cond-sim-subject" class="cond-input" value="Einladung zum Vorstellungsgespräch - Alpha Solutions GmbH">
                            </div>
                        </div>
                        <div class="cond-field" style="margin-top:12px;">
                            <label class="cond-label">Email Body Content:</label>
                            <textarea id="cond-sim-body" class="cond-textarea" rows="2">Sehr geehrte(r) Bewerber(in), vielen Dank für Ihre Bewerbung! Wir möchten Sie herzlich zu einem Vorstellungsgespräch am kommenden Dienstag um 10:00 Uhr einladen.</textarea>
                        </div>
                        <div class="cond-preset-bar">
                            <button type="button" class="cond-btn cond-btn-primary" data-cond-action="simulate-email">
                                🧪 Classify &amp; Process Email
                            </button>
                            <button type="button" class="cond-btn cond-btn-secondary" data-cond-preset="interview">
                                Preset: Interview Invitation
                            </button>
                            <button type="button" class="cond-btn cond-btn-secondary" data-cond-preset="info_request">
                                Preset: Missing Document Request
                            </button>
                            <button type="button" class="cond-btn cond-btn-secondary" data-cond-preset="confirmation">
                                Preset: Receipt Confirmation
                            </button>
                            <button type="button" class="cond-btn cond-btn-secondary" data-cond-preset="rejection">
                                Preset: Rejection
                            </button>
                        </div>
                    </div>

                    <!-- Processed Replies Log -->
                    <div class="cond-card">
                        <div class="cond-card-header">
                            <div class="cond-card-heading">
                                <h3>Processed Recruiter Replies &amp; AI Follow-Up Drafts</h3>
                                <p class="cond-card-sub">Inbound email events analyzed by Luna AI email monitoring engine.</p>
                            </div>
                        </div>
                        <div class="cond-table-responsive">
                            <table class="cond-table">
                                <thead>
                                    <tr>
                                        <th>Received</th>
                                        <th>Company / Sender</th>
                                        <th>AI Intent</th>
                                        <th>Client</th>
                                        <th>Subject, Summary &amp; Draft</th>
                                        <th>Action Taken</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${rows}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            `;
        }

        function renderLogsAndSettingsTab(tasks, logs, settings) {
            const taskRows = tasks.length
                ? tasks.map((t) => `
                    <tr>
                        <td><code class="cond-code">${escapeHtml(t.id)}</code></td>
                        <td><strong style="color:var(--text-primary);">${escapeHtml(t.task_type)}</strong></td>
                        <td><code class="cond-code">${escapeHtml(t.client_id)}</code></td>
                        <td>
                            <span class="cond-pill-status ${t.status === "completed" ? "is-applied" : t.status === "failed" ? "is-rejected" : "is-info"}">
                                ${escapeHtml(t.status)} ${t.retry_count ? `(Retries: ${t.retry_count})` : ""}
                            </span>
                        </td>
                        <td style="font-size:12px; color:var(--text-secondary);">${escapeHtml(t.result_summary || t.error_message || "—")}</td>
                        <td style="font-size:11.5px; color:var(--text-muted);">${formatIsoTime(t.created_at)}</td>
                        <td style="text-align:right;">
                            ${t.status === "failed"
                        ? `<button type="button" class="cond-btn cond-btn-sm cond-btn-secondary" data-cond-action="retry-task" data-task-id="${escapeHtml(t.id)}">↻ Retry</button>`
                        : ""
                    }
                        </td>
                    </tr>
                `).join("")
                : `<tr><td colspan="7" class="cond-td-empty">No tasks executed yet.</td></tr>`;

            const logRows = logs.length
                ? logs.map((l) => `
                    <tr>
                        <td style="font-size:11.5px; color:var(--text-muted); white-space:nowrap;">${formatIsoTime(l.created_at)}</td>
                        <td><span class="cond-pill-status">${escapeHtml(l.level)}</span></td>
                        <td><code class="cond-code">${escapeHtml(l.module)}</code></td>
                        <td><code class="cond-code">${escapeHtml(l.client_id || "system")}</code></td>
                        <td style="font-size:12.5px; color:var(--text-primary);">${escapeHtml(l.message)}</td>
                    </tr>
                `).join("")
                : `<tr><td colspan="5" class="cond-td-empty">No activity logs recorded yet.</td></tr>`;

            return `
                <div class="cond-setup-grid">
                    <!-- Global Configuration Card -->
                    <div class="cond-card">
                        <div class="cond-card-header">
                            <div class="cond-card-heading">
                                <h3>Global Conductor Schedule &amp; Circuit Breaker</h3>
                                <p class="cond-card-sub">Tune autonomous background intervals, automated email checking, and circuit breaker limits.</p>
                            </div>
                        </div>
                        <div class="cond-config-grid">
                            <label class="cond-switch-wrap" style="align-items:center;">
                                <input type="checkbox" class="cond-switch-input" id="cond-set-auto-search" ${String(settings.auto_daily_search || "true") === "true" ? "checked" : ""}>
                                <span class="cond-switch-track"></span>
                                <span class="cond-switch-lbl" style="font-size:12.5px; color:var(--text-primary);">Enable Scheduled Daily Searches</span>
                            </label>
                            <label class="cond-switch-wrap" style="align-items:center;">
                                <input type="checkbox" class="cond-switch-input" id="cond-set-auto-email" ${String(settings.auto_email_monitoring || "true") === "true" ? "checked" : ""}>
                                <span class="cond-switch-track"></span>
                                <span class="cond-switch-lbl" style="font-size:12.5px; color:var(--text-primary);">Enable Scheduled IMAP Email Monitoring</span>
                            </label>
                            <label class="cond-switch-wrap" style="align-items:center;">
                                <input type="checkbox" class="cond-switch-input" id="cond-set-auto-wa" ${String(settings.auto_whatsapp_updates || "true") === "true" ? "checked" : ""}>
                                <span class="cond-switch-track"></span>
                                <span class="cond-switch-lbl" style="font-size:12.5px; color:var(--text-primary);">Enable Proactive WhatsApp Updates</span>
                            </label>

                            <div class="cond-field">
                                <label class="cond-label">Daily Search Interval (Hours):</label>
                                <input type="number" id="cond-set-search-hours" class="cond-input" min="1" max="168" value="${escapeHtml(settings.daily_search_interval_hours || "24")}">
                            </div>
                            <div class="cond-field">
                                <label class="cond-label">Email Check Interval (Minutes):</label>
                                <input type="number" id="cond-set-email-mins" class="cond-input" min="1" max="1440" value="${escapeHtml(settings.email_monitor_interval_minutes || "15")}">
                            </div>
                            <div class="cond-field">
                                <label class="cond-label">Max Consecutive Errors (Circuit Breaker):</label>
                                <input type="number" id="cond-set-max-errors" class="cond-input" min="1" max="50" value="${escapeHtml(settings.max_consecutive_errors || "5")}">
                            </div>
                        </div>
                        <div style="margin-top:16px; display:flex; justify-content:flex-end;">
                            <button type="button" class="cond-btn cond-btn-primary" data-cond-action="save-settings">
                                Save Global Settings
                            </button>
                        </div>
                    </div>

                    <!-- Task Execution Queue -->
                    <div class="cond-card">
                        <div class="cond-card-header">
                            <div class="cond-card-heading">
                                <h3>Task Queue &amp; Autonomous Worker History</h3>
                                <p class="cond-card-sub">Recent automated job queue executions and error recovery states.</p>
                            </div>
                        </div>
                        <div class="cond-table-responsive">
                            <table class="cond-table">
                                <thead>
                                    <tr>
                                        <th>Task ID</th>
                                        <th>Type</th>
                                        <th>Client</th>
                                        <th>Status</th>
                                        <th>Summary / Error</th>
                                        <th>Created</th>
                                        <th style="text-align:right;">Action</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${taskRows}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <!-- Real-Time Activity Log -->
                    <div class="cond-card">
                        <div class="cond-card-header">
                            <div class="cond-card-heading">
                                <h3>Real-Time Activity &amp; Audit Logs</h3>
                                <p class="cond-card-sub">Live audit trail of autonomous engine events and system decisions.</p>
                            </div>
                        </div>
                        <div class="cond-table-responsive">
                            <table class="cond-table">
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
                    render();
                } else if (action === "sync-applications") {
                    showToast("Synchronizing with Supabase applications and candidate dossiers...", "info");
                    actionBtn.disabled = true;
                    try {
                        const res = await fetch("/api/conductor/sync-applications", { method: "POST" });
                        const data = await res.json();
                        if (data.success) {
                            showToast(data.summary || `Sync complete: ${data.newly_imported} new, ${data.synced_existing} up to date.`, "success");
                        } else {
                            showToast(data.error || "Sync failed.", "warn");
                        }
                    } catch (err) {
                        showToast(`Sync error: ${err.message}`, "warn");
                    } finally {
                        actionBtn.disabled = false;
                        await fetchAllData();
                    }
                } else if (action === "toggle-details" && clientId) {
                    if (state.expandedClients.has(clientId)) {
                        state.expandedClients.delete(clientId);
                    } else {
                        state.expandedClients.add(clientId);
                    }
                    const drawer = document.getElementById(`cond-drawer-${clientId}`);
                    const arrow = actionBtn.querySelector(".cond-drawer-arrow");
                    if (drawer) {
                        const isHidden = drawer.style.display === "none";
                        drawer.style.display = isHidden ? "" : "none";
                        if (arrow) arrow.textContent = isHidden ? "▲" : "▼";
                    }
                    actionBtn.classList.toggle("is-expanded", state.expandedClients.has(clientId));
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
                    showToast(data.success ? `Inbox check finished (${data.status || "ok"}): ${data.processed_count || 0} message(s) processed.` : `Inbox check failed: ${data.error || data.status || "unconfigured"}`, data.success ? "info" : "warn");
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
                    showToast(data.message || data.error || "Match action completed.", data.success ? "success" : "warn");
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
                    showToast(data.message || "Saved global settings.", "success");
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
            } else if (e.target.id === "cond-client-filter-status") {
                state.clientFilterStatus = e.target.value;
                render();
            }
        }

        function handleInput(e) {
            if (e.target.id === "cond-client-search") {
                state.clientSearchQuery = e.target.value;
                render();
            }
        }

        if (root) {
            root.addEventListener("click", handleActionClick);
            root.addEventListener("change", handleChange);
            root.addEventListener("input", handleInput);
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

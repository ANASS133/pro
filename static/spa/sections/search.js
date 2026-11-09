(function () {
    const sections = window.SPASections || {};

    sections.createSearchSection = function createSearchSection() {
        const formOne = document.getElementById("search_form_1");
        const formTwo = document.getElementById("search_form_2");

        if (!formOne) {
            return {
                show() {},
                hide() {},
            };
        }

        const escapeHtml = window.SPAUtils.escapeHtml;
        const INDEX_STATE_KEY = "aa_index_form_state_v2";

        function updateFilterSummaryBadge() {
            const badge = document.getElementById("filters_summary_badge");
            if (!badge) return;
            const srcEl = document.getElementById("search_source_1");
            const dateEl = document.getElementById("published_since");
            const radEl = document.getElementById("search_radius");

            const srcLabels = {
                all: "All Sources",
                job_portals: "Job Portals Only",
                google_maps: "Google Maps Only",
            };
            const dateLabels = {
                "30days": "30 Days",
                "14days": "14 Days",
                "7days": "7 Days",
                all: "All Listings",
            };
            const srcVal = srcEl ? srcEl.value : "all";
            const srcText = srcLabels[srcVal] || "All Sources";
            const radText = (radEl && radEl.value) ? ` • +${radEl.value} km` : "";

            if (srcVal === "google_maps") {
                badge.textContent = `${srcText}${radText}`;
            } else {
                const dateText = dateLabels[dateEl ? dateEl.value : "30days"] || "30 Days";
                badge.textContent = `${srcText} • ${dateText}${radText}`;
            }
        }

        function handleSearchSourceChange() {
            const srcEl = document.getElementById("search_source_1");
            if (!srcEl) return;
            const val = srcEl.value; // 'all', 'job_portals', 'google_maps'

            const aiSection = document.getElementById("ai_employer_detection_section");
            const pubSinceItem = document.getElementById("filter_item_published_since");

            // 1. AI Employer Detection visibility:
            // Google Maps Only or All Sources -> Visible
            // Job Portals Only -> Hidden completely
            if (aiSection) {
                if (val === "job_portals") {
                    aiSection.style.display = "none";
                } else {
                    aiSection.style.display = "block";
                }
            }

            // 2. Publication Period filter inside Advanced Filters:
            // Job Portals Only or All Sources -> Visible
            // Google Maps Only -> Hidden (maps has no publication date)
            if (pubSinceItem) {
                if (val === "google_maps") {
                    pubSinceItem.style.display = "none";
                } else {
                    pubSinceItem.style.display = "block";
                }
            }

            updateFilterSummaryBadge();

            try {
                const url = new URL(window.location.href);
                if (url.searchParams.get("source") !== val) {
                    url.searchParams.set("source", val);
                    window.history.replaceState({}, "", url);
                }
            } catch (_) {}
        }

        function saveIndexState() {
            const modeChecked = document.querySelector('input[name="mode"]:checked');
            const state = {
                mode: modeChecked ? modeChecked.value : "ausbildung",
                keyword: document.getElementById("keyword") ? document.getElementById("keyword").value : "",
                location: document.getElementById("location") ? document.getElementById("location").value : "",
                published_since: document.getElementById("published_since") ? document.getElementById("published_since").value : "30days",
                search_source_1: document.getElementById("search_source_1") ? document.getElementById("search_source_1").value : "all",
                radius: document.getElementById("search_radius") ? document.getElementById("search_radius").value : "",
            };
            if (formTwo) {
                state.keyword_2 = document.getElementById("keyword_2") ? document.getElementById("keyword_2").value : "";
                state.location_2 = document.getElementById("location_2") ? document.getElementById("location_2").value : "";
                state.published_since_2 = document.getElementById("published_since_2") ? document.getElementById("published_since_2").value : "all";
                state.search_source_2 = document.getElementById("search_source_2") ? document.getElementById("search_source_2").value : "all";
            }
            localStorage.setItem(INDEX_STATE_KEY, JSON.stringify(state));
            updateFilterSummaryBadge();

            try {
                const url = new URL(window.location.href);
                if (url.searchParams.get("source") !== val) {
                    url.searchParams.set("source", val);
                    window.history.replaceState({}, "", url);
                }
            } catch (_) {}
        }

        function restoreIndexState() {
            const raw = localStorage.getItem(INDEX_STATE_KEY);
            if (!raw) {
                const ausRadio = document.getElementById("mode_ausbildung");
                const kwEl = document.getElementById("keyword");
                if (ausRadio && ausRadio.checked && kwEl && (!kwEl.value || kwEl.value.trim() === "")) {
                    kwEl.value = "Ausbildung als ";
                }
                updateFilterSummaryBadge();
                return;
            }

            try {
                const state = JSON.parse(raw);
                if (state.mode) {
                    const r = document.getElementById(`mode_${state.mode}`);
                    if (r) {
                        r.checked = true;
                        r.dispatchEvent(new Event("change"));
                    }
                }
                [
                    "keyword",
                    "location",
                    "published_since",
                    "search_source_1",
                    "keyword_2",
                    "location_2",
                    "published_since_2",
                    "search_source_2",
                ].forEach((id) => {
                    const element = document.getElementById(id);
                    if (!element) {
                        return;
                    }
                    if (typeof state[id] === "string" || typeof state[id] === "number") {
                        element.value = String(state[id]);
                    }
                });
                if (state.radius !== undefined) {
                    const radEl = document.getElementById("search_radius");
                    if (radEl) radEl.value = String(state.radius);
                }
                updateFilterSummaryBadge();
            } catch (_error) {
                // Ignore invalid local state.
            }
        }

        function bindIndexStatePersistence() {
            [
                "keyword",
                "location",
                "published_since",
                "search_source_1",
                "search_radius",
                "keyword_2",
                "location_2",
                "published_since_2",
                "search_source_2",
            ].forEach((id) => {
                const element = document.getElementById(id);
                if (!element) {
                    return;
                }
                element.addEventListener("input", saveIndexState);
                element.addEventListener("change", saveIndexState);
            });
            const modeRadios = document.querySelectorAll('input[name="mode"]');
            modeRadios.forEach((r) => r.addEventListener("change", saveIndexState));
        }

        function publishedSinceLabel(value) {
            const labels = {
                all: "Alle Anzeigen",
                "30days": "30 Tage",
                "14days": "14 Tage",
                "7days": "7 Tage",
                today: "Heute",
                yesterday: "Gestern",
                "1week": "7 Tage",
                "2weeks": "14 Tage",
                "4weeks": "30 Tage",
            };
            return labels[value] || "30 Tage";
        }

        function formatConsoleTime() {
            const d = new Date();
            return d.toTimeString().split(" ")[0];
        }

        // --- Real-time Scraper Monitoring Dashboard State ---
        let monTimerInterval = null;
        let monStartTime = null;
        let monLogs = [];
        let monItems = [];
        let monActiveLogFilter = "all";
        let monActiveItemFilter = "all";
        let monLogQuery = "";
        let monDashboardInitialized = false;

        function startExecutionTimer() {
            if (monTimerInterval) clearInterval(monTimerInterval);
            monStartTime = Date.now();
            const timerEl = document.getElementById("mon_exec_timer");
            monTimerInterval = setInterval(() => {
                if (!monStartTime || !timerEl) return;
                const elapsedMs = Date.now() - monStartTime;
                const totalSec = Math.floor(elapsedMs / 1000);
                const mins = String(Math.floor(totalSec / 60)).padStart(2, "0");
                const secs = String(totalSec % 60).padStart(2, "0");
                const tenths = Math.floor((elapsedMs % 1000) / 100);
                timerEl.textContent = `⏱ ${mins}:${secs}.${tenths}`;
            }, 100);
        }

        function stopExecutionTimer() {
            if (monTimerInterval) {
                clearInterval(monTimerInterval);
                monTimerInterval = null;
            }
        }

        function renderTerminalLogs(ui) {
            const terminal = (ui && ui.consoleTerminal) || document.getElementById("scraper_console_terminal_1");
            if (!terminal) return;
            const badgeLogs = document.getElementById("mon_badge_logs");
            if (badgeLogs) badgeLogs.textContent = String(monLogs.length);

            const q = monLogQuery.toLowerCase();
            const filtered = monLogs.filter(log => {
                if (monActiveLogFilter !== "all") {
                    const lvl = String(log.level || "info").toLowerCase();
                    if (monActiveLogFilter === "rejected" && !lvl.includes("reject") && !lvl.includes("warn")) return false;
                    if (monActiveLogFilter === "error" && !lvl.includes("error") && !lvl.includes("fail")) return false;
                    if (monActiveLogFilter === "success" && !lvl.includes("success")) return false;
                    if (monActiveLogFilter === "info" && lvl !== "info") return false;
                }
                if (q) {
                    const text = `${log.message || ""} ${log.source || ""} ${log.url || ""} ${log.reason || ""}`.toLowerCase();
                    if (!text.includes(q)) return false;
                }
                return true;
            });

            if (!filtered.length) {
                terminal.innerHTML = '<div class="terminal-row terminal-muted"><span class="terminal-ts">[--:--:--]</span> No logs match the selected filter.</div>';
                return;
            }

            const html = filtered.slice(-150).map(log => {
                let lvlClass = "terminal-lvl-info";
                const lvl = String(log.level || "info").toLowerCase();
                if (lvl.includes("error") || lvl.includes("fail")) lvlClass = "terminal-lvl-error";
                else if (lvl.includes("reject") || lvl.includes("warn")) lvlClass = "terminal-lvl-rejected";
                else if (lvl.includes("success")) lvlClass = "terminal-lvl-success";

                const srcTag = log.source ? `<span class="terminal-src">[${escapeHtml(log.source.toUpperCase())}]</span> ` : "";
                const urlTag = log.url ? ` <span style="color:#64748b; font-size:10.5px;">(${escapeHtml(log.url)})</span>` : "";
                const reasonTag = log.reason ? ` <span style="color:#f87171; font-size:10.5px; font-weight:600;">[Excluded: ${escapeHtml(log.reason)}]</span>` : "";

                return `<div class="terminal-row">
                    <span class="terminal-ts">[${escapeHtml(log.time || formatConsoleTime())}]</span>
                    ${srcTag}
                    <span class="${lvlClass}">${escapeHtml(log.message || "")}${urlTag}${reasonTag}</span>
                </div>`;
            }).join("");

            terminal.innerHTML = html;
            terminal.scrollTop = terminal.scrollHeight;
        }

        function renderDiscoveredItems() {
            const feed = document.getElementById("mon_discovered_items_feed");
            const badgeItems = document.getElementById("mon_badge_items");
            const countLabel = document.getElementById("mon_items_count_label");
            if (!feed) return;

            if (badgeItems) badgeItems.textContent = String(monItems.length);
            if (countLabel) countLabel.textContent = `${monItems.length} Opportunities Discovered`;

            const filtered = monItems.filter(item => {
                if (monActiveItemFilter === "accepted" && item.status !== "accepted") return false;
                if (monActiveItemFilter === "rejected" && item.status !== "rejected") return false;
                return true;
            });

            if (!filtered.length) {
                feed.innerHTML = '<div class="mon-items-empty">No opportunities match the selected filter.</div>';
                return;
            }

            feed.innerHTML = filtered.slice(-100).map(item => {
                const isAcc = item.status === "accepted";
                const badge = isAcc
                    ? '<span class="mon-match-badge">✓ Verified Match</span>'
                    : `<span class="mon-reason-badge">Excluded: ${escapeHtml(item.reason || "Filtered")}</span>`;
                const emailTag = item.email ? `<span>📧 ${escapeHtml(item.email)}</span>` : "";
                const srcTag = item.source ? `<span>Source: ${escapeHtml(item.source)}</span>` : "";

                return `
                    <div class="mon-item-card ${isAcc ? 'is-accepted' : 'is-rejected'}">
                        <div class="mon-item-left">
                            <span class="mon-item-title">${escapeHtml(item.title || "Position")}</span>
                            <span class="mon-item-company">${escapeHtml(item.company || "Employer")}</span>
                            <div class="mon-item-meta">
                                <span>📍 ${escapeHtml(item.location || "Germany")}</span>
                                ${srcTag}
                                ${emailTag}
                            </div>
                        </div>
                        <div class="mon-item-right">
                            ${badge}
                        </div>
                    </div>
                `;
            }).join("");
        }

        function initDashboardControls(ui) {
            if (monDashboardInitialized) return;
            monDashboardInitialized = true;

            // 1. Dashboard body minimize / expand toggle
            const toggleBtn = document.getElementById("mon_dashboard_toggle");
            const bodyEl = document.getElementById("mon_dashboard_body");
            if (toggleBtn && bodyEl) {
                toggleBtn.addEventListener("click", () => {
                    const isCollapsed = bodyEl.style.display === "none";
                    bodyEl.style.display = isCollapsed ? "block" : "none";
                    toggleBtn.textContent = isCollapsed ? "▲" : "▼";
                });
            }

            // 2. Portal Drawers
            document.querySelectorAll("[data-portal-toggle]").forEach(btn => {
                btn.addEventListener("click", () => {
                    const pId = btn.getAttribute("data-portal-toggle");
                    const drawer = document.querySelector(`[data-portal-drawer="${pId}"]`);
                    if (drawer) {
                        const isHidden = drawer.hidden;
                        drawer.hidden = !isHidden;
                        btn.textContent = isHidden ? "Details ▲" : "Details ▼";
                    }
                });
            });

            // 3. Tab switching
            const tabBtnLogs = document.getElementById("mon_tab_btn_logs");
            const tabBtnItems = document.getElementById("mon_tab_btn_items");
            const paneLogs = document.getElementById("mon_tab_pane_logs");
            const paneItems = document.getElementById("mon_tab_pane_items");

            if (tabBtnLogs && tabBtnItems && paneLogs && paneItems) {
                tabBtnLogs.addEventListener("click", () => {
                    tabBtnLogs.classList.add("is-active");
                    tabBtnItems.classList.remove("is-active");
                    paneLogs.style.display = "block";
                    paneItems.style.display = "none";
                });
                tabBtnItems.addEventListener("click", () => {
                    tabBtnItems.classList.add("is-active");
                    tabBtnLogs.classList.remove("is-active");
                    paneItems.style.display = "block";
                    paneLogs.style.display = "none";
                    renderDiscoveredItems();
                });
            }

            // 4. Log filter chips
            document.querySelectorAll("[data-log-filter]").forEach(chip => {
                chip.addEventListener("click", () => {
                    document.querySelectorAll("[data-log-filter]").forEach(c => c.classList.remove("is-active"));
                    chip.classList.add("is-active");
                    monActiveLogFilter = chip.getAttribute("data-log-filter") || "all";
                    renderTerminalLogs(ui);
                });
            });

            // 5. Log search input
            const logSearchInput = document.getElementById("mon_log_search_input");
            if (logSearchInput) {
                logSearchInput.addEventListener("input", (e) => {
                    monLogQuery = (e.target.value || "").trim();
                    renderTerminalLogs(ui);
                });
            }

            // 6. Console Clear
            const clearBtn = document.getElementById("scraper_console_clear_1");
            if (clearBtn) {
                clearBtn.addEventListener("click", () => {
                    monLogs = [];
                    renderTerminalLogs(ui);
                });
            }

            // 7. Export Logs Button
            const exportBtn = document.getElementById("mon_btn_export_logs");
            if (exportBtn) {
                exportBtn.addEventListener("click", () => {
                    const exportData = {
                        exported_at: new Date().toISOString(),
                        total_logs: monLogs.length,
                        total_items: monItems.length,
                        logs: monLogs,
                        items: monItems,
                    };
                    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = `jobscout_scraper_logs_${Date.now()}.json`;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                });
            }

            // 8. Item Filters
            document.querySelectorAll("[data-item-filter]").forEach(chip => {
                chip.addEventListener("click", () => {
                    document.querySelectorAll("[data-item-filter]").forEach(c => c.classList.remove("is-active"));
                    chip.classList.add("is-active");
                    monActiveItemFilter = chip.getAttribute("data-item-filter") || "all";
                    renderDiscoveredItems();
                });
            });
        }

        function logToConsole(ui, message, level = "info", sourceTag = "") {
            const timeStr = formatConsoleTime();
            monLogs.push({
                time: timeStr,
                level: level,
                source: sourceTag,
                message: message,
            });
            renderTerminalLogs(ui);
        }

        function setSearchProgress(ui, progressData) {
            const pct = Math.max(0, Math.min(100, Math.round(progressData.percent || 0)));
            const stage = progressData.stage || "";
            const found = typeof progressData.found === "number" ? progressData.found : 0;
            const rawFound = typeof progressData.raw_found === "number" ? progressData.raw_found : found;
            const source = progressData.source || "";
            const finishedSource = progressData.finished_source || "";
            const sourceCount = progressData.source_count;

            if (ui.progressCard) {
                ui.progressCard.style.display = "block";
            }

            // Ensure controls are wired
            initDashboardControls(ui);

            // 1. Update Live Target Banner
            if (ui.targetText && stage) {
                ui.targetText.textContent = stage;
            }

            // 2. Update Live Metrics Strip
            if (progressData.live_metrics) {
                const lm = progressData.live_metrics;
                if (ui.metricRaw) ui.metricRaw.textContent = String(lm.raw_scanned || 0);
                if (ui.metricMatched) ui.metricMatched.textContent = String(lm.accepted || 0);
                const rejEl = document.getElementById("mon_kpi_rejected");
                if (rejEl) rejEl.textContent = String(lm.rejected || 0);
                const dupEl = document.getElementById("mon_kpi_duplicates");
                if (dupEl) dupEl.textContent = String(lm.duplicates || 0);
                const errEl = document.getElementById("mon_kpi_errors");
                if (errEl) errEl.textContent = String(lm.errors || 0);
                if (ui.metricSource && lm.active_portal) {
                    const runningNames = (progressData.workers && progressData.workers.active_names) || [];
                    ui.metricSource.textContent = runningNames.length > 1 ? `${runningNames.length} running` : String(lm.active_portal);
                    ui.metricSource.title = String(lm.active_portal);
                }
            } else {
                if (ui.metricRaw) ui.metricRaw.textContent = String(rawFound);
                if (ui.metricMatched) ui.metricMatched.textContent = String(found);
                if (ui.metricSource && source) {
                    ui.metricSource.textContent = source.toUpperCase().replace("_", ".");
                }
            }

            // 3. Worker Status & Pipeline Summary
            if (progressData.workers) {
                const w = progressData.workers;
                const workerEl = document.getElementById("mon_worker_active");
                const running = Number(w.running ?? (typeof w.active === "number" ? w.active : 0)) || 0;
                const finished = Number(w.finished ?? ((w.completed || 0) + (w.failed || 0))) || 0;
                const total = Number(w.total) || 0;
                if (workerEl) {
                    const parts = [`${running} running`, `${w.queued || 0} queued`, `${w.completed || 0} done`];
                    if (w.failed) parts.push(`${w.failed} failed`);
                    workerEl.textContent = `Workers (parallel): ${parts.join(" • ")}`;
                    workerEl.title = (w.active_names || []).join(", ");
                }
                const summaryEl = document.getElementById("mon_pipeline_summary");
                if (summaryEl) {
                    summaryEl.textContent = `${finished}/${total} portals finished • ${running} running in parallel`;
                }
            }

            // 4. Portal Pipeline
            if (progressData.portals) {
                const stateLabels = {
                    pending: "Queued",
                    running: "Running",
                    completed: "Completed",
                    failed: "Failed",
                    timeout: "Timed out",
                    skipped: "Skipped",
                };
                Object.entries(progressData.portals).forEach(([pKey, pInfo]) => {
                    const state = String(pInfo.state || pInfo.status || "pending").toLowerCase();
                    const stateEl = document.querySelector(`[data-portal-state="${pKey}"]`);
                    if (stateEl) {
                        stateEl.className = `mon-portal-state state-${state}${pInfo.slow && state === "running" ? " is-slow" : ""}`;
                        let label = stateLabels[state] || state;
                        if (state === "running") {
                            const secs = Math.round((pInfo.elapsed_ms || 0) / 1000);
                            label = pInfo.slow ? `Slow • ${secs}s` : `Running • ${secs}s`;
                        }
                        stateEl.textContent = label;
                        stateEl.title = pInfo.current_task || "";
                    }
                    const cardEl = document.querySelector(`[data-portal-card="${pKey}"]`);
                    if (cardEl) {
                        cardEl.dataset.state = state;
                        cardEl.classList.toggle("is-slow", !!pInfo.slow && state === "running");
                    }
                    const countsEl = document.querySelector(`[data-portal-counts="${pKey}"]`);
                    if (countsEl) {
                        if (state === "skipped") {
                            countsEl.textContent = "Not selected";
                        } else if (state === "pending") {
                            countsEl.textContent = "Waiting for worker...";
                        } else if (state === "running" && !pInfo.scanned) {
                            countsEl.textContent = pInfo.current_task || "Fetching...";
                        } else if (state === "failed" || state === "timeout") {
                            countsEl.textContent = pInfo.current_task || "Failed";
                        } else {
                            countsEl.textContent = `${pInfo.scanned || 0} scanned • ${pInfo.accepted || 0} accepted`;
                        }
                        countsEl.title = pInfo.current_task || "";
                    }
                    const durEl = document.querySelector(`[data-portal-duration="${pKey}"]`);
                    if (durEl) {
                        const ms = pInfo.duration_ms || pInfo.elapsed_ms || 0;
                        if (ms) {
                            durEl.textContent = state === "running"
                                ? `Elapsed: ${(ms / 1000).toFixed(1)}s / timeout ${pInfo.timeout_s || "-"}s`
                                : `Duration: ${(ms / 1000).toFixed(1)}s`;
                        }
                    }
                    const breakEl = document.querySelector(`[data-portal-breakdown="${pKey}"]`);
                    if (breakEl) {
                        breakEl.innerHTML = `
                            <span class="mon-chip-sm">Accepted: ${pInfo.accepted || 0}</span>
                            <span class="mon-chip-sm">Rejected: ${pInfo.rejected || 0}</span>
                            <span class="mon-chip-sm">Duplicates: ${pInfo.duplicates || 0}</span>
                        `;
                    }
                });
            }

            // 5. Google Maps Live Crawler (Nationwide & Regional)
            if (progressData.google_maps_metrics) {
                const gm = progressData.google_maps_metrics;
                const gmCard = document.getElementById("mon_gmaps_monitor");
                if (gmCard) gmCard.style.display = "block";
                const cityEl = document.getElementById("mon_gmaps_city");
                if (cityEl) cityEl.textContent = gm.city || "-";
                const regCurEl = document.getElementById("mon_gmaps_current_region");
                if (regCurEl) regCurEl.textContent = gm.current_region || gm.city || "-";
                const catEl = document.getElementById("mon_gmaps_category");
                if (catEl) catEl.textContent = gm.category || "-";
                const compEl = document.getElementById("mon_gmaps_companies");
                if (compEl) compEl.textContent = String(gm.companies_found || 0);
                const webEl = document.getElementById("mon_gmaps_websites");
                if (webEl) webEl.textContent = String(gm.websites_visited || 0);
                const emailEl = document.getElementById("mon_gmaps_emails");
                if (emailEl) emailEl.textContent = String(gm.emails_extracted || 0);
                const vacEl = document.getElementById("mon_gmaps_vacancies");
                if (vacEl) vacEl.textContent = String(gm.verified_vacancies || 0);
                const potEl = document.getElementById("mon_gmaps_potential");
                if (potEl) potEl.textContent = String(gm.potential_employers || 0);

                const regEl = document.getElementById("mon_gmaps_regions");
                if (regEl) regEl.textContent = `${gm.regions_scanned || 0} / ${gm.regions_total || 16}`;
                const munEl = document.getElementById("mon_gmaps_municipalities");
                if (munEl) munEl.textContent = String(gm.municipalities_covered || 0);
                const statEl = document.getElementById("mon_gmaps_resume_status");
                if (statEl) {
                    const statusText = gm.resume_status || (gm.is_completed ? "Completed" : "Active");
                    statEl.textContent = statusText;
                    if (statusText === "completed" || statusText === "Completed") {
                        statEl.className = "mon-chip-sm mon-text-success";
                    } else if (statusText === "paused") {
                        statEl.className = "mon-chip-sm mon-text-warning";
                    } else {
                        statEl.className = "mon-chip-sm";
                    }
                }
            }

            // 6. Ingest New Logs
            if (Array.isArray(progressData.new_logs) && progressData.new_logs.length) {
                progressData.new_logs.forEach(l => monLogs.push(l));
                renderTerminalLogs(ui);
            } else if (stage && stage !== ui.lastLoggedStage && progressData.status !== "heartbeat") {
                ui.lastLoggedStage = stage;
                let lvl = "info";
                if (progressData.status === "source_done" || pct >= 100) lvl = "success";
                else if (progressData.status === "source_error") lvl = "error";
                logToConsole(ui, stage, lvl, source);
            }

            // 7. Ingest Discovered Items
            if (Array.isArray(progressData.recent_items) && progressData.recent_items.length) {
                progressData.recent_items.forEach(it => monItems.push(it));
                renderDiscoveredItems();
            }

            // 8. Update Search Button progress bar & label
            if (ui.btnBar) {
                ui.btnBar.style.width = `${pct}%`;
            }
            if (ui.btnLabel) {
                if (pct >= 100) {
                    ui.btnLabel.textContent = `Completed (${found} positions)`;
                } else if (found > 0) {
                    ui.btnLabel.textContent = `Searching... ${pct}% (${found} positions)`;
                } else {
                    ui.btnLabel.textContent = `Searching... ${pct}%`;
                }
            }

            // 9. Update Search Progress Card
            if (ui.searchProgressFill) {
                ui.searchProgressFill.style.width = `${pct}%`;
            }
            if (ui.searchProgressPct) {
                ui.searchProgressPct.textContent = `${pct}%`;
            }
            if (ui.progressCounter) {
                if (rawFound > found) {
                    ui.progressCounter.textContent = `${found} matching positions (${rawFound} scanned)`;
                } else {
                    ui.progressCounter.textContent = `${found} positions found`;
                }
            }
            if (ui.searchProgressStatus && stage) {
                ui.searchProgressStatus.textContent = stage;
            }

            // 10. Update Portal Badges (legacy)
            if (ui.searchProgressStages) {
                if (source && source !== "all") {
                    const activePill = ui.searchProgressStages.querySelector(`[data-portal="${source}"]`);
                    if (activePill) {
                        activePill.classList.add("is-active");
                    }
                }
                if (finishedSource) {
                    const donePill = ui.searchProgressStages.querySelector(`[data-portal="${finishedSource}"]`);
                    if (donePill) {
                        donePill.classList.remove("is-active");
                        donePill.classList.add("is-done");
                        const baseLabel = donePill.dataset.label || donePill.textContent.replace(/^✓\s*/, "").replace(/\s*\(\d+\)$/, "");
                        donePill.dataset.label = baseLabel;
                        if (typeof sourceCount === "number") {
                            donePill.textContent = `✓ ${baseLabel} (${sourceCount})`;
                        } else {
                            donePill.textContent = `✓ ${baseLabel}`;
                        }
                    }
                }
            }

            // 11. Update Sidebar Live Job Widget
            const sidebarJob = document.getElementById("sidebar-live-job");
            const sidebarTitle = document.getElementById("sidebar-job-title");
            const sidebarPercent = document.getElementById("sidebar-job-percent");
            const sidebarFill = document.getElementById("sidebar-job-fill");
            const sidebarMeta = document.getElementById("sidebar-job-meta");
            if (sidebarJob && sidebarTitle && sidebarPercent && sidebarFill && sidebarMeta) {
                sidebarJob.hidden = false;
                sidebarTitle.textContent = "Job search running";
                sidebarPercent.textContent = `${pct}%`;
                sidebarFill.style.width = `${pct}%`;
                sidebarMeta.textContent = stage || `${found} Stellen gefunden`;
            }
        }

        function setLoading(ui, loading) {
            if (loading) {
                ui.searchBtn.disabled = true;
                ui.searchBtn.classList.add("is-searching");
                if (ui.resultsBox) {
                    ui.resultsBox.classList.remove("visible");
                }
                if (ui.listEl) {
                    ui.listEl.innerHTML = "";
                }
                if (ui.filterBar) {
                    ui.filterBar.style.display = "none";
                }
                ui.lastJobs = [];

                const isUi1 = ui === searchUi1;
                const exportBtn = document.getElementById(isUi1 ? "export_excel_btn_1" : "export_excel_btn_2");
                if (exportBtn) {
                    exportBtn.style.display = "none";
                }
                if (ui.generateCoverLettersBtn) {
                    ui.generateCoverLettersBtn.style.display = "none";
                }

                if (ui.loadingEl) {
                    ui.loadingEl.style.display = "none";
                }
                if (ui.progressCard) {
                    ui.progressCard.style.display = "block";
                    const titleEl = document.getElementById("search_progress_title_1");
                    if (titleEl) titleEl.textContent = "Job search in progress...";
                    const bodyEl = document.getElementById("mon_dashboard_body");
                    if (bodyEl) bodyEl.style.display = "block";
                    const toggleBtn = document.getElementById("mon_dashboard_toggle");
                    if (toggleBtn) toggleBtn.textContent = "▲";

                    if (ui.searchProgressStages) {
                        ui.searchProgressStages.querySelectorAll(".stage-pill").forEach((p) => {
                            p.classList.remove("is-active", "is-done");
                            if (!p.dataset.label) {
                                p.dataset.label = p.textContent.trim().replace(/^✓\s*/, "").replace(/\s*\(\d+\)$/, "");
                            }
                            p.textContent = p.dataset.label;
                        });
                    }
                }

                // Reset dashboard state for new search
                startExecutionTimer();
                initDashboardControls(ui);
                monLogs = [];
                monItems = [];
                renderTerminalLogs(ui);
                renderDiscoveredItems();

                // Reset Portal cards
                document.querySelectorAll(".mon-portal-state").forEach(p => {
                    p.className = "mon-portal-state state-pending";
                    p.textContent = "Queued";
                });
                document.querySelectorAll(".mon-portal-counts").forEach(c => {
                    c.textContent = "Waiting for worker...";
                });
                document.querySelectorAll(".mon-portal-duration").forEach(d => {
                    d.textContent = "Duration: -";
                });
                document.querySelectorAll("[data-portal-card]").forEach(c => {
                    c.classList.remove("is-slow");
                    c.dataset.state = "pending";
                });
                const gmCard = document.getElementById("mon_gmaps_monitor");
                if (gmCard) gmCard.style.display = "none";

                setSearchProgress(ui, { percent: 5, stage: "Connecting to job portals & directories...", found: 0 });
            } else {
                ui.searchBtn.disabled = false;
                ui.searchBtn.classList.remove("is-searching");
                if (ui.btnBar) {
                    ui.btnBar.style.width = "0%";
                }
                if (ui.btnLabel) {
                    ui.btnLabel.textContent = "Start Search";
                }
                if (ui.loadingEl) {
                    ui.loadingEl.style.display = "none";
                }
                stopExecutionTimer();

                const titleEl = document.getElementById("search_progress_title_1");
                if (titleEl) titleEl.textContent = "Search Pipeline Complete";
                const activeTag = document.getElementById("mon_worker_active");
                if (activeTag) activeTag.textContent = "Worker: Done";

                // Keep dashboard visible! Do NOT auto-hide after 3.5s so user can inspect metrics.

                const sidebarJob = document.getElementById("sidebar-live-job");
                if (sidebarJob) {
                    setTimeout(() => {
                        sidebarJob.hidden = true;
                    }, 4000);
                }
            }
        }

        function getJobMethodCategory(job) {
            const email = String(job.email || "").trim();
            const hasValidEmail = Boolean(email && email.includes("@") && !email.toLowerCase().includes("failed") && !email.toLowerCase().includes("error") && !email.toLowerCase().includes("duplicate") && !email.toLowerCase().includes("none"));
            const hasVerifiedForm = Boolean(job.has_form === true || String(job.has_form).toLowerCase() === "true");
            const method = String(job.application_method || "").toLowerCase();

            if (method === "both" || (hasValidEmail && hasVerifiedForm)) {
                return "both";
            }
            if (method === "email" || (hasValidEmail && !hasVerifiedForm)) {
                return "email";
            }
            if (method === "form" || (hasVerifiedForm && !hasValidEmail)) {
                return "form";
            }
            return "missing";
        }

        function renderResults(ui, data) {
            ui.resultsBox.classList.add("visible");
            ui.errorEl.style.display = "none";
            ui.lastJobs = Array.isArray(data.jobs) ? data.jobs : [];

            const total = Number(data.total || ui.lastJobs.length || 0);
            const publishedSince = publishedSinceLabel(data.published_since || "all");
            let metaText = `${total} matching positions found | Veröffentlicht seit: ${publishedSince}`;
            if (data.audit && data.audit.raw_total) {
                metaText = `${total} matching positions from ${data.audit.raw_total} geprüften Angeboten | Veröffentlicht seit: ${publishedSince}`;
            }
            ui.metaEl.textContent = metaText;

            const isUi1 = ui === searchUi1;
            const exportBtn = document.getElementById(isUi1 ? "export_excel_btn_1" : "export_excel_btn_2");

            // Render Audit Summary Banner if audit data is present
            let auditBanner = ui.resultsBox.querySelector(".search-audit-banner");
            if (data.audit && data.audit.raw_total) {
                const a = data.audit;
                if (!auditBanner) {
                    auditBanner = document.createElement("div");
                    auditBanner.className = "search-audit-banner";
                    ui.resultsBox.insertBefore(auditBanner, ui.listEl);
                }
                const perSource = a.exclusions_by_source || {};
                const srcRows = Object.entries(perSource).map(([src, s]) => {
                    let note = [];
                    if (s.rejected_location) note.push(`${s.rejected_location} überregional`);
                    if (s.rejected_profession) note.push(`${s.rejected_profession} anderes Berufsfeld`);
                    if (s.rejected_date) note.push(`${s.rejected_date} veraltet`);
                    if (s.rejected_duplicate) note.push(`${s.rejected_duplicate} Dubletten`);
                    const noteStr = note.length ? `(${note.join(", ")})` : "";
                    return `<div style="display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid #f1f5f9;">
                        <span><strong>${escapeHtml(src)}:</strong> ${s.valid || 0} Treffer <small style="color:#64748b;">aus ${s.raw || 0} Angeboten</small></span>
                        <span style="color:#64748b; font-size:12px;">${escapeHtml(noteStr)}</span>
                    </div>`;
                }).join("");

                auditBanner.style.cssText = "background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:10px 14px; margin:10px 0; font-size:13px; color:#334155;";
                auditBanner.innerHTML = `
                    <div style="display:flex; justify-content:space-between; align-items:center; cursor:pointer;" id="audit_header_${isUi1 ? '1' : '2'}">
                        <span><strong>📊 Search Audit:</strong> ${a.filtered_total} matching positions from ${a.raw_total} Angeboten &bull; <span style="color:#64748b;">${a.exclusions_total} filtered out</span></span>
                        <button type="button" style="background:none; border:none; color:#2563eb; cursor:pointer; font-size:12px; font-weight:600;">Show details ▾</button>
                    </div>
                    <div id="audit_details_${isUi1 ? '1' : '2'}" style="display:none; margin-top:8px; padding-top:8px; border-top:1px solid #e2e8f0;">
                        <div style="margin-bottom:6px; font-weight:600; color:#1e293b;">Breakdown by Portal & Filter Criteria:</div>
                        ${srcRows}
                    </div>
                `;
                const hdr = auditBanner.querySelector(`#audit_header_${isUi1 ? '1' : '2'}`);
                const det = auditBanner.querySelector(`#audit_details_${isUi1 ? '1' : '2'}`);
                if (hdr && det) {
                    hdr.onclick = () => {
                        const isOpen = det.style.display !== "none";
                        det.style.display = isOpen ? "none" : "block";
                        const btn = hdr.querySelector("button");
                        if (btn) btn.textContent = isOpen ? "Show details ▾" : "Hide details ▴";
                    };
                }
            } else if (auditBanner) {
                auditBanner.remove();
            }

            if (!ui.lastJobs.length) {
                if (ui.filterBar) ui.filterBar.style.display = "none";
                ui.listEl.innerHTML = '<div class="job-item">No matching job listings found for these search criteria.</div>';
                ui.autoBtn.style.display = "none";
                if (exportBtn) exportBtn.style.display = "none";
                if (ui.generateCoverLettersBtn) ui.generateCoverLettersBtn.style.display = "none";
                return;
            }

            ui.autoBtn.style.display = "inline-flex";
            if (ui.generateCoverLettersBtn) ui.generateCoverLettersBtn.style.display = "inline-flex";

            // Update filter bar counts
            const counts = { all: ui.lastJobs.length, email: 0, form: 0, both: 0, missing: 0 };
            ui.lastJobs.forEach((job) => {
                const cat = getJobMethodCategory(job);
                if (counts[cat] !== undefined) {
                    counts[cat]++;
                }
            });

            if (ui.filterBar) {
                ui.filterBar.style.display = "flex";
                const prefix = isUi1 ? "_1" : "_2";
                const elAll = document.getElementById(`count_all${prefix}`);
                const elEmail = document.getElementById(`count_email${prefix}`);
                const elForm = document.getElementById(`count_form${prefix}`);
                const elBoth = document.getElementById(`count_both${prefix}`);
                const elMissing = document.getElementById(`count_missing${prefix}`);
                if (elAll) elAll.textContent = String(counts.all);
                if (elEmail) elEmail.textContent = String(counts.email);
                if (elForm) elForm.textContent = String(counts.form);
                if (elBoth) elBoth.textContent = String(counts.both);
                if (elMissing) elMissing.textContent = String(counts.missing);
            }

            const activeFilter = ui.activeFilter || "all";
            if (exportBtn) {
                exportBtn.style.display = "inline-flex";
                exportBtn.href = `/api/search/download?filter=${encodeURIComponent(activeFilter)}&search_run_id=${encodeURIComponent(ui.currentSearchRunId || "")}`;
            }

            const filteredJobs = ui.lastJobs.filter((job) => {
                if (activeFilter === "all") return true;
                return getJobMethodCategory(job) === activeFilter;
            });

            if (!filteredJobs.length) {
                ui.listEl.innerHTML = '<div class="job-item">Keine Stellen für den ausgewählten Filter ("' + escapeHtml(activeFilter) + '") vorhanden.</div>';
                return;
            }

            ui.listEl.innerHTML = filteredJobs.map((job) => {
                const title = escapeHtml(job.title || "Ohne Titel");
                const company = escapeHtml(job.company || "k. A.");
                const location = escapeHtml(job.location || job.city || "k. A.");
                const publishedDate = escapeHtml(job.published_date || "k. A.");
                const scrapedAt = escapeHtml(job.scraped_at || "k. A.");
                const source = escapeHtml(job.source || "Arbeitsagentur");
                const originalUrl = escapeHtml(String(job.apply_url || job.url || "").trim());
                const formUrl = escapeHtml(String(job.form_link || "").trim());
                const bewerbungLink = escapeHtml(String(job.bewerbung_link || formUrl || originalUrl || "").trim());
                const hasVerifiedForm = Boolean(job.has_form === true || String(job.has_form).toLowerCase() === "true");

                const email = String(job.email || "").trim();
                const hasValidEmail = Boolean(email && email.includes("@") && !email.toLowerCase().includes("failed") && !email.toLowerCase().includes("error") && !email.toLowerCase().includes("duplicate") && !email.toLowerCase().includes("none"));

                const sourceLower = source.toLowerCase();
                let sourceClass = "source-arbeitsagentur";
                if (sourceLower.includes("azubiyo")) {
                    sourceClass = "source-azubiyo";
                } else if (sourceLower.includes("aubi")) {
                    sourceClass = "source-aubi-plus";
                } else if (sourceLower.includes("ihk")) {
                    sourceClass = "source-ihk";
                } else if (sourceLower.includes("ausbildung")) {
                    sourceClass = "source-ausbildung-de";
                } else if (sourceLower.includes("maps") || sourceLower.includes("google")) {
                    sourceClass = "source-google-maps";
                }
                const sourceBadge = `<span class="job-source-pill ${sourceClass}">${source}</span>`;

                let contactBadge = "";
                if (hasValidEmail && hasVerifiedForm) {
                    contactBadge = `<span class="job-contact-pill has-both" title="Email & verified online application form available">⚡ Direct Email + Form</span>`;
                } else if (hasVerifiedForm) {
                    contactBadge = `<span class="job-contact-pill has-verified-form" title="Verified online application form">✅ Online Form</span>`;
                } else if (hasValidEmail) {
                    contactBadge = `<span class="job-contact-pill has-email" title="Direct recruiter email available">✉️ ${escapeHtml(email)}</span>`;
                }

                const aiButtonsHtml = `
                    <button type="button" class="job-link job-single-anschreiben-btn" data-index="${idx}" title="⚡ Create tailored cover letter in Cover Letter Studio">⚡ Cover Letter</button>
                    <button type="button" class="job-link job-vibe-btn" data-company="${company}" data-title="${title}" title="Inspect company culture, tone & address formula">🧭 Vibe</button>
                    <button type="button" class="job-link job-heatmap-btn" data-company="${company}" data-title="${title}" title="View visual ATS match & skill heatmap">📊 Heatmap</button>
                `;

                // Distinct, verified action buttons
                let actionButtonsHtml = "";
                if (hasVerifiedForm && formUrl) {
                    actionButtonsHtml += `<a class="job-link job-verified-apply-btn" href="${formUrl}" target="_blank" rel="noopener noreferrer" title="Zum echten verifizierten Online-Bewerbungsformular">📝 Apply via Form ↗</a>`;
                    actionButtonsHtml += `<button type="button" class="job-link job-autofill-btn" data-job-url="${formUrl}" data-job-title="${title}" data-job-company="${company}" title="Mit verifiziertem Formular bewerben & Autofill nutzen">⚡ Apply via Form (Autofill)</button>`;
                } else {
                    if (originalUrl) {
                        actionButtonsHtml += `<a class="job-link job-listing-btn" href="${originalUrl}" target="_blank" rel="noopener noreferrer" title="Originale Stellenanzeige aufrufen">Open Listing ↗</a>`;
                    }
                    if (bewerbungLink && bewerbungLink !== originalUrl) {
                        actionButtonsHtml += `<a class="job-link job-listing-btn" href="${bewerbungLink}" target="_blank" rel="noopener noreferrer" title="Karriereseite aufrufen">Open Careers Page ↗</a>`;
                    }
                }

                if (hasValidEmail) {
                    actionButtonsHtml += `<a class="job-link job-mail-btn" href="mailto:${escapeHtml(email)}?subject=Bewerbung%20als%20${encodeURIComponent(job.title || '')}" title="Bewerbungs-E-Mail senden">✉️ Send Email</a>`;
                }
                actionButtonsHtml += aiButtonsHtml;

                let oppBadge = "";
                const isVerifiedVacancy = job.is_verified_vacancy === true || job.opportunity_type === "VERIFIED_AUSBILDUNG";
                const isPotential = job.opportunity_type === "POTENTIAL_EMPLOYER" || job.is_potential_employer;

                if (isVerifiedVacancy) {
                    oppBadge = `<span class="job-contact-pill" style="background:#ecfdf5; color:#065f46; border:1px solid #a7f3d0;" title="Verifizierte aktive Ausschreibung auf Unternehmenswebsite">✓ Confirmed Vacancy</span>`;
                } else if (isPotential) {
                    oppBadge = `<span class="job-contact-pill" style="background:#eff6ff; color:#1e40af; border:1px solid #bfdbfe;" title="Relevanter potenzieller Ausbildungsbetrieb für Initiativbewerbungen">★ Potential Employer</span>`;
                }

                let catBadge = "";
                const catText = job.target_category || job.category;
                if (catText) {
                    catBadge = `<span class="job-contact-pill" style="background:#f8fafc; color:#475569; border:1px solid #cbd5e1;" title="Identifizierte Arbeitgeber-Branche">🏷️ ${escapeHtml(catText)}</span>`;
                }

                return `
                    <article class="job-item">
                        <div class="job-item-header" style="display:flex; align-items:flex-start; gap:10px;">
                            <input type="checkbox" class="job-select-checkbox" data-index="${idx}" title="Select for cover letter generation" style="margin-top:5px; width:17px; height:17px; cursor:pointer; accent-color:#6366f1;">
                            <div style="flex:1;">
                                <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px; flex-wrap:wrap;">
                                    <h4 class="job-title" style="margin:0;">${title}</h4>
                                    <div class="job-badges-wrap">
                                        ${sourceBadge}
                                        ${oppBadge}
                                        ${catBadge}
                                        ${contactBadge}
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="job-meta">
                            <strong>Company:</strong> ${company} &bull; 
                            <strong>Location:</strong> ${location}<br>
                            <strong>Published:</strong> ${publishedDate} &bull; 
                            <strong>Scraped:</strong> ${scrapedAt}
                        </div>
                        <div class="job-actions-row">
                            ${actionButtonsHtml}
                        </div>
                        <div class="job-ai-panel hidden"></div>
                    </article>
                `;
            }).join("");
        }

        function showError(ui, message) {
            ui.resultsBox.classList.add("visible");
            ui.metaEl.textContent = "";
            ui.listEl.innerHTML = "";
            ui.autoBtn.style.display = "none";
            if (ui.generateCoverLettersBtn) ui.generateCoverLettersBtn.style.display = "none";
            ui.errorEl.textContent = message || "Search failed.";
            ui.errorEl.style.display = "block";
        }

        function renderWorkers(container, workers, isRunning) {
            if (!container) return;
            const workerList = [1, 2, 3, 4].map(id => {
                const w = (workers && workers[`worker_${id}`]) || {
                    worker_id: id,
                    status: isRunning ? "active" : "idle",
                    connection_status: "direct",
                    network_profile: "Direct",
                    public_ip: "—",
                    current_platform: "No active platform",
                    current_job_title: "",
                    current_employer: "",
                    current_stage: "Idle",
                    current_company: "",
                    current_job: "",
                    completed_count: 0,
                    extraction_method: "",
                };
                return w;
            });

            container.innerHTML = workerList.map(w => {
                const status = (w.status || (isRunning ? "active" : "idle")).toLowerCase();
                const connStatus = (w.connection_status || "direct").toLowerCase();

                let statusClass = "worker-idle";
                let statusTag = "Idle";
                if (status === "paused") {
                    statusClass = "worker-paused";
                    statusTag = "Paused";
                } else if (status === "blocked" || status === "failed" || connStatus === "failed") {
                    statusClass = "worker-failed";
                    statusTag = status === "blocked" ? "Blocked" : "Failed";
                } else if (status === "manual_required") {
                    statusClass = "worker-rate-limited";
                    statusTag = "Manual Required";
                } else if (status === "waiting") {
                    statusClass = "worker-idle";
                    statusTag = "Waiting";
                } else if (status === "rate_limited") {
                    statusClass = "worker-rate-limited";
                    statusTag = "Rate Limited";
                } else if (status === "active" || status === "processing" || status === "working") {
                    statusClass = "worker-active";
                    statusTag = status === "working" ? "Working" : "Active";
                }

                let connClass = "conn-direct";
                let connLabel = "Direct";
                if (connStatus === "connected") {
                    connClass = "conn-connected";
                    connLabel = "Connected";
                } else if (connStatus === "degraded") {
                    connClass = "conn-degraded";
                    connLabel = "Degraded";
                } else if (connStatus === "failed") {
                    connClass = "conn-failed";
                    connLabel = "Offline";
                }

                // Platform identification & badge styling
                const isIdleState = (status === "idle" || (!isRunning && status !== "paused"));
                let rawPlatform = (w.current_platform || "").trim();
                let platform = rawPlatform;
                if (isIdleState && (!rawPlatform || rawPlatform === "—" || rawPlatform === "Paused")) {
                    platform = "No active platform";
                } else if (!rawPlatform) {
                    platform = status === "paused" ? (w.current_platform || "No active platform") : "No active platform";
                }

                let platformClass = "platform-none";
                const pLower = platform.toLowerCase();
                if (pLower.includes("arbeitsagentur")) {
                    platformClass = "platform-arbeitsagentur";
                } else if (pLower.includes("ausbildung.de") || pLower.includes("ausbildung_de")) {
                    platformClass = "platform-ausbildung-de";
                } else if (pLower.includes("azubiyo")) {
                    platformClass = "platform-azubiyo";
                } else if (pLower.includes("aubi")) {
                    platformClass = "platform-aubi-plus";
                } else if (pLower.includes("ihk")) {
                    platformClass = "platform-ihk";
                } else if (pLower.includes("maps")) {
                    platformClass = "platform-google-maps";
                }

                // Job Title and Employer details
                let jobTitle = (w.current_job_title || "").trim();
                let employer = (w.current_employer || w.current_company || w.company || "").trim();

                if (!jobTitle && !employer) {
                    if (status === "paused") {
                        jobTitle = "Paused";
                        employer = "";
                    } else if (isIdleState) {
                        jobTitle = "Waiting for task...";
                        employer = "—";
                    } else {
                        jobTitle = (w.current_job || "Processing position...").trim();
                        employer = "";
                    }
                } else if (!jobTitle) {
                    jobTitle = (w.current_job || "Apprenticeship Position").trim();
                }

                // Processing Stage
                let stage = (w.current_stage || w.method || w.extraction_method || "").trim();
                if (status === "paused") {
                    stage = "Paused";
                } else if (isIdleState && (!stage || stage === "—")) {
                    stage = "Idle";
                } else if (!stage || stage === "—") {
                    stage = status === "working" ? "HTTP Fast-Path" : "Waiting";
                }

                let stageClass = "stage-default";
                const stLower = stage.toLowerCase();
                if (stLower.includes("fast-http") || stLower.includes("fast_http") || stLower.includes("fast-path")) {
                    stageClass = "stage-fast-http";
                } else if (stLower.includes("selenium")) {
                    stageClass = "stage-selenium";
                } else if (stLower.includes("form")) {
                    stageClass = "stage-form";
                } else if (stLower.includes("email")) {
                    stageClass = "stage-email";
                } else if (stLower.includes("manual")) {
                    stageClass = "stage-manual";
                } else if (stLower.includes("paused")) {
                    stageClass = "stage-paused";
                }

                const doneCount = Number(w.completed_count || 0);
                const profile = escapeHtml(w.network_profile || "Direct");
                const ip = escapeHtml(w.public_ip || "—");
                const safePlatform = escapeHtml(platform);
                const safeTitle = escapeHtml(jobTitle);
                const safeEmployer = escapeHtml(employer);
                const safeStage = escapeHtml(stage);
                const tooltip = safeEmployer ? `${safeTitle} (${safeEmployer})` : safeTitle;

                return `<div class="worker-card ${statusClass}" data-worker="${w.worker_id}">
                    <div class="worker-card-head">
                        <span class="worker-name"><span class="w-dot"></span>Worker ${w.worker_id}</span>
                        <div class="worker-badges">
                            <span class="worker-conn-badge ${connClass}" title="Route Status">${connLabel}</span>
                            <span class="worker-tag">${statusTag}</span>
                        </div>
                    </div>
                    <div class="worker-route-info" title="Route: ${profile} | IP: ${ip}">
                        <span class="w-profile">${profile}</span>
                        <span class="w-sep">&bull;</span>
                        <span class="w-ip">${ip}</span>
                    </div>
                    <div class="worker-platform-row">
                        <span class="worker-platform-badge ${platformClass}" title="Source Platform: ${safePlatform}">
                            <span class="w-platform-dot"></span>
                            <span class="w-platform-name">${safePlatform}</span>
                        </span>
                    </div>
                    <div class="worker-job-block" title="${tooltip}">
                        <div class="worker-job-title" title="${safeTitle}">${safeTitle}</div>
                        <div class="worker-employer" title="${safeEmployer}">${safeEmployer || "&nbsp;"}</div>
                    </div>
                    <div class="worker-meta">
                        <span class="w-stage ${stageClass}" title="Current Stage: ${safeStage}">${safeStage}</span>
                        <span class="w-count">${doneCount} done</span>
                    </div>
                </div>`;
            }).join("");
        }

        function renderActivityFeed(container, counterEl, feedItems) {
            if (!container) return;
            if (!feedItems || feedItems.length === 0) {
                container.innerHTML = `<div class="feed-empty-state">Waiting for extraction events...</div>`;
                if (counterEl) counterEl.textContent = "0 events";
                return;
            }

            if (counterEl) counterEl.textContent = `${feedItems.length} events`;

            const recent = feedItems.slice(-20).reverse();
            container.innerHTML = recent.map(item => {
                const time = escapeHtml(item.time || "");
                const text = escapeHtml(item.text || "");
                const type = escapeHtml(item.type || "info");
                const company = item.company ? `<span class="feed-company">(${escapeHtml(item.company)})</span>` : "";

                let iconSvg = "";
                let typeClass = `feed-item-${type}`;
                if (type === "email" || type === "recruitment") {
                    iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>`;
                } else if (type === "form") {
                    iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>`;
                } else if (type === "fast_path") {
                    iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>`;
                } else if (type === "selenium") {
                    iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>`;
                } else if (type === "rate_limit") {
                    iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>`;
                } else if (type === "error") {
                    iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>`;
                } else {
                    iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`;
                }

                const fullFeedText = item.company ? `${text} (${item.company})` : text;
                return `<div class="dash-feed-item ${typeClass}">
                    <span class="feed-time">${time}</span>
                    <span class="feed-icon">${iconSvg}</span>
                    <span class="feed-text" title="${escapeHtml(fullFeedText)}">${text} ${company}</span>
                </div>`;
            }).join("");
        }

        function renderCaptchaDiagnostics(container, events) {
            if (!container) return;
            if (!events || events.length === 0) {
                container.innerHTML = '<tr><td colspan="6" class="diag-empty">No security challenges recorded yet.</td></tr>';
                return;
            }

            const badgeClasses = {
                detected: "diag-type-detected",
                service_request: "diag-type-request",
                service_response: "diag-type-response",
                website_confirmed: "diag-type-verified",
                manual_required: "diag-type-manual",
            };

            const typeLabels = {
                detected: "Detected",
                service_request: "API Request",
                service_response: "API Response",
                website_confirmed: "Website Verified",
                manual_required: "Manual Required",
            };

            container.innerHTML = events.slice(-30).reverse().map(evt => {
                const time = escapeHtml(evt.timestamp || "");
                const worker = `Worker ${escapeHtml(String(evt.worker_id || 1))}`;
                const domain = escapeHtml(evt.domain || "unknown");
                const typeKey = evt.event_type || "detected";
                const typeBadge = `<span class="diag-type-badge ${badgeClasses[typeKey] || "diag-type-detected"}">${escapeHtml(typeLabels[typeKey] || typeKey)}</span>`;
                const status = escapeHtml(evt.status || "OK");
                const corrId = `<span class="diag-corr-id">${escapeHtml(evt.correlation_id || "")}</span>`;

                return `<tr>
                    <td>${time}</td>
                    <td><strong>${worker}</strong></td>
                    <td>${domain}</td>
                    <td>${typeBadge}</td>
                    <td>${status}</td>
                    <td>${corrId}</td>
                </tr>`;
            }).join("");
        }

        function cancelTrueCaptchaTimer(ui, chId) {
            if (!chId || !ui?._trueCaptchaTimers) return;
            const entry = ui._trueCaptchaTimers.get(chId);
            if (entry) {
                if (entry.timeoutId) clearTimeout(entry.timeoutId);
                if (entry.intervalId) clearInterval(entry.intervalId);
                ui._trueCaptchaTimers.delete(chId);
                if (ui._trueCaptchaAttempted) {
                    ui._trueCaptchaAttempted.add(chId);
                }
            }
        }

        async function recognizeAndSubmitTrueCaptcha(ui, chId) {
            if (!ui?.manualCaptchaCards || !chId) return;
            const getLiveElements = () => {
                const card = ui.manualCaptchaCards.querySelector(`.manual-captcha-card[data-challenge-id="${chId}"]`);
                return {
                    card,
                    input: card?.querySelector(".mch-code-input"),
                    submitBtn: card?.querySelector(".btn-submit-captcha-code"),
                    feedbackEl: card?.querySelector(".mch-feedback-msg"),
                };
            };
            const initial = getLiveElements();
            if (!initial.card || !initial.input || !initial.submitBtn || initial.submitBtn.disabled) return;

            if (initial.feedbackEl) {
                initial.feedbackEl.style.display = "block";
                initial.feedbackEl.className = "mch-feedback-msg info";
                initial.feedbackEl.textContent = "TrueCaptcha erkennt den Code...";
            }

            try {
                const resp = await fetch("/api/inline/auto-jobs/challenges/solve-truecaptcha", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ challenge_id: chId }),
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok || !data.success || !data.solution) {
                    throw new Error(data.message || "TrueCaptcha konnte keinen Code erkennen.");
                }

                const solution = String(data.solution).trim();
                if (!ui._captchaInputValues) ui._captchaInputValues = new Map();
                ui._captchaInputValues.set(chId, solution);

                // Write the recognized code immediately into the input field
                let live = getLiveElements();
                if (live.input) {
                    live.input.value = solution;
                    live.input.setAttribute("value", solution);
                    live.input.dispatchEvent(new Event("input", { bubbles: true }));
                    live.input.dispatchEvent(new Event("change", { bubbles: true }));
                }

                if (live.feedbackEl) {
                    live.feedbackEl.style.display = "block";
                    live.feedbackEl.className = "mch-feedback-msg info";
                    live.feedbackEl.textContent = `Code erkannt: ${solution}. Bestätige...`;
                }

                // Keep the recognized value visible briefly before auto-submitting
                await new Promise(resolve => setTimeout(resolve, 500));

                live = getLiveElements();
                if (!live.input || !live.submitBtn || live.submitBtn.disabled) return;
                live.input.value = solution;
                live.submitBtn.click();
            } catch (error) {
                const retryCount = (ui._trueCaptchaRetries && ui._trueCaptchaRetries.get(chId)) || 0;
                if (retryCount < 1) {
                    if (!ui._trueCaptchaRetries) ui._trueCaptchaRetries = new Map();
                    ui._trueCaptchaRetries.set(chId, 1);
                    const live = getLiveElements();
                    if (live.feedbackEl) {
                        live.feedbackEl.style.display = "block";
                        live.feedbackEl.className = "mch-feedback-msg info";
                        live.feedbackEl.textContent = "Erkennung fehlgeschlagen. Lade neues Bild für einen erneuten Versuch...";
                    }
                    try {
                        const rResp = await fetch("/api/inline/auto-jobs/challenges/refresh-image", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ challenge_id: chId }),
                        });
                        const rData = await rResp.json().catch(() => ({}));
                        if (rResp.ok && rData.success && rData.captcha_image_base64) {
                            const imgBox = live.card?.querySelector(".mch-img-box");
                            if (imgBox) {
                                imgBox.innerHTML = `<img src="${rData.captcha_image_base64}" alt="CAPTCHA Sicherheits-Code" class="mch-captcha-img" />`;
                            }
                            await new Promise(r => setTimeout(r, 1000));
                            return recognizeAndSubmitTrueCaptcha(ui, chId);
                        }
                    } catch (_) {}
                }
                const live = getLiveElements();
                if (live.feedbackEl) {
                    live.feedbackEl.style.display = "block";
                    live.feedbackEl.className = "mch-feedback-msg error";
                    live.feedbackEl.textContent = error?.message || "TrueCaptcha ist momentan nicht erreichbar.";
                }
            }
        }

        function renderManualCaptchaChallenges(ui, challenges, trueCaptchaConfigured = false) {
            if (!ui || !ui.manualCaptchaSection || !ui.manualCaptchaCards) return;
            const active = Array.isArray(challenges) ? challenges.filter(c => c && (c.status === "pending" || c.status === "failed")) : [];
            if (!ui._trueCaptchaTimers) {
                ui._trueCaptchaTimers = new Map();
            }
            if (!ui._trueCaptchaAttempted) {
                ui._trueCaptchaAttempted = new Set();
            }
            if (!ui._trueCaptchaRetries) {
                ui._trueCaptchaRetries = new Map();
            }
            if (!ui._captchaInputValues) {
                ui._captchaInputValues = new Map();
            }

            if (active.length === 0) {
                for (const [_, entry] of ui._trueCaptchaTimers.entries()) {
                    if (entry.timeoutId) clearTimeout(entry.timeoutId);
                    if (entry.intervalId) clearInterval(entry.intervalId);
                }
                ui._trueCaptchaTimers.clear();
                ui._trueCaptchaAttempted.clear();
                ui._trueCaptchaRetries.clear();
                ui._captchaInputValues.clear();
                ui.manualCaptchaSection.style.display = "none";
                ui.manualCaptchaCards.innerHTML = "";
                return;
            }

            ui.manualCaptchaSection.style.display = "block";
            if (ui.manualCaptchaBadge) {
                ui.manualCaptchaBadge.textContent = `${active.length} ${active.length === 1 ? "Prüfung aktiv" : "Prüfungen aktiv"}`;
            }

            // Clean up timers and attempt records for challenges that are no longer active
            const activeIds = new Set(active.map(c => c.challenge_id));
            for (const [chId, entry] of ui._trueCaptchaTimers.entries()) {
                if (!activeIds.has(chId)) {
                    if (entry.timeoutId) clearTimeout(entry.timeoutId);
                    if (entry.intervalId) clearInterval(entry.intervalId);
                    ui._trueCaptchaTimers.delete(chId);
                }
            }
            for (const chId of ui._trueCaptchaAttempted) {
                if (!activeIds.has(chId)) {
                    ui._trueCaptchaAttempted.delete(chId);
                }
            }
            for (const chId of ui._trueCaptchaRetries.keys()) {
                if (!activeIds.has(chId)) {
                    ui._trueCaptchaRetries.delete(chId);
                }
            }

            // Schedule single 4-second automatic TrueCaptcha trigger if not yet attempted
            if (trueCaptchaConfigured) {
                active.forEach(ch => {
                    const chId = ch.challenge_id;
                    const isImageCaptcha = (ch.challenge_type === "image_text");
                    const hasImg = Boolean(ch.image_valid && ch.captcha_image_base64);
                    const attempts = Number(ch.attempts || 0);
                    const alreadyAttempted = ui._trueCaptchaAttempted.has(chId) || attempts > 0;

                    // Execute auto-trigger only ONCE per challenge - never repeat multiple times
                    if (chId && isImageCaptcha && hasImg && ch.status === "pending" && !alreadyAttempted && !ch.last_error && !ui._trueCaptchaTimers.has(chId)) {
                        const duration = 4000;

                        const triggerAuto = () => {
                            const entry = ui._trueCaptchaTimers?.get(chId);
                            if (!entry) return;
                            ui._trueCaptchaTimers.delete(chId);
                            ui._trueCaptchaAttempted.add(chId);
                            recognizeAndSubmitTrueCaptcha(ui, chId);
                        };

                        const timeoutId = setTimeout(triggerAuto, duration);
                        ui._trueCaptchaTimers.set(chId, { timeoutId });
                    }
                });
            }

            // Preserve input values and typing state across redraws
            ui.manualCaptchaCards.querySelectorAll("input.mch-code-input").forEach(inp => {
                const id = inp.getAttribute("data-challenge-id");
                if (id && inp.value) {
                    ui._captchaInputValues.set(id, inp.value);
                }
            });

            const activeInput = ui.manualCaptchaCards.querySelector("input.mch-code-input:focus");
            const activeChallengeId = activeInput ? activeInput.getAttribute("data-challenge-id") : null;
            const activeInputValue = activeInput ? activeInput.value : "";
            if (activeChallengeId && activeInputValue) {
                ui._captchaInputValues.set(activeChallengeId, activeInputValue);
            }

            ui.manualCaptchaCards.innerHTML = active.map(ch => {
                const chId = escapeHtml(ch.challenge_id || "");
                const workerId = escapeHtml(String(ch.worker_id || 1));
                const platform = escapeHtml(ch.platform || "Platform");
                const title = escapeHtml(ch.job_title || "Stellenangebot");
                const employer = escapeHtml(ch.employer || "Arbeitgeber");
                const type = ch.challenge_type || "unknown";
                const isImageCaptcha = type === "image_text";
                const isInteractive = !isImageCaptcha;
                const hasImg = Boolean(ch.image_valid && ch.captcha_image_base64);
                const imageError = escapeHtml(ch.status === "expired"
                    ? "This CAPTCHA expired. Request a fresh image from the authenticated session."
                    : (ch.image_error || "CAPTCHA image is missing or could not be loaded."));
                const typeLabels = {
                    image_text: "Sicherheits-Code",
                    recaptcha: "reCAPTCHA",
                    turnstile: "Cloudflare Turnstile",
                    login_required: "Login required",
                    unknown: "Unknown security challenge",
                };
                const typeLabel = typeLabels[type] || typeLabels.unknown;
                const lastErr = ch.last_error ? escapeHtml(ch.last_error) : "";
                const sourceUrl = escapeHtml(ch.source_url || "");
                const savedVal = escapeHtml((ui._captchaInputValues && ui._captchaInputValues.get(ch.challenge_id)) || ch.recognized_code || "");

                return `
                    <div class="manual-captcha-card ${isInteractive ? 'interactive-card' : ''}" data-challenge-id="${chId}">
                        <div class="mch-header">
                            <div class="mch-badges">
                                <span class="mch-worker-tag"><span class="mch-dot"></span>Worker ${workerId}</span>
                                <span class="mch-platform-tag">${platform}</span>
                                <span class="mch-type-tag ${isInteractive ? 'interactive' : 'image'}">
                                    ${escapeHtml(typeLabel)}
                                </span>
                            </div>
                            <span class="mch-created">${escapeHtml(ch.created_at ? new Date(ch.created_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'}) : '')}</span>
                        </div>

                        <div class="mch-job-meta">
                            <strong class="mch-job-title" title="${title}">${title}</strong>
                            <span class="mch-job-employer" title="${employer}">— ${employer}</span>
                        </div>

                        ${isInteractive ? `
                            <div class="mch-interactive-desc">
                                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                                <span>Diese Seite verlangt eine interaktive Sicherheitsüberprüfung (z.B. reCAPTCHA oder Cloudflare). Öffnen Sie die Seite im Browser und bestätigen Sie die Prüfung, um diesen Worker fortzusetzen.</span>
                            </div>
                            ${hasImg ? `
                                <div class="mch-screenshot-preview">
                                    <img src="${ch.captcha_image_base64}" alt="Sicherheitsabfrage" class="mch-screenshot-img" />
                                </div>
                            ` : ''}
                            <div class="mch-actions-row">
                                <button type="button" class="mch-btn mch-btn-browser btn-open-captcha-browser" data-challenge-id="${chId}" data-url="${sourceUrl}" title="Zielseite im Standardbrowser öffnen">
                                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                                    <span>Im Browser öffnen</span>
                                </button>
                                <button type="button" class="mch-btn mch-btn-verify btn-verify-interactive-captcha" data-challenge-id="${chId}" title="Überprüfung auf der Webseite bestätigen">
                                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="20 6 9 17 4 12"></polyline></svg>
                                    <span>Überprüfung abgeschlossen</span>
                                </button>
                                <button type="button" class="mch-btn mch-btn-skip btn-skip-captcha" data-challenge-id="${chId}" title="Als Manuell markieren und mit nächster Stelle fortfahren">
                                    <span>Überspringen</span>
                                </button>
                            </div>
                        ` : `
                            <div class="mch-image-area">
                                <div class="mch-img-box-wrapper">
                                    <div class="mch-img-box" data-challenge-id="${chId}" title="Klicken zum Vergrößern">
                                        ${hasImg ? `
                                            <img src="${ch.captcha_image_base64}" alt="CAPTCHA Sicherheits-Code" class="mch-captcha-img" />
                                        ` : `
                                            <div class="mch-img-fallback mch-img-error" role="alert">
                                                <span>${imageError}</span>
                                            </div>
                                        `}
                                    </div>
                                    <button type="button" class="mch-btn-icon btn-refresh-captcha-img" data-challenge-id="${chId}" title="Bild jetzt neu laden">
                                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M23 4v6h-6"></path><path d="M1 20v-6h6"></path><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>
                                    </button>
                                </div>
                                ${hasImg ? `<div class="mch-input-group">
                                    <input type="text" class="mch-code-input" placeholder="CAPTCHA-Code eingeben..." maxlength="64" inputmode="text" autocomplete="off" autocapitalize="none" spellcheck="false" data-challenge-id="${chId}" value="${savedVal}" />
                                    <button type="button" class="mch-btn mch-btn-primary btn-submit-captcha-code" data-challenge-id="${chId}">
                                        <span>Bestätigen</span>
                                    </button>
                                    <button type="button" class="mch-btn mch-btn-browser btn-open-captcha-browser" data-challenge-id="${chId}" data-url="${sourceUrl}" title="Zielseite im Browser öffnen, um den Code dort einzusehen">
                                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                                        <span>Im Browser öffnen</span>
                                    </button>
                                    <button type="button" class="mch-btn mch-btn-skip btn-skip-captcha" data-challenge-id="${chId}" title="Als Manuell markieren">
                                        <span>Überspringen</span>
                                    </button>
                                </div>` : `<div class="mch-actions-row">
                                    <button type="button" class="mch-btn mch-btn-browser btn-open-captcha-browser" data-challenge-id="${chId}" data-url="${sourceUrl}"><span>Originalseite öffnen</span></button>
                                    <button type="button" class="mch-btn mch-btn-skip btn-skip-captcha" data-challenge-id="${chId}"><span>Überspringen</span></button>
                                </div>`}
                            </div>
                        `}

                        ${lastErr ? `
                            <div class="mch-error-message">
                                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                                <span>${lastErr}</span>
                            </div>
                        ` : `
                            <div class="mch-feedback-msg" style="display:none;"></div>
                        `}
                    </div>
                `;
            }).join("");

            // Re-apply preserved values to DOM inputs
            ui.manualCaptchaCards.querySelectorAll("input.mch-code-input").forEach(inp => {
                const id = inp.getAttribute("data-challenge-id");
                const val = ui._captchaInputValues?.get(id);
                if (val && inp.value !== val) {
                    inp.value = val;
                }
            });

            if (activeChallengeId) {
                const inputToRestore = ui.manualCaptchaCards.querySelector(`input.mch-code-input[data-challenge-id="${activeChallengeId}"]`);
                if (inputToRestore) {
                    inputToRestore.focus();
                }
            }

        }

        function setupManualCaptchaListeners(ui) {
            if (!ui || !ui.manualCaptchaCards) return;
            ui.manualCaptchaCards.addEventListener("click", async (e) => {
                const target = e.target;

                // 1. Submit Code
                const submitBtn = target.closest(".btn-submit-captcha-code");
                if (submitBtn) {
                    const card = submitBtn.closest(".manual-captcha-card");
                    const chId = submitBtn.dataset.challengeId || card?.getAttribute("data-challenge-id");
                    cancelTrueCaptchaTimer(ui, chId);
                    const input = card?.querySelector(".mch-code-input");
                    const solution = (input?.value || "").trim();
                    const feedbackEl = card?.querySelector(".mch-feedback-msg");
                    const errEl = card?.querySelector(".mch-error-message");

                    if (!solution) {
                        if (input) {
                            input.focus();
                            input.classList.add("input-error");
                            setTimeout(() => input.classList.remove("input-error"), 2000);
                        }
                        return;
                    }

                    submitBtn.disabled = true;
                    const origHtml = submitBtn.innerHTML;
                    submitBtn.innerHTML = `<span>Prüfe...</span>`;
                    if (feedbackEl) {
                        feedbackEl.style.display = "block";
                        feedbackEl.className = "mch-feedback-msg info";
                        feedbackEl.textContent = "Code wird an die Original-Webseite übermittelt...";
                    }

                    try {
                        const resp = await fetch("/api/inline/auto-jobs/challenges/solve", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ challenge_id: chId, solution_text: solution }),
                        });
                        const resData = await resp.json().catch(() => ({}));
                        if (resp.ok && resData.success) {
                            if (feedbackEl) {
                                feedbackEl.className = "mch-feedback-msg success";
                                feedbackEl.textContent = "Website verifiziert! Worker setzt Extraktion fort...";
                            }
                            setTimeout(() => {
                                pollAutoProgress(ui);
                            }, 1000);
                        } else {
                            const retryCount = (ui._trueCaptchaRetries && ui._trueCaptchaRetries.get(chId)) || 0;
                            const isTrueCaptcha = Boolean(ui._trueCaptchaAttempted && ui._trueCaptchaAttempted.has(chId));

                            if (isTrueCaptcha && retryCount < 1 && resData.can_retry !== false) {
                                if (!ui._trueCaptchaRetries) ui._trueCaptchaRetries = new Map();
                                ui._trueCaptchaRetries.set(chId, 1);

                                // If server rotated the image, update DOM immediately
                                if (resData.challenge && resData.challenge.captcha_image_base64) {
                                    const imgBox = card?.querySelector(".mch-img-box");
                                    if (imgBox) {
                                        imgBox.innerHTML = `<img src="${resData.challenge.captcha_image_base64}" alt="CAPTCHA Sicherheits-Code" class="mch-captcha-img" />`;
                                    }
                                }

                                if (feedbackEl) {
                                    feedbackEl.style.display = "block";
                                    feedbackEl.className = "mch-feedback-msg info";
                                    feedbackEl.textContent = "Code von Website abgelehnt. TrueCaptcha versucht es einmal erneut mit dem neuen Bild...";
                                }
                                if (errEl) errEl.style.display = "none";

                                if (input) {
                                    input.value = "";
                                    ui._captchaInputValues?.delete(chId);
                                }

                                setTimeout(() => {
                                    recognizeAndSubmitTrueCaptcha(ui, chId);
                                }, 1000);
                                return;
                            }

                            if (errEl) {
                                errEl.style.display = "flex";
                                const span = errEl.querySelector("span");
                                if (span) span.textContent = resData.message || "Code von Website abgelehnt.";
                            } else if (feedbackEl) {
                                feedbackEl.className = "mch-feedback-msg error";
                                feedbackEl.textContent = resData.message || "Code von Website abgelehnt. Erneuter Versuch möglich.";
                            }
                            if (input) {
                                input.value = solution;
                                input.focus();
                                input.select();
                            }
                        }
                    } catch (err) {
                        if (feedbackEl) {
                            feedbackEl.className = "mch-feedback-msg error";
                            feedbackEl.textContent = "Netzwerkfehler beim Senden des Codes.";
                        }
                    } finally {
                        submitBtn.disabled = false;
                        submitBtn.innerHTML = origHtml;
                    }
                    return;
                }

                // 2. Open in Browser
                const browserBtn = target.closest(".btn-open-captcha-browser");
                if (browserBtn) {
                    const chId = browserBtn.dataset.challengeId;
                    cancelTrueCaptchaTimer(ui, chId);
                    const sourceUrl = browserBtn.dataset.url;
                    if (sourceUrl) {
                        window.open(sourceUrl, "_blank", "noopener,noreferrer");
                    }
                    try {
                        await fetch("/api/inline/auto-jobs/challenges/open-browser", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ challenge_id: chId }),
                        });
                    } catch (_) {}
                    return;
                }

                // 2b. Refresh Captcha Image
                const refreshBtn = target.closest(".btn-refresh-captcha-img");
                if (refreshBtn) {
                    const card = refreshBtn.closest(".manual-captcha-card");
                    const chId = refreshBtn.dataset.challengeId || card?.getAttribute("data-challenge-id");
                    cancelTrueCaptchaTimer(ui, chId);
                    if (chId) {
                        ui._trueCaptchaRetries?.delete(chId);
                        ui._trueCaptchaAttempted?.delete(chId);
                    }
                    const imgBox = card?.querySelector(".mch-img-box");
                    const origSvg = refreshBtn.innerHTML;
                    refreshBtn.disabled = true;
                    refreshBtn.innerHTML = `<span class="btn-spinner" style="width:12px; height:12px; border-top-color:#2563eb;"></span>`;

                    try {
                        const resp = await fetch("/api/inline/auto-jobs/challenges/refresh-image", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ challenge_id: chId }),
                        });
                        const data = await resp.json().catch(() => ({}));
                        if (resp.ok && data.success && data.captcha_image_base64 && imgBox) {
                            imgBox.innerHTML = `<img src="${data.captcha_image_base64}" alt="CAPTCHA Sicherheits-Code" class="mch-captcha-img" />`;
                            await pollAutoProgress(ui);
                        } else if (imgBox) {
                            imgBox.innerHTML = `<div class="mch-img-fallback mch-img-error" role="alert"><span>${escapeHtml(data.message || "CAPTCHA image is unavailable or expired.")}</span></div>`;
                        }
                    } catch (_) {
                        if (imgBox) imgBox.innerHTML = `<div class="mch-img-fallback mch-img-error" role="alert"><span>CAPTCHA image refresh failed.</span></div>`;
                    } finally {
                        refreshBtn.disabled = false;
                        refreshBtn.innerHTML = origSvg;
                    }
                    return;
                }

                // 2c. Zoom / Enlarge Captcha Image on Click
                const imgClick = target.closest(".mch-captcha-img");
                if (imgClick) {
                    imgClick.classList.toggle("zoomed");
                    return;
                }

                // 3. Verify Interactive
                const verifyBtn = target.closest(".btn-verify-interactive-captcha");
                if (verifyBtn) {
                    const card = verifyBtn.closest(".manual-captcha-card");
                    const chId = verifyBtn.dataset.challengeId || card?.getAttribute("data-challenge-id");
                    cancelTrueCaptchaTimer(ui, chId);
                    const feedbackEl = card?.querySelector(".mch-feedback-msg");
                    const errEl = card?.querySelector(".mch-error-message");

                    verifyBtn.disabled = true;
                    const origHtml = verifyBtn.innerHTML;
                    verifyBtn.innerHTML = `<span>Prüfe Status...</span>`;
                    try {
                        const resp = await fetch("/api/inline/auto-jobs/challenges/verify-interactive", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ challenge_id: chId }),
                        });
                        const resData = await resp.json().catch(() => ({}));
                        if (resp.ok && resData.success) {
                            if (feedbackEl) {
                                feedbackEl.style.display = "block";
                                feedbackEl.className = "mch-feedback-msg success";
                                feedbackEl.textContent = "Website verifiziert! Worker setzt Extraktion fort...";
                            }
                            setTimeout(() => {
                                pollAutoProgress(ui);
                            }, 1000);
                        } else {
                            if (errEl) {
                                errEl.style.display = "flex";
                                const span = errEl.querySelector("span");
                                if (span) span.textContent = resData.message || "Seite ist weiterhin blockiert.";
                            } else if (feedbackEl) {
                                feedbackEl.style.display = "block";
                                feedbackEl.className = "mch-feedback-msg error";
                                feedbackEl.textContent = resData.message || "Seite ist weiterhin blockiert. Bitte führen Sie die Prüfung im Browser zu Ende.";
                            }
                        }
                    } catch (_) {
                    } finally {
                        verifyBtn.disabled = false;
                        verifyBtn.innerHTML = origHtml;
                    }
                    return;
                }

                // 4. Skip / Mark Manual
                const skipBtn = target.closest(".btn-skip-captcha");
                if (skipBtn) {
                    const card = skipBtn.closest(".manual-captcha-card");
                    const chId = skipBtn.dataset.challengeId || card?.getAttribute("data-challenge-id");
                    cancelTrueCaptchaTimer(ui, chId);
                    skipBtn.disabled = true;
                    try {
                        await fetch("/api/inline/auto-jobs/challenges/skip", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ challenge_id: chId }),
                        });
                        await pollAutoProgress(ui);
                    } catch (_) {}
                    return;
                }
            });

            // Cancel countdown if user starts typing code manually
            ui.manualCaptchaCards.addEventListener("input", (e) => {
                if (e.target && e.target.classList.contains("mch-code-input")) {
                    const card = e.target.closest(".manual-captcha-card");
                    const chId = e.target.dataset.challengeId || card?.getAttribute("data-challenge-id");
                    if (chId) {
                        if (!ui._captchaInputValues) ui._captchaInputValues = new Map();
                        ui._captchaInputValues.set(chId, e.target.value);
                    }
                    cancelTrueCaptchaTimer(ui, chId);
                }
            });
            ui.manualCaptchaCards.addEventListener("focusin", (e) => {
                if (e.target && e.target.classList.contains("mch-code-input")) {
                    const card = e.target.closest(".manual-captcha-card");
                    const chId = e.target.dataset.challengeId || card?.getAttribute("data-challenge-id");
                    cancelTrueCaptchaTimer(ui, chId);
                }
            });

            // Enter key submits code
            ui.manualCaptchaCards.addEventListener("keydown", (e) => {
                if (e.key === "Enter" && e.target.classList.contains("mch-code-input")) {
                    e.preventDefault();
                    const card = e.target.closest(".manual-captcha-card");
                    const btn = card?.querySelector(".btn-submit-captcha-code");
                    if (btn) btn.click();
                }
            });
        }

        function renderAutoProgress(ui, data) {
            ui.progressPanel.classList.add("visible");

            const total = Number(data.total_jobs || 0);
            const processed = Number(data.current_index || 0);
            const pending = Math.max(0, total - processed);

            // Primary Metrics
            if (ui.processedEl) ui.processedEl.textContent = String(processed);
            if (ui.totalEl) ui.totalEl.textContent = String(total);
            if (ui.emailsEl) ui.emailsEl.textContent = String(data.emails_found || 0);
            if (ui.formsEl) ui.formsEl.textContent = String(data.forms_found || 0);
            if (ui.captchaEl) ui.captchaEl.textContent = String(data.captchas_solved || 0);
            const cm = data.captcha_metrics || {};
            if (ui.captchaUniqueEl) ui.captchaUniqueEl.textContent = String(cm.unique_challenges || 0);
            if (ui.captchaRequestsEl) ui.captchaRequestsEl.textContent = String(cm.service_requests || 0);
            if (ui.captchaVerifiedEl) ui.captchaVerifiedEl.textContent = String(cm.website_verifications_confirmed || 0);
            if (ui.captchaManualEl) ui.captchaManualEl.textContent = String(cm.manual_verification_required || 0);
            const eventCount = (cm.recent_events && cm.recent_events.length) || 0;
            if (ui.captchaDiagPill) ui.captchaDiagPill.textContent = `${eventCount} events`;
            if (ui.captchaDiagTbody) {
                renderCaptchaDiagnostics(ui.captchaDiagTbody, cm.recent_events);
            }
            renderManualCaptchaChallenges(ui, data.active_challenges, Boolean(data.truecaptcha_configured));
            if (ui.failedEl) ui.failedEl.textContent = String(data.failed || 0);

            const pct = window.SPAUtils ? window.SPAUtils.clampPercent(data.percentage || 0) : Math.min(100, Math.max(0, data.percentage || 0));
            const roundedPct = Math.round(pct);
            if (ui.progressFill) {
                ui.progressFill.style.width = `${pct}%`;
                ui.progressFill.textContent = `${roundedPct}%`;
            }
            if (ui.percentNumEl) {
                ui.percentNumEl.textContent = `${roundedPct}%`;
            }

            // Secondary Metrics
            if (ui.recruitmentEmailsEl) ui.recruitmentEmailsEl.textContent = String(data.recruitment_emails || 0);
            if (ui.externalLinksEl) ui.externalLinksEl.textContent = String(data.external_links || 0);
            if (ui.fastPathEl) ui.fastPathEl.textContent = String(data.fast_path_hits || 0);
            if (ui.seleniumFallbacksEl) ui.seleniumFallbacksEl.textContent = String(data.selenium_fallbacks || 0);
            if (ui.rateLimitedEl) ui.rateLimitedEl.textContent = String(data.rate_limited_count || 0);
            if (ui.pendingEl) ui.pendingEl.textContent = String(pending);

            const avgTime = Number(data.avg_time_per_job || 0);
            if (ui.avgTimeEl) {
                ui.avgTimeEl.textContent = avgTime > 0 ? `${avgTime.toFixed(1)}s` : "--";
            }
            if (ui.speedEl) {
                ui.speedEl.textContent = avgTime > 0 ? `${avgTime.toFixed(1)}s/job` : "-- s/job";
            }

            // Status Badge & Completion calculation
            const isCompleted = !data.is_running && !data.paused && !data.stop_requested && processed >= total && total > 0 && pending === 0;

            // Dynamic Throughput & ETA
            if (ui.etaEl) {
                const remainingSec = Number(data.estimated_remaining_seconds || 0);
                if (data.stalled) {
                    ui.etaEl.textContent = "Stalled";
                } else if (data.paused) {
                    ui.etaEl.textContent = "Pausiert";
                } else if (!data.is_running) {
                    ui.etaEl.textContent = isCompleted ? "Done" : (data.stop_requested ? "Gestoppt" : "ETA: --");
                } else if (remainingSec <= 0) {
                    ui.etaEl.textContent = "ETA: calculating...";
                } else if (remainingSec < 60) {
                    ui.etaEl.textContent = `ETA: ~${Math.round(remainingSec)}s`;
                } else {
                    const mins = Math.floor(remainingSec / 60);
                    const secs = Math.round(remainingSec % 60);
                    ui.etaEl.textContent = `ETA: ~${mins}m ${secs}s`;
                }
            }

            // Status Badge styling
            let badgeClass = "status-idle";
            let badgeText = "Idle";
            if (isCompleted) {
                badgeClass = "status-completed";
                badgeText = "Completed";
            } else if (data.stop_requested) {
                badgeClass = "status-stopping";
                badgeText = "Stopping...";
            } else if (data.paused) {
                badgeClass = "status-paused";
                badgeText = data.last_error ? "Paused - Error" : "Paused";
            } else if (data.is_running) {
                if (Number(data.rate_limited_count || 0) > 0 && data.status_label === "Rate Limited") {
                    badgeClass = "status-rate-limited";
                    badgeText = "Rate Limited (Cooling down)";
                } else {
                    badgeClass = "status-running";
                    badgeText = "Running";
                }
            } else if (Number(data.failed || 0) > 0 && processed === 0) {
                badgeClass = "status-failed";
                badgeText = "Failed";
            }

            if (ui.statusBadgeEl) {
                ui.statusBadgeEl.className = `dash-badge ${badgeClass}`;
                ui.statusBadgeEl.textContent = badgeText;
            }

            // Active Workers Badge
            const activeWorkers = Number(data.active_workers || (data.is_running ? 4 : 0));
            if (ui.activeWorkersBadgeEl) {
                if (data.is_running) {
                    ui.activeWorkersBadgeEl.className = "dash-badge workers-active";
                    ui.activeWorkersBadgeEl.innerHTML = `<span class="pulse-dot"></span> <span class="workers-text">${activeWorkers} Active Workers</span>`;
                } else {
                    ui.activeWorkersBadgeEl.className = "dash-badge workers-idle";
                    ui.activeWorkersBadgeEl.innerHTML = `<span class="pulse-dot"></span> <span class="workers-text">Workers Idle</span>`;
                }
            }

            // Error display
            if (data.last_error) {
                ui.progressError.textContent = data.last_error;
                ui.progressError.style.display = "block";
            } else {
                ui.progressError.textContent = "";
                ui.progressError.style.display = "none";
            }

            // Status text
            let status = "Idle";
            if (isCompleted) {
                status = `Extraction completed (${processed}/${total} processed)`;
            } else if (data.stop_requested) {
                status = "Stopping extraction and compiling results...";
            } else if (data.paused) {
                status = data.last_error ? `Paused - Error: ${data.last_error}` : "Paused";
            } else if (data.is_running) {
                status = `Processing position ${processed}/${total}...`;
            }
            if (ui.progressStatus) {
                ui.progressStatus.textContent = status;
            }

            // Workers Grid
            if (ui.workersGridEl) {
                renderWorkers(ui.workersGridEl, data.workers, data.is_running);
            }

            // Activity Feed
            if (ui.activityFeedListEl) {
                renderActivityFeed(ui.activityFeedListEl, ui.feedCounterEl, data.activity_feed);
            }

            // Stop button: visible while actively running, paused, or stopping
            if (ui.stopBtn) {
                if (data.stop_requested) {
                    ui.stopBtn.disabled = true;
                    ui.stopBtn.innerHTML = `<span class="btn-spinner"></span><span>Stoppe...</span>`;
                    ui.stopBtn.style.display = "inline-flex";
                } else {
                    ui.stopBtn.disabled = false;
                    ui.stopBtn.style.display = (data.is_running || data.paused) ? "inline-flex" : "none";
                }
            }

            // Pause button: ONLY visible when actively running
            if (ui.pauseBtn) {
                ui.pauseBtn.style.display = (data.is_running && !data.paused) ? "inline-flex" : "none";
            }

            // Continue button: ONLY visible when paused
            if (ui.continueBtn) {
                ui.continueBtn.style.display = data.paused ? "inline-flex" : "none";
            }

            // Download button: visible when extraction is finished, stopped, or when idle with collected results
            const canDownload = Boolean(
                isCompleted ||
                data.stop_requested ||
                (!data.is_running && processed > 0)
            );
            if (ui.downloadBtn) {
                ui.downloadBtn.style.display = (canDownload && !data.is_running) ? "inline-flex" : "none";
            }

            // Go to Cover Letters button: visible when completed or stopped with collected results
            const canGoToAnschreiben = Boolean(!data.is_running && !data.paused && processed > 0);
            if (ui.anschreibenBtn) {
                ui.anschreibenBtn.style.display = canGoToAnschreiben ? "inline-flex" : "none";
            }

            // Keep Auto-Extract Button in sync with live extraction state
            if (ui.autoBtn) {
                if (data.is_running) {
                    ui.autoBtn.disabled = true;
                    ui.autoBtn.innerHTML = `<span class="btn-spinner"></span><span>Extrahiere (${processed}/${total})...</span>`;
                } else if (data.paused) {
                    ui.autoBtn.disabled = false;
                    ui.autoBtn.innerHTML = `<span>▶ Fortsetzen (${processed}/${total})</span>`;
                } else {
                    setAutoBtnIdle(ui.autoBtn);
                }
            }
        }

        function setAutoBtnIdle(btn) {
            if (!btn) return;
            btn.disabled = false;
            btn.innerHTML = `<svg class="btn-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg><span>⚡ Auto-Extract Contacts</span>`;
        }

        function setAutoBtnLoading(btn, text = "Starting...") {
            if (!btn) return;
            btn.disabled = true;
            btn.innerHTML = `<span class="btn-spinner"></span><span>${escapeHtml(text)}</span>`;
        }

        async function pollAutoProgress(ui) {
            if (!ui.autoJobId) {
                return;
            }

            try {
                const response = await fetch(`/api/inline/auto-jobs/status/${encodeURIComponent(ui.autoJobId)}`);
                const data = await response.json();

                if (!response.ok || !data.success || !data.job) {
                    throw new Error(data.message || "Status der Auto-Extraktion konnte nicht geladen werden");
                }

                // Isolation check: if this job belongs to a different search run, decouple it from current search UI
                if (data.job.search_run_id && ui.currentSearchRunId && data.job.search_run_id !== ui.currentSearchRunId) {
                    if (ui.pollTimer) {
                        clearInterval(ui.pollTimer);
                        ui.pollTimer = null;
                    }
                    ui.autoJobId = null;
                    if (ui.progressPanel) ui.progressPanel.classList.remove("visible");
                    setAutoBtnIdle(ui.autoBtn);
                    loadPreviousTasks(ui);
                    return;
                }

                ui.pollFailures = 0;
                renderAutoProgress(ui, data.job);

                if (!data.job.is_running && !data.job.paused) {
                    if (ui.pollTimer) {
                        clearInterval(ui.pollTimer);
                        ui.pollTimer = null;
                    }
                    setAutoBtnIdle(ui.autoBtn);
                    loadPreviousTasks(ui);
                }
            } catch (error) {
                ui.pollFailures = (ui.pollFailures || 0) + 1;
                ui.progressError.textContent = error.message || "Statusfehler";
                ui.progressError.style.display = "block";
                if (ui.pollFailures >= 5) {
                    if (ui.pollTimer) {
                        clearInterval(ui.pollTimer);
                        ui.pollTimer = null;
                    }
                    setAutoBtnIdle(ui.autoBtn);
                }
            }
        }

        async function startAutoExtraction(ui) {
            if (!Array.isArray(ui.lastJobs) || !ui.lastJobs.length) {
                showError(ui, "Please perform a search first to discover job opportunities.");
                return;
            }

            setAutoBtnLoading(ui.autoBtn, "Starte...");

            try {
                const kw = (ui.keywordEl && ui.keywordEl.value) ? ui.keywordEl.value.trim() : "";
                const loc = (ui.locationEl && ui.locationEl.value) ? ui.locationEl.value.trim() : "";
                const pub = (ui.publishedSinceEl && ui.publishedSinceEl.value) ? ui.publishedSinceEl.value : "all";

                const response = await fetch("/api/inline/auto-jobs/start", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        jobs: ui.lastJobs,
                        keyword: kw,
                        location: loc,
                        published_since: pub,
                        search_run_id: ui.currentSearchRunId || "",
                    }),
                });
                const data = await response.json();

                if (!response.ok || !data.success) {
                    throw new Error(data.message || "Auto-Extraktion konnte nicht gestartet werden");
                }

                ui.autoJobId = data.job_id || "";
                if (!ui.autoJobId) {
                    throw new Error("Keine Job-ID erhalten");
                }
                if (data.search_run_id) {
                    ui.currentSearchRunId = data.search_run_id;
                }
                try {
                    localStorage.setItem("jobscout_active_auto_job_id_" + (ui.currentSearchRunId || "default"), ui.autoJobId);
                } catch (_) {}

                ui.progressPanel.classList.add("visible");
                if (typeof ui.progressPanel.scrollIntoView === "function") {
                    ui.progressPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
                }

                if (ui.pollTimer) {
                    clearInterval(ui.pollTimer);
                }
                ui.pollFailures = 0;
                ui.pollTimer = setInterval(() => {
                    pollAutoProgress(ui);
                }, 1500);
                await pollAutoProgress(ui);
                loadPreviousTasks(ui);
            } catch (error) {
                setAutoBtnIdle(ui.autoBtn);
                showError(ui, error.message || "Auto-Extraktion konnte nicht gestartet werden");
            }
        }

        async function pauseAutoExtraction(ui) {
            let jobId = ui.autoJobId;
            if (!jobId) return;

            try {
                const response = await fetch(`/api/inline/auto-jobs/pause/${encodeURIComponent(jobId)}`, { method: "POST" });
                const data = await response.json().catch(() => ({}));
                if (!response.ok || !data.success) {
                    throw new Error(data.message || "Pausieren fehlgeschlagen");
                }
                await pollAutoProgress(ui);
                loadPreviousTasks(ui);
            } catch (err) {
                if (ui.progressError) {
                    ui.progressError.textContent = err.message || "Pausieren fehlgeschlagen";
                    ui.progressError.style.display = "block";
                }
            }
        }

        async function continueAutoExtraction(ui) {
            if (!ui.autoJobId) {
                ui.progressError.textContent = "Kein aktiver Job auf dieser Seite.";
                ui.progressError.style.display = "block";
                return;
            }

            try {
                const response = await fetch(`/api/inline/auto-jobs/continue/${encodeURIComponent(ui.autoJobId)}`, { method: "POST" });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.message || "Fortsetzen fehlgeschlagen");
                }

                if (ui.pollTimer) {
                    clearInterval(ui.pollTimer);
                }
                ui.pollTimer = setInterval(() => {
                    pollAutoProgress(ui);
                }, 1500);
                await pollAutoProgress(ui);
                loadPreviousTasks(ui);
            } catch (error) {
                ui.progressError.textContent = error.message || "Fortsetzen fehlgeschlagen";
                ui.progressError.style.display = "block";
            }
        }

        async function loadPreviousTasks(ui) {
            if (!ui || !ui.previousTasksList) return;
            try {
                const resp = await fetch("/api/inline/auto-jobs/history");
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok || !data.success || !Array.isArray(data.tasks)) return;

                const tasks = data.tasks;
                if (ui.previousTasksCount) {
                    ui.previousTasksCount.textContent = String(tasks.length);
                }

                if (tasks.length === 0) {
                    if (ui.previousTasksSection) ui.previousTasksSection.style.display = "none";
                    return;
                }

                if (ui.previousTasksSection) {
                    ui.previousTasksSection.style.display = "block";
                }

                ui.previousTasksList.innerHTML = tasks.map(task => {
                    const isCurrentRun = Boolean(task.search_run_id && task.search_run_id === ui.currentSearchRunId);
                    const total = task.total_jobs || 0;
                    const proc = task.processed_jobs || 0;
                    const pct = total ? Math.min(100, Math.round((proc / total) * 100)) : 0;

                    let badgeClass = "status-idle";
                    let statusText = task.status_label || "Idle";
                    if (task.is_running) {
                        badgeClass = "status-running";
                        statusText = "Running";
                    } else if (task.paused) {
                        badgeClass = "status-warning";
                        statusText = "Paused";
                    } else if (task.stop_requested || String(statusText).toLowerCase() === "stopped") {
                        badgeClass = "status-stopped";
                        statusText = "Stopped";
                    } else if (proc >= total && total > 0) {
                        badgeClass = "status-completed";
                        statusText = "Completed";
                    }

                    const kw = escapeHtml(task.keyword || "Stellen-Suche");
                    const loc = task.location ? ` in ${escapeHtml(task.location)}` : " (Bundesweit)";
                    const runShort = escapeHtml(task.search_run_id ? task.search_run_id.replace(/^run_/, '').slice(0, 8) : task.job_id.slice(0, 8));

                    return `
                        <div class="previous-task-card ${isCurrentRun ? 'current-task-highlight' : ''}" data-job-id="${escapeHtml(task.job_id)}" data-run-id="${escapeHtml(task.search_run_id)}">
                            <div class="ptask-header-row">
                                <div class="ptask-title-wrap">
                                    <span class="ptask-job-title">${kw}${loc}</span>
                                    <span class="ptask-run-tag">Run #${runShort}</span>
                                    ${isCurrentRun ? '<span class="ptask-active-tag">Aktuelle Suche</span>' : ''}
                                </div>
                                <div class="ptask-status-wrap">
                                    <span class="dash-badge ${badgeClass}">${statusText}</span>
                                    <span class="ptask-progress-summary"><strong class="ptask-progress-pct">${pct}%</strong> (${proc}/${total})</span>
                                </div>
                            </div>

                            <div class="ptask-progress-track">
                                <div class="ptask-progress-bar ${badgeClass}" style="width: ${pct}%;"></div>
                            </div>

                            <div class="ptask-footer-row">
                                <div class="ptask-stats-group">
                                    <span class="ptask-stat-badge emails">
                                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>
                                        <strong>${task.emails_found || 0}</strong> E-Mails
                                    </span>
                                    <span class="ptask-stat-badge forms">
                                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>
                                        <strong>${task.forms_found || 0}</strong> Formulare
                                    </span>
                                </div>
                                <div class="ptask-action-group">
                                    <button type="button" class="ptask-action-btn ptask-btn-reopen btn-reopen-task" data-job-id="${escapeHtml(task.job_id)}" data-run-id="${escapeHtml(task.search_run_id)}" title="Öffne das Live-Dashboard dieser Extraktion">
                                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                                        <span>Dashboard öffnen</span>
                                    </button>
                                    ${task.is_running ? `
                                        <button type="button" class="ptask-action-btn ptask-btn-pause btn-pause-task" data-job-id="${escapeHtml(task.job_id)}" title="Extraktion pausieren">
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>
                                            <span>Pause</span>
                                        </button>
                                        <button type="button" class="ptask-action-btn ptask-btn-stop btn-stop-task" data-job-id="${escapeHtml(task.job_id)}" title="Extraktion stoppen">
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="2"></rect></svg>
                                            <span>Stopp</span>
                                        </button>
                                    ` : task.paused ? `
                                        <button type="button" class="ptask-action-btn ptask-btn-resume btn-resume-task" data-job-id="${escapeHtml(task.job_id)}" title="Extraktion fortsetzen">
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                                            <span>Fortsetzen</span>
                                        </button>
                                        <button type="button" class="ptask-action-btn ptask-btn-stop btn-stop-task" data-job-id="${escapeHtml(task.job_id)}" title="Extraktion stoppen">
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="2"></rect></svg>
                                            <span>Stopp</span>
                                        </button>
                                    ` : ''}
                                    <button type="button" class="ptask-action-btn ptask-btn-download btn-download-task" data-job-id="${escapeHtml(task.job_id)}" title="Ergebnisse als Excel (.xlsx) herunterladen">
                                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                                        <span>Excel (.xlsx)</span>
                                    </button>
                                    <button type="button" class="ptask-action-btn ptask-btn-delete btn-delete-task" data-job-id="${escapeHtml(task.job_id)}" title="Aufgabe löschen">
                                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                                        <span>Löschen</span>
                                    </button>
                                </div>
                            </div>
                        </div>
                    `;
                }).join("");
            } catch (_) {}
        }

        async function reopenPreviousTask(ui, jobId, runId) {
            if (!jobId) return;
            ui.autoJobId = jobId;
            if (runId) {
                ui.currentSearchRunId = runId;
            }
            if (ui.progressPanel) {
                ui.progressPanel.classList.add("visible");
                if (typeof ui.progressPanel.scrollIntoView === "function") {
                    ui.progressPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
                }
            }
            await pollAutoProgress(ui);
            if (ui.pollTimer) clearInterval(ui.pollTimer);
            ui.pollTimer = setInterval(() => { pollAutoProgress(ui); }, 1500);

            // Fetch and display this task's job opportunities in results table
            try {
                const jResp = await fetch(`/api/inline/auto-jobs/jobs/${encodeURIComponent(jobId)}`);
                const jData = await jResp.json();
                if (jData.success && Array.isArray(jData.jobs) && jData.jobs.length) {
                    renderResults(ui, { jobs: jData.jobs, total: jData.total });
                }
            } catch (_) {}
            loadPreviousTasks(ui);
        }

        async function triggerAutoJobDownload(jobId, filterMode = "all") {
            const filterParam = encodeURIComponent(filterMode || "all");
            const downloadUrl = `/api/inline/auto-jobs/download/${encodeURIComponent(jobId)}?filter=${filterParam}`;
            const resp = await fetch(downloadUrl);
            if (!resp.ok) {
                let errMessage = "Download fehlgeschlagen";
                try {
                    const errData = await resp.json();
                    errMessage = errData.message || errMessage;
                } catch (_) {}
                throw new Error(errMessage);
            }
            const blob = await resp.blob();
            let filename = `auto_extraction_${jobId.slice(0, 8)}.xlsx`;
            const disposition = resp.headers.get("Content-Disposition");
            if (disposition && disposition.includes("filename=")) {
                const match = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
                if (match && match[1]) {
                    filename = match[1].replace(/['"]/g, "").trim();
                }
            }
            const blobUrl = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.style.display = "none";
            link.href = blobUrl;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            setTimeout(() => {
                URL.revokeObjectURL(blobUrl);
                link.remove();
            }, 1500);
        }

        async function stopAndDownloadAuto(ui) {
            let jobId = ui.autoJobId;
            if (!jobId) {
                try {
                    jobId = localStorage.getItem("jobscout_active_auto_job_id") || "";
                } catch (_) {}
            }
            if (!jobId) {
                try {
                    const actResp = await fetch("/api/inline/auto-jobs/active");
                    const actData = await actResp.json();
                    if (actData.has_active && actData.job_id) {
                        jobId = actData.job_id;
                        ui.autoJobId = jobId;
                    }
                } catch (_) {}
            }

            if (!jobId) {
                ui.progressError.textContent = "Kein aktiver Job auf dieser Seite.";
                ui.progressError.style.display = "block";
                return;
            }

            const origStopBtnHtml = ui.stopBtn ? ui.stopBtn.innerHTML : "";
            if (ui.stopBtn) {
                ui.stopBtn.disabled = true;
                ui.stopBtn.innerHTML = `<span class="btn-spinner"></span><span>Stoppe &amp; erstelle Download...</span>`;
            }
            if (ui.progressStatus) {
                ui.progressStatus.textContent = "Stoppe Extraktion und erstelle Excel-Download...";
            }
            if (ui.progressError) {
                ui.progressError.style.display = "none";
            }

            try {
                // 1. Send stop command to server
                const response = await fetch(`/api/inline/auto-jobs/stop/${encodeURIComponent(jobId)}`, { method: "POST" });
                const data = await response.json().catch(() => ({}));

                if (!response.ok || !data.success) {
                    throw new Error(data.message || "Stoppen fehlgeschlagen");
                }

                // 2. Stop frontend polling loop
                if (ui.pollTimer) {
                    clearInterval(ui.pollTimer);
                    ui.pollTimer = null;
                }

                // 3. Robust download via Blob (never blocked by popup/download blockers)
                await triggerAutoJobDownload(jobId, ui.activeFilter || "all");

                // 4. Fetch the latest enriched jobs to update the results table on page
                try {
                    const jobsResp = await fetch(`/api/inline/auto-jobs/jobs/${encodeURIComponent(jobId)}`);
                    const jobsData = await jobsResp.json();
                    if (jobsData.success && Array.isArray(jobsData.jobs) && jobsData.jobs.length) {
                        ui.lastJobs = jobsData.jobs;
                        renderResults(ui, {
                            jobs: ui.lastJobs,
                            total: ui.lastJobs.length,
                            published_since: ui.publishedSinceEl ? ui.publishedSinceEl.value : "all",
                        });
                    }
                } catch (rErr) {
                    console.debug("Could not refresh results table after stop:", rErr);
                }

                // 5. Update UI states
                setAutoBtnIdle(ui.autoBtn);
                if (ui.progressStatus) {
                    ui.progressStatus.textContent = "Extraktion gestoppt. Download abgeschlossen.";
                }
                if (ui.downloadBtn) {
                    ui.downloadBtn.style.display = "inline-flex";
                }
                if (ui.anschreibenBtn) {
                    ui.anschreibenBtn.style.display = "inline-flex";
                }
                if (ui.stopBtn) {
                    ui.stopBtn.style.display = "none";
                }
            } catch (error) {
                if (ui.progressError) {
                    ui.progressError.textContent = error.message || "Stoppen oder Download fehlgeschlagen";
                    ui.progressError.style.display = "block";
                }
                if (ui.stopBtn) {
                    ui.stopBtn.disabled = false;
                    ui.stopBtn.innerHTML = origStopBtnHtml;
                }
            }
        }

        async function transferJobsToCoverLetterStudio(ui, jobsToTransfer) {
            const jobs = Array.isArray(jobsToTransfer) && jobsToTransfer.length > 0
                ? jobsToTransfer
                : (ui.lastJobs || []);

            if (!jobs.length) {
                showError(ui, "Keine Stellenanzeigen zum Übertragen vorhanden.");
                return;
            }

            const btn = ui.generateCoverLettersBtn;
            const originalText = btn ? btn.textContent : "";
            if (btn) {
                btn.disabled = true;
                btn.textContent = `⚡ Übertrage ${jobs.length} Stellen...`;
            }

            try {
                const response = await fetch("/api/create-anschreibens/direct-jobs-bootstrap", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        jobs: jobs,
                        source_label: "JobScout Suche"
                    })
                });

                const data = await response.json();
                if (!response.ok || !data.success || !data.session) {
                    throw new Error(data.error || "Fehler beim Vorbereiten der Stellen für das Cover Letter Studio");
                }

                // Store direct session for Cover Letter Studio to adopt seamlessly
                window.sessionStorage.setItem("anschreiben:direct-session", JSON.stringify(data.session));

                // Switch section to Cover Letter Studio
                const studioLink = document.querySelector('[data-section-link="create-anschreibens"]');
                if (studioLink) {
                    studioLink.click();
                } else {
                    window.location.href = "/create-anschreibens";
                }
            } catch (err) {
                showError(ui, err.message || "Übertragung ins Cover Letter Studio fehlgeschlagen.");
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = originalText;
                }
            }
        }

        async function runInlineSearch(ui) {
            const keyword = ui.keywordEl.value.trim();
            const location = ui.locationEl.value.trim();
            const publishedSince = ui.publishedSinceEl.value;
            const source = ui.sourceEl ? ui.sourceEl.value : "all";
            const modeInput = ui.form ? ui.form.querySelector('input[name="mode"]:checked') : document.querySelector('input[name="mode"]:checked');
            const mode = modeInput ? modeInput.value : "ausbildung";
            const radiusEl = ui.form ? ui.form.querySelector('[name="radius"]') : document.getElementById("search_radius");
            const radius = radiusEl ? radiusEl.value.trim() : "";

            if (!keyword) {
                showError(ui, "Bitte ein Stichwort eingeben.");
                return;
            }

            if (ui.currentEventSource) {
                try {
                    ui.currentEventSource.close();
                } catch (_) {}
                ui.currentEventSource = null;
            }
            const currentGen = (ui.searchGeneration = (ui.searchGeneration || 0) + 1);

            // Search Session Isolation: decouple previous extraction task from the new search run
            if (ui.pollTimer) {
                clearInterval(ui.pollTimer);
                ui.pollTimer = null;
            }
            ui.autoJobId = null;
            if (ui.progressPanel) {
                ui.progressPanel.classList.remove("visible");
            }
            setAutoBtnIdle(ui.autoBtn);

            const searchRunId = "run_" + Date.now() + "_" + Math.random().toString(36).substring(2, 9);
            ui.currentSearchRunId = searchRunId;

            saveIndexState();
            setLoading(ui, true);

            const searchScope = "both";
            const autoCategoriesEl = document.getElementById("auto_categories_toggle");
            const autoCategories = autoCategoriesEl ? String(autoCategoriesEl.checked) : "true";
            const customCategoriesEl = document.getElementById("custom_categories");
            const customCategories = customCategoriesEl ? customCategoriesEl.value : "";

            const params = new URLSearchParams({
                search_run_id: searchRunId,
                keyword,
                location,
                published_since: publishedSince,
                source,
                mode,
                radius,
                search_scope: searchScope,
                auto_categories: autoCategories,
                custom_categories: customCategories,
            });

            let searchCompleted = false;

            // 1. Try real-time streaming search via Server-Sent Events (SSE)
            try {
                const streamUrl = `/api/search/stream?${params.toString()}`;
                const evtSource = new EventSource(streamUrl);
                ui.currentEventSource = evtSource;

                await new Promise((resolve, reject) => {
                    // Inactivity watchdog: the backend emits a heartbeat every ~2s while portals run,
                    // so only a silent stream (server gone / network dead) is treated as a failure.
                    // A long but alive search is never cut off.
                    const STREAM_IDLE_LIMIT_MS = 90000;
                    let timeoutTimer = null;
                    const armWatchdog = () => {
                        if (timeoutTimer) clearTimeout(timeoutTimer);
                        timeoutTimer = setTimeout(() => {
                            evtSource.close();
                            if (ui.currentEventSource === evtSource) ui.currentEventSource = null;
                            if (!searchCompleted) {
                                const err = new Error("Live stream stalled: no data from server for 90s");
                                err.fatal = true;
                                reject(err);
                            }
                        }, STREAM_IDLE_LIMIT_MS);
                    };
                    armWatchdog();
                    evtSource.addEventListener("start", armWatchdog);

                    evtSource.addEventListener("progress", (e) => {
                        if (ui.searchGeneration !== currentGen) return;
                        armWatchdog();
                        try {
                            const data = JSON.parse(e.data);
                            setSearchProgress(ui, data);
                        } catch (_) {}
                    });

                    evtSource.addEventListener("complete", (e) => {
                        clearTimeout(timeoutTimer);
                        if (ui.searchGeneration !== currentGen) {
                            evtSource.close();
                            if (ui.currentEventSource === evtSource) ui.currentEventSource = null;
                            return;
                        }
                        try {
                            const data = JSON.parse(e.data);
                            evtSource.close();
                            if (ui.currentEventSource === evtSource) ui.currentEventSource = null;
                            if (data.search_run_id) {
                                ui.currentSearchRunId = data.search_run_id;
                            }
                            searchCompleted = true;
                            setSearchProgress(ui, {
                                percent: 100,
                                stage: `Fertig: ${data.total || 0} Stellen gefunden!`,
                                found: data.total || 0,
                            });
                            renderResults(ui, data);
                            loadPreviousTasks(ui);
                            resolve();
                        } catch (err) {
                            evtSource.close();
                            if (ui.currentEventSource === evtSource) ui.currentEventSource = null;
                            reject(err);
                        }
                    });

                    evtSource.addEventListener("error", (e) => {
                        clearTimeout(timeoutTimer);
                        evtSource.close();
                        if (ui.currentEventSource === evtSource) ui.currentEventSource = null;
                        if (searchCompleted) return;
                        // A server-sent `event: error` carries data: the search itself failed,
                        // so re-running it through the fallback would only repeat the failure.
                        if (e && e.data) {
                            let msg = "Suche fehlgeschlagen";
                            try { msg = JSON.parse(e.data).message || msg; } catch (_) {}
                            const err = new Error(msg);
                            err.fatal = true;
                            reject(err);
                            return;
                        }
                        reject(new Error("Stream connection failed"));
                    });
                });
            } catch (streamError) {
                if (ui.searchGeneration !== currentGen) return;
                if (!searchCompleted && streamError && streamError.fatal) {
                    logToConsole(ui, streamError.message, "error", "stream");
                    showError(ui, streamError.message || "Suche fehlgeschlagen");
                } else if (!searchCompleted) {
                    console.warn("SSE stream failed or not supported, falling back to /api/search:", streamError);
                    // No simulated numbers: without the live stream we only know that the request is running.
                    logToConsole(ui, "Live stream unavailable — running search without live metrics (results appear when finished)...", "warning", "stream");
                    setSearchProgress(ui, {
                        percent: 5,
                        stage: "Live stream unavailable — waiting for search results (no live metrics)...",
                        found: 0,
                        status: "heartbeat",
                    });
                    const simInterval = null;

                    try {
                        const response = await fetch(`/api/search?${params.toString()}`);
                        const data = await response.json();
                        clearInterval(simInterval);
                        if (ui.searchGeneration !== currentGen) return;

                        if (!response.ok || data.status !== "success") {
                            throw new Error(data.message || "Suche fehlgeschlagen");
                        }

                        if (data.search_run_id) {
                            ui.currentSearchRunId = data.search_run_id;
                        }
                        searchCompleted = true;
                        setSearchProgress(ui, {
                            percent: 100,
                            stage: `Fertig: ${data.total || 0} Stellen gefunden!`,
                            found: data.total || 0,
                        });
                        renderResults(ui, data);
                        loadPreviousTasks(ui);
                    } catch (fallbackError) {
                        clearInterval(simInterval);
                        if (ui.searchGeneration === currentGen) {
                            showError(ui, fallbackError.message || "Suche fehlgeschlagen");
                        }
                    }
                }
            } finally {
                if (ui.searchGeneration === currentGen) {
                    setLoading(ui, false);
                }
            }
        }

        const searchUi1 = {
            form: formOne,
            keywordEl: document.getElementById("keyword"),
            locationEl: document.getElementById("location"),
            publishedSinceEl: document.getElementById("published_since"),
            sourceEl: document.getElementById("search_source_1"),
            searchBtn: document.getElementById("search_btn_1"),
            btnBar: document.getElementById("search_btn_bar_1"),
            btnLabel: document.getElementById("search_btn_label_1"),
            progressCard: document.getElementById("search_progress_card_1"),
            progressTitle: document.getElementById("search_progress_title_1"),
            progressCounter: document.getElementById("search_progress_counter_1"),
            searchProgressFill: document.getElementById("search_progress_fill_1"),
            searchProgressPct: document.getElementById("search_progress_pct_1"),
            searchProgressStatus: document.getElementById("search_progress_status_1"),
            searchProgressStages: document.getElementById("search_progress_stages_1"),
            loadingEl: document.getElementById("loading_1"),
            resultsBox: document.getElementById("results_1"),
            metaEl: document.getElementById("results_meta_1"),
            listEl: document.getElementById("results_list_1"),
            errorEl: document.getElementById("results_error_1"),
            targetBanner: document.getElementById("scraper_target_banner_1"),
            targetText: document.getElementById("scraper_target_text_1"),
            metricRaw: document.getElementById("metric_raw_scanned_1"),
            metricMatched: document.getElementById("metric_matched_leads_1"),
            metricSource: document.getElementById("metric_active_source_1"),
            consoleTerminal: document.getElementById("scraper_console_terminal_1"),
            consoleClear: document.getElementById("scraper_console_clear_1"),
            consoleToggle: document.getElementById("scraper_console_toggle_1"),
            lastLoggedStage: "",
            autoBtn: document.getElementById("auto_btn_1"),
            progressPanel: document.getElementById("progress_panel_1"),
            processedEl: document.getElementById("processed_1"),
            totalEl: document.getElementById("total_1"),
            emailsEl: document.getElementById("emails_1"),
            formsEl: document.getElementById("forms_1"),
            percentNumEl: document.getElementById("percent_num_1"),
            statusBadgeEl: document.getElementById("extraction_status_badge_1"),
            activeWorkersBadgeEl: document.getElementById("active_workers_badge_1"),
            etaEl: document.getElementById("progress_eta_1"),
            speedEl: document.getElementById("progress_speed_1"),
            recruitmentEmailsEl: document.getElementById("recruitment_emails_1"),
            externalLinksEl: document.getElementById("external_links_1"),
            fastPathEl: document.getElementById("fast_path_1"),
            seleniumFallbacksEl: document.getElementById("selenium_fallbacks_1"),
            rateLimitedEl: document.getElementById("rate_limited_1"),
            avgTimeEl: document.getElementById("avg_time_1"),
            pendingEl: document.getElementById("pending_1"),
            captchaEl: document.getElementById("captcha_1"),
            captchaUniqueEl: document.getElementById("captcha_unique_1"),
            captchaRequestsEl: document.getElementById("captcha_requests_1"),
            captchaVerifiedEl: document.getElementById("captcha_verified_1"),
            captchaManualEl: document.getElementById("captcha_manual_1"),
            captchaDiagBtn: document.getElementById("captcha_diag_btn_1"),
            captchaDiagPanel: document.getElementById("captcha_diag_panel_1"),
            captchaDiagArrow: document.getElementById("captcha_diag_arrow_1"),
            captchaDiagPill: document.getElementById("captcha_diag_pill_1"),
            captchaDiagTbody: document.getElementById("captcha_diag_tbody_1"),
            failedEl: document.getElementById("failed_1"),
            manualCaptchaSection: document.getElementById("manual_captcha_section_1"),
            manualCaptchaBadge: document.getElementById("manual_captcha_badge_1"),
            manualCaptchaCards: document.getElementById("manual_captcha_cards_1"),
            workersGridEl: document.getElementById("workers_grid_1"),
            activityFeedListEl: document.getElementById("activity_feed_list_1"),
            feedCounterEl: document.getElementById("feed_counter_1"),
            progressFill: document.getElementById("progress_fill_1"),
            progressStatus: document.getElementById("progress_status_1"),
            progressError: document.getElementById("progress_error_1"),
            stopBtn: document.getElementById("stop_btn_1"),
            pauseBtn: document.getElementById("pause_btn_1"),
            continueBtn: document.getElementById("continue_btn_1"),
            downloadBtn: document.getElementById("download_btn_1"),
            anschreibenBtn: document.getElementById("anschreiben_btn_1"),
            generateCoverLettersBtn: document.getElementById("btn_generate_cover_letters_1"),
            filterBar: document.getElementById("results_filter_bar_1"),
            previousTasksSection: document.getElementById("previous_tasks_section_1"),
            previousTasksList: document.getElementById("previous_tasks_list_1"),
            previousTasksCount: document.getElementById("previous_tasks_count_1"),
            clearPreviousTasksBtn: document.getElementById("btn_clear_previous_tasks_1"),
            togglePreviousTasksBtn: document.getElementById("toggle_previous_tasks_btn_1"),
            previousTasksToggleArea: document.getElementById("previous_tasks_toggle_area_1"),
            activeFilter: "all",
            lastJobs: [],
            autoJobId: "",
            currentSearchRunId: "",
            pollTimer: null,
        };

        const searchUi2 = formTwo ? {
            form: formTwo,
            keywordEl: document.getElementById("keyword_2"),
            locationEl: document.getElementById("location_2"),
            publishedSinceEl: document.getElementById("published_since_2"),
            sourceEl: document.getElementById("search_source_2"),
            searchBtn: document.getElementById("search_btn_2"),
            btnBar: document.getElementById("search_btn_bar_2"),
            btnLabel: document.getElementById("search_btn_label_2"),
            progressCard: document.getElementById("search_progress_card_2"),
            progressTitle: document.getElementById("search_progress_title_2"),
            progressCounter: document.getElementById("search_progress_counter_2"),
            searchProgressFill: document.getElementById("search_progress_fill_2"),
            searchProgressPct: document.getElementById("search_progress_pct_2"),
            searchProgressStatus: document.getElementById("search_progress_status_2"),
            searchProgressStages: document.getElementById("search_progress_stages_2"),
            loadingEl: document.getElementById("loading_2"),
            resultsBox: document.getElementById("results_2"),
            metaEl: document.getElementById("results_meta_2"),
            listEl: document.getElementById("results_list_2"),
            errorEl: document.getElementById("results_error_2"),
            autoBtn: document.getElementById("auto_btn_2"),
            progressPanel: document.getElementById("progress_panel_2"),
            processedEl: document.getElementById("processed_2"),
            emailsEl: document.getElementById("emails_2"),
            captchaEl: document.getElementById("captcha_2"),
            failedEl: document.getElementById("failed_2"),
            manualCaptchaSection: document.getElementById("manual_captcha_section_2"),
            manualCaptchaBadge: document.getElementById("manual_captcha_badge_2"),
            manualCaptchaCards: document.getElementById("manual_captcha_cards_2"),
            progressFill: document.getElementById("progress_fill_2"),
            progressStatus: document.getElementById("progress_status_2"),
            progressError: document.getElementById("progress_error_2"),
            stopBtn: document.getElementById("stop_btn_2"),
            continueBtn: document.getElementById("continue_btn_2"),
            downloadBtn: document.getElementById("download_btn_2"),
            anschreibenBtn: document.getElementById("anschreiben_btn_2"),
            filterBar: document.getElementById("results_filter_bar_2"),
            activeFilter: "all",
            lastJobs: [],
            autoJobId: "",
            pollTimer: null,
        } : null;

        function bindFilterEvents(ui) {
            if (!ui || !ui.filterBar) return;
            ui.filterBar.addEventListener("click", (e) => {
                const btn = e.target.closest(".filter-pill");
                if (!btn) return;
                const filter = btn.dataset.filter || "all";
                ui.activeFilter = filter;
                ui.filterBar.querySelectorAll(".filter-pill").forEach((p) => p.classList.remove("active"));
                btn.classList.add("active");
                if (ui.lastJobs && ui.lastJobs.length) {
                    renderResults(ui, {
                        jobs: ui.lastJobs,
                        total: ui.lastJobs.length,
                        published_since: ui.publishedSinceEl ? ui.publishedSinceEl.value : "all",
                    });
                }
            });
        }
        bindFilterEvents(searchUi1);
        if (searchUi1.captchaDiagBtn && searchUi1.captchaDiagPanel) {
            searchUi1.captchaDiagBtn.addEventListener("click", () => {
                const isHidden = searchUi1.captchaDiagPanel.style.display === "none";
                searchUi1.captchaDiagPanel.style.display = isHidden ? "block" : "none";
                searchUi1.captchaDiagBtn.setAttribute("aria-expanded", isHidden ? "true" : "false");
                if (searchUi1.captchaDiagArrow) {
                    searchUi1.captchaDiagArrow.classList.toggle("is-open", isHidden);
                }
            });
        }
        // Console Clear & Toggle Listeners
        if (searchUi1.consoleClear && searchUi1.consoleTerminal) {
            searchUi1.consoleClear.addEventListener("click", () => {
                searchUi1.consoleTerminal.innerHTML = '<div class="terminal-row terminal-muted">[00:00:00] Console cleared. Ready for next scraping cycle.</div>';
            });
        }
        if (searchUi1.consoleToggle && searchUi1.consoleTerminal) {
            searchUi1.consoleToggle.addEventListener("click", () => {
                const isHidden = searchUi1.consoleTerminal.style.display === "none";
                searchUi1.consoleTerminal.style.display = isHidden ? "block" : "none";
                searchUi1.consoleToggle.textContent = isHidden ? "Minimize ▲" : "Expand ▼";
            });
        }

        if (searchUi2) bindFilterEvents(searchUi2);

        searchUi1.form.addEventListener("submit", async (event) => {
            event.preventDefault();
            await runInlineSearch(searchUi1);
        });

        searchUi1.autoBtn.addEventListener("click", async () => {
            if (searchUi1.autoJobId && searchUi1.continueBtn && searchUi1.continueBtn.style.display !== "none") {
                await continueAutoExtraction(searchUi1);
            } else {
                await startAutoExtraction(searchUi1);
            }
        });

        if (searchUi1.pauseBtn) {
            searchUi1.pauseBtn.addEventListener("click", async () => {
                await pauseAutoExtraction(searchUi1);
            });
        }

        searchUi1.continueBtn.addEventListener("click", async () => {
            await continueAutoExtraction(searchUi1);
        });

        searchUi1.stopBtn.addEventListener("click", async () => {
            await stopAndDownloadAuto(searchUi1);
        });

        setupManualCaptchaListeners(searchUi1);
        if (searchUi2) {
            setupManualCaptchaListeners(searchUi2);
        }

        // Previous tasks section toggle
        if (searchUi1.togglePreviousTasksBtn && searchUi1.previousTasksList) {
            const toggleTasks = () => {
                const isHidden = (searchUi1.previousTasksList.style.display === "none");
                searchUi1.previousTasksList.style.display = isHidden ? "flex" : "none";
                searchUi1.togglePreviousTasksBtn.textContent = isHidden ? "Hide Tasks ▴" : "Show Tasks ▾";
            };
            searchUi1.togglePreviousTasksBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                toggleTasks();
            });
            if (searchUi1.previousTasksToggleArea) {
                searchUi1.previousTasksToggleArea.addEventListener("click", toggleTasks);
            }
        }

        // Delegated clicks for previous tasks cards
        if (searchUi1.previousTasksList) {
            searchUi1.previousTasksList.addEventListener("click", async (e) => {
                const target = e.target;
                const reopenBtn = target.closest(".btn-reopen-task");
                if (reopenBtn) {
                    const jobId = reopenBtn.dataset.jobId;
                    const runId = reopenBtn.dataset.runId;
                    await reopenPreviousTask(searchUi1, jobId, runId);
                    return;
                }
                const pauseBtn = target.closest(".btn-pause-task");
                if (pauseBtn) {
                    const jobId = pauseBtn.dataset.jobId;
                    try {
                        await fetch(`/api/inline/auto-jobs/pause/${encodeURIComponent(jobId)}`, { method: "POST" });
                        if (searchUi1.autoJobId === jobId) {
                            await pollAutoProgress(searchUi1);
                        }
                        loadPreviousTasks(searchUi1);
                    } catch (_) {}
                    return;
                }
                const resumeBtn = target.closest(".btn-resume-task");
                if (resumeBtn) {
                    const jobId = resumeBtn.dataset.jobId;
                    try {
                        await fetch(`/api/inline/auto-jobs/continue/${encodeURIComponent(jobId)}`, { method: "POST" });
                        if (searchUi1.autoJobId === jobId) {
                            if (searchUi1.pollTimer) clearInterval(searchUi1.pollTimer);
                            searchUi1.pollTimer = setInterval(() => { pollAutoProgress(searchUi1); }, 1500);
                            await pollAutoProgress(searchUi1);
                        }
                        loadPreviousTasks(searchUi1);
                    } catch (_) {}
                    return;
                }
                const stopBtn = target.closest(".btn-stop-task");
                if (stopBtn) {
                    const jobId = stopBtn.dataset.jobId;
                    try {
                        await fetch(`/api/inline/auto-jobs/stop/${encodeURIComponent(jobId)}`, { method: "POST" });
                        if (searchUi1.autoJobId === jobId) {
                            await pollAutoProgress(searchUi1);
                        }
                        loadPreviousTasks(searchUi1);
                    } catch (_) {}
                    return;
                }
                const dlBtn = target.closest(".btn-download-task");
                if (dlBtn) {
                    const jobId = dlBtn.dataset.jobId;
                    try {
                        await triggerAutoJobDownload(jobId, "all");
                    } catch (_) {}
                    return;
                }
                const deleteBtn = target.closest(".btn-delete-task");
                if (deleteBtn) {
                    const jobId = deleteBtn.dataset.jobId;
                    if (!jobId) return;
                    if (!confirm("Möchten Sie diese Aufgabe wirklich löschen?")) return;
                    try {
                        deleteBtn.disabled = true;
                        const resp = await fetch(`/api/inline/auto-jobs/delete/${encodeURIComponent(jobId)}`, { method: "POST" });
                        const res = await resp.json().catch(() => ({}));
                        if (res && res.success) {
                            if (searchUi1.autoJobId === jobId) {
                                searchUi1.autoJobId = "";
                                if (searchUi1.progressPanel) {
                                    searchUi1.progressPanel.classList.remove("visible");
                                }
                                if (searchUi1.pollTimer) {
                                    clearInterval(searchUi1.pollTimer);
                                    searchUi1.pollTimer = null;
                                }
                            }
                            await loadPreviousTasks(searchUi1);
                        } else {
                            alert(res.message || "Löschen fehlgeschlagen");
                        }
                    } catch (err) {
                        alert("Fehler beim Löschen: " + (err.message || err));
                    } finally {
                        deleteBtn.disabled = false;
                    }
                    return;
                }
            });
        }

        if (searchUi1.clearPreviousTasksBtn) {
            searchUi1.clearPreviousTasksBtn.addEventListener("click", async (e) => {
                e.stopPropagation();
                if (!confirm("Möchten Sie wirklich alle vorherigen Aufgaben löschen?")) return;
                try {
                    searchUi1.clearPreviousTasksBtn.disabled = true;
                    const resp = await fetch("/api/inline/auto-jobs/clear?all=1", { method: "POST" });
                    const res = await resp.json().catch(() => ({}));
                    if (res && res.success) {
                        searchUi1.autoJobId = "";
                        if (searchUi1.progressPanel) {
                            searchUi1.progressPanel.classList.remove("visible");
                        }
                        if (searchUi1.pollTimer) {
                            clearInterval(searchUi1.pollTimer);
                            searchUi1.pollTimer = null;
                        }
                        await loadPreviousTasks(searchUi1);
                    } else {
                        alert(res.message || "Löschen fehlgeschlagen");
                    }
                } catch (err) {
                    alert("Fehler beim Löschen: " + (err.message || err));
                } finally {
                    searchUi1.clearPreviousTasksBtn.disabled = false;
                }
            });
        }

        searchUi1.downloadBtn.addEventListener("click", async () => {
            let jobId = searchUi1.autoJobId;
            if (!jobId) {
                try {
                    jobId = localStorage.getItem("jobscout_active_auto_job_id") || "";
                } catch (_) {}
            }
            if (!jobId) return;
            const origHtml = searchUi1.downloadBtn.innerHTML;
            searchUi1.downloadBtn.disabled = true;
            searchUi1.downloadBtn.innerHTML = `<span class="btn-spinner"></span><span>Lade herunter...</span>`;
            try {
                await triggerAutoJobDownload(jobId, searchUi1.activeFilter || "all");
            } catch (err) {
                if (searchUi1.progressError) {
                    searchUi1.progressError.textContent = err.message || "Download fehlgeschlagen";
                    searchUi1.progressError.style.display = "block";
                }
            } finally {
                searchUi1.downloadBtn.disabled = false;
                searchUi1.downloadBtn.innerHTML = origHtml;
            }
        });

        searchUi1.anschreibenBtn.addEventListener("click", async () => {
            if (!searchUi1.autoJobId) {
                return;
            }
            const response = await fetch(`/api/inline/auto-jobs/use-for-anschreiben/${encodeURIComponent(searchUi1.autoJobId)}`, { method: "POST" });
            const data = await response.json().catch(() => ({}));
            if (response.ok && data.success) {
                window.location.href = data.redirect_url || "/create-anschreibens?autoload=auto";
            }
        });

        if (searchUi1.generateCoverLettersBtn) {
            searchUi1.generateCoverLettersBtn.addEventListener("click", async () => {
                const checkedBoxes = Array.from(searchUi1.listEl.querySelectorAll(".job-select-checkbox:checked"));
                let selectedJobs = [];
                if (checkedBoxes.length > 0) {
                    selectedJobs = checkedBoxes.map((cb) => {
                        const idx = parseInt(cb.dataset.index, 10);
                        return searchUi1.lastJobs[idx];
                    }).filter(Boolean);
                } else {
                    const activeFilter = searchUi1.activeFilter || "all";
                    selectedJobs = searchUi1.lastJobs.filter((job) => {
                        if (activeFilter === "all") return true;
                        return getJobMethodCategory(job) === activeFilter;
                    });
                }
                await transferJobsToCoverLetterStudio(searchUi1, selectedJobs);
            });
        }

        if (searchUi2) {
            searchUi2.form.addEventListener("submit", async (event) => {
                event.preventDefault();
                await runInlineSearch(searchUi2);
            });

            searchUi2.autoBtn.addEventListener("click", async () => {
                await startAutoExtraction(searchUi2);
            });

            searchUi2.continueBtn.addEventListener("click", async () => {
                await continueAutoExtraction(searchUi2);
            });

            searchUi2.stopBtn.addEventListener("click", async () => {
                await stopAndDownloadAuto(searchUi2);
            });

            searchUi2.downloadBtn.addEventListener("click", async () => {
                let jobId = searchUi2.autoJobId;
                if (!jobId) {
                    try {
                        jobId = localStorage.getItem("jobscout_active_auto_job_id") || "";
                    } catch (_) {}
                }
                if (!jobId) return;
                const origHtml = searchUi2.downloadBtn.innerHTML;
                searchUi2.downloadBtn.disabled = true;
                searchUi2.downloadBtn.innerHTML = `<span class="btn-spinner"></span><span>Lade herunter...</span>`;
                try {
                    await triggerAutoJobDownload(jobId, searchUi2.activeFilter || "all");
                } catch (err) {
                    if (searchUi2.progressError) {
                        searchUi2.progressError.textContent = err.message || "Download fehlgeschlagen";
                        searchUi2.progressError.style.display = "block";
                    }
                } finally {
                    searchUi2.downloadBtn.disabled = false;
                    searchUi2.downloadBtn.innerHTML = origHtml;
                }
            });

            searchUi2.anschreibenBtn.addEventListener("click", async () => {
                if (!searchUi2.autoJobId) {
                    return;
                }
                const response = await fetch(`/api/inline/auto-jobs/use-for-anschreiben/${encodeURIComponent(searchUi2.autoJobId)}`, { method: "POST" });
                const data = await response.json().catch(() => ({}));
                if (response.ok && data.success) {
                    window.location.href = data.redirect_url || "/create-anschreibens?autoload=auto";
                }
            });
        }

        // Mode Segmented Control dynamic placeholders, hints & prefix prefill
        const modeRadios = document.querySelectorAll('input[name="mode"]');
        const ausbildungOption = document.querySelector('label[for="mode_ausbildung"]');

        function applyAusbildungPrefix(focus = true) {
            const kwInput = document.getElementById("keyword");
            if (!kwInput) return;
            const prefix = "Ausbildung als ";
            if (!kwInput.value || kwInput.value.trim() === "" || kwInput.value.trim() === "Ausbildung als") {
                kwInput.value = prefix;
            } else if (!kwInput.value.startsWith(prefix)) {
                kwInput.value = prefix + kwInput.value.replace(/^Ausbildung\s+(als\s+)?/i, "").trimStart();
            }
            if (focus) {
                kwInput.focus();
                const len = kwInput.value.length;
                kwInput.setSelectionRange(len, len);
            }
        }

        modeRadios.forEach((radio) => {
            radio.addEventListener("change", (e) => {
                const val = e.target.value;
                const kwInput = document.getElementById("keyword");
                const hint = document.getElementById("keyword_hint");
                if (val === "arbeit") {
                    if (kwInput) {
                        kwInput.placeholder = "z. B. Softwareentwickler, Projektmanager, Elektroniker";
                        if (kwInput.value === "Ausbildung als " || kwInput.value.trim() === "Ausbildung als") {
                            kwInput.value = "";
                        } else if (kwInput.value.startsWith("Ausbildung als ")) {
                            kwInput.value = kwInput.value.slice("Ausbildung als ".length);
                        }
                    }
                    if (hint) hint.textContent = "Geben Sie die Berufsbezeichnung ein — findet Arbeitgeber und direkte E-Mail-Kontakte.";
                } else {
                    if (kwInput) {
                        kwInput.placeholder = "z. B. Fachinformatiker, Koch, Softwareentwickler";
                        applyAusbildungPrefix(true);
                    }
                    if (hint) hint.textContent = "Geben Sie einfach die Berufsbezeichnung ein — Suche passt sich automatisch an.";
                }
                saveIndexState();
            });
        });

        // Also allow clicking directly on Ausbildung option/label to focus and ensure prefix is present
        if (ausbildungOption) {
            ausbildungOption.addEventListener("click", () => {
                const hint = document.getElementById("keyword_hint");
                if (hint) hint.textContent = "Geben Sie einfach die Berufsbezeichnung ein — Suche passt sich automatisch an.";
                applyAusbildungPrefix(true);
                saveIndexState();
            });
        }

        // Collapsible Advanced Filters Toggle
        const filterToggle = document.getElementById("advanced_filters_toggle");
        const filterContent = document.getElementById("advanced_filters_content");
        if (filterToggle && filterContent) {
            filterToggle.addEventListener("click", () => {
                const isExpanded = filterToggle.getAttribute("aria-expanded") === "true";
                const newExpanded = !isExpanded;
                filterToggle.setAttribute("aria-expanded", String(newExpanded));
                filterContent.style.display = newExpanded ? "block" : "none";
                filterToggle.classList.toggle("is-open", newExpanded);
            });
        }

        // ---------------------------------------------------------------------
        // KI-Berufsverständnis (Intelligent Profession-to-Employer Engine)
        // ---------------------------------------------------------------------
        const aiProfToggle = document.getElementById("ai_profession_toggle");
        const aiProfContent = document.getElementById("ai_profession_content");
        const autoCatToggle = document.getElementById("auto_categories_toggle");
        const chipsContainer = document.getElementById("employer_categories_chips");
        const customCategoriesInput = document.getElementById("custom_categories");
        const profRecognizedName = document.getElementById("prof_recognized_name");
        const profSectorName = document.getElementById("prof_sector_name");
        const geoCoverageIndicator = document.getElementById("geo_coverage_indicator");
        const profSearchTermsPreview = document.getElementById("prof_search_terms_preview");
        const profSummaryBadge = document.getElementById("prof_summary_badge");

        const toggleCustomBtn = document.getElementById("toggle_custom_categories_btn");
        const customDrawer = document.getElementById("custom_categories_drawer");
        const newCustomInput = document.getElementById("new_custom_category_input");
        const addCustomBtn = document.getElementById("add_custom_category_btn");
        const restoreDefaultBtn = document.getElementById("restore_default_categories_btn");

        let activeCategoriesList = [];
        let defaultCategoriesList = [];
        let allCategoriesList = [];
        const disabledCategoriesSet = new Set();
        let classifyDebounceTimer = null;

        if (toggleCustomBtn && customDrawer) {
            toggleCustomBtn.addEventListener("click", () => {
                const isExpanded = toggleCustomBtn.getAttribute("aria-expanded") === "true";
                const newExpanded = !isExpanded;
                toggleCustomBtn.setAttribute("aria-expanded", String(newExpanded));
                customDrawer.style.display = newExpanded ? "block" : "none";
                toggleCustomBtn.classList.toggle("is-open", newExpanded);
            });
        }

        function addCustomCategoryAction() {
            if (!newCustomInput) return;
            const val = newCustomInput.value.trim();
            if (!val) return;
            if (!allCategoriesList.some(c => c.toLowerCase() === val.toLowerCase())) {
                allCategoriesList.push(val);
                disabledCategoriesSet.delete(val);
                activeCategoriesList = allCategoriesList.filter(c => !disabledCategoriesSet.has(c));
                if (customCategoriesInput) customCategoriesInput.value = activeCategoriesList.join(", ");
                renderCategoryChips();
                updateSearchTermsPreview();
            }
            newCustomInput.value = "";
        }

        if (addCustomBtn) {
            addCustomBtn.addEventListener("click", addCustomCategoryAction);
        }

        if (newCustomInput) {
            newCustomInput.addEventListener("keydown", (e) => {
                if (e.key === "Enter") {
                    e.preventDefault();
                    addCustomCategoryAction();
                }
            });
        }

        if (restoreDefaultBtn) {
            restoreDefaultBtn.addEventListener("click", () => {
                allCategoriesList = [...defaultCategoriesList];
                disabledCategoriesSet.clear();
                activeCategoriesList = [...defaultCategoriesList];
                if (customCategoriesInput) customCategoriesInput.value = activeCategoriesList.join(", ");
                renderCategoryChips();
                updateSearchTermsPreview();
            });
        }

        if (aiProfToggle && aiProfContent) {
            aiProfToggle.addEventListener("click", () => {
                const isExpanded = aiProfToggle.getAttribute("aria-expanded") === "true";
                const newExpanded = !isExpanded;
                aiProfToggle.setAttribute("aria-expanded", String(newExpanded));
                aiProfContent.style.display = newExpanded ? "block" : "none";
                aiProfToggle.classList.toggle("is-open", newExpanded);
            });
        }

        function renderCategoryChips() {
            if (!chipsContainer) return;
            chipsContainer.innerHTML = "";

            if (!allCategoriesList.length) {
                chipsContainer.innerHTML = `
                    <div class="ai-chips-empty">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                        <span>Type a profession above to automatically discover target employer industries</span>
                    </div>`;
                activeCategoriesList = [];
                if (customCategoriesInput) customCategoriesInput.value = "";
                return;
            }

            allCategoriesList.forEach((cat, idx) => {
                const isSelected = !disabledCategoriesSet.has(cat);
                const chip = document.createElement("div");
                chip.className = `ai-sector-chip ${isSelected ? "is-selected" : "is-unselected"}`;
                chip.setAttribute("role", "button");
                chip.setAttribute("tabindex", "0");
                chip.setAttribute("aria-pressed", isSelected ? "true" : "false");
                chip.title = isSelected ? "Active in search. Click to exclude." : "Excluded from search. Click to include.";

                chip.innerHTML = `
                    <span class="ai-chip-check" aria-hidden="true">
                        ${isSelected
                            ? '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>'
                            : '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"></circle></svg>'
                        }
                    </span>
                    <span class="ai-chip-name">${escapeHtml(cat)}</span>
                    <button type="button" class="ai-chip-remove" data-idx="${idx}" title="Remove category" aria-label="Remove category">&times;</button>
                `;

                // Remove button
                const removeBtn = chip.querySelector(".ai-chip-remove");
                removeBtn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    allCategoriesList.splice(idx, 1);
                    disabledCategoriesSet.delete(cat);
                    activeCategoriesList = allCategoriesList.filter(c => !disabledCategoriesSet.has(c));
                    if (customCategoriesInput) customCategoriesInput.value = activeCategoriesList.join(", ");
                    renderCategoryChips();
                    updateSearchTermsPreview();
                });

                // Toggle chip active state on chip click
                chip.addEventListener("click", () => {
                    if (disabledCategoriesSet.has(cat)) {
                        disabledCategoriesSet.delete(cat);
                    } else {
                        disabledCategoriesSet.add(cat);
                    }
                    activeCategoriesList = allCategoriesList.filter(c => !disabledCategoriesSet.has(c));
                    if (customCategoriesInput) customCategoriesInput.value = activeCategoriesList.join(", ");
                    renderCategoryChips();
                    updateSearchTermsPreview();
                });

                // Keyboard accessibility (Enter/Space toggles)
                chip.addEventListener("keydown", (e) => {
                    if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        chip.click();
                    }
                });

                chipsContainer.appendChild(chip);
            });

            activeCategoriesList = allCategoriesList.filter(c => !disabledCategoriesSet.has(c));
            if (customCategoriesInput) {
                customCategoriesInput.value = activeCategoriesList.join(", ");
            }
        }

        function updateSearchTermsPreview() {
            if (!profSearchTermsPreview) return;
            if (activeCategoriesList.length) {
                const loc = document.getElementById("location") ? document.getElementById("location").value.trim() : "";
                const locSuffix = loc ? ` ${loc}` : "";
                const terms = activeCategoriesList.map(c => `"${c}${locSuffix}"`).join(", ");
                profSearchTermsPreview.textContent = terms;
            } else {
                profSearchTermsPreview.textContent = "No specific category queries active.";
            }
        }

        async function triggerProfessionClassification(force = false) {
            const kwInput = document.getElementById("keyword");
            if (!kwInput) return;
            const rawVal = kwInput.value.trim();
            const locVal = document.getElementById("location") ? document.getElementById("location").value.trim() : "";

            if (!rawVal || rawVal.length < 3) {
                if (profRecognizedName) profRecognizedName.textContent = "Ready for input...";
                if (profSectorName) profSectorName.textContent = "—";
                if (profSearchTermsPreview) profSearchTermsPreview.textContent = "Enter a profession above to preview target search queries.";
                if (profSummaryBadge) profSummaryBadge.textContent = "Automatic";
                activeCategoriesList = [];
                defaultCategoriesList = [];
                allCategoriesList = [];
                disabledCategoriesSet.clear();
                renderCategoryChips();
                return;
            }

            if (autoCatToggle && !autoCatToggle.checked && !force) {
                return;
            }

            try {
                if (profSummaryBadge) profSummaryBadge.textContent = "Analyzing...";
                const res = await fetch(`/api/profession/classify?keyword=${encodeURIComponent(rawVal)}&location=${encodeURIComponent(locVal)}`);
                if (!res.ok) throw new Error("Classification failed");
                const data = await res.json();
                
                const norm = data.normalized_profession || rawVal;
                const sector = data.sector || "General";
                const cats = (data.employer_categories || []).map(c => c.category || c.search_term);
                
                if (profRecognizedName) profRecognizedName.textContent = norm;
                if (profSectorName) profSectorName.textContent = sector;
                if (profSummaryBadge) profSummaryBadge.textContent = "Automatic";
                
                if (data.geographic_coverage) {
                    const cov = data.geographic_coverage;
                    const hubCount = (cov.targets || []).length;
                    if (geoCoverageIndicator) {
                        if (cov.scope === "nationwide_sample") {
                            geoCoverageIndicator.textContent = `Nationwide (${hubCount} Metro Hubs)`;
                        } else if (cov.scope === "federal_state") {
                            geoCoverageIndicator.textContent = `${cov.matched_state} (${hubCount} Hubs)`;
                        } else {
                            geoCoverageIndicator.textContent = locVal || "Local Region";
                        }
                    }
                }
                defaultCategoriesList = [...cats];
                allCategoriesList = [...cats];
                disabledCategoriesSet.clear();
                activeCategoriesList = [...cats];
                renderCategoryChips();
                updateSearchTermsPreview();
            } catch (err) {
                console.warn("Profession classify error:", err);
                if (profSummaryBadge) profSummaryBadge.textContent = "Automatic";
            }
        }


        if (autoCatToggle) {
            autoCatToggle.addEventListener("change", () => {
                if (autoCatToggle.checked) {
                    triggerProfessionClassification(true);
                }
            });
        }

        const mainKwInput = document.getElementById("keyword");
        if (mainKwInput) {
            mainKwInput.addEventListener("input", () => {
                clearTimeout(classifyDebounceTimer);
                classifyDebounceTimer = setTimeout(() => {
                    triggerProfessionClassification();
                }, 400);
            });
        }

        const mainLocInput = document.getElementById("location");
        if (mainLocInput) {
            mainLocInput.addEventListener("input", () => {
                clearTimeout(classifyDebounceTimer);
                classifyDebounceTimer = setTimeout(() => {
                    triggerProfessionClassification();
                }, 500);
            });
        }

        // Keep summary badge synchronized
        ["search_source_1", "published_since", "search_radius"].forEach((id) => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener("change", updateFilterSummaryBadge);
            }
        });

        window.addEventListener("beforeunload", () => {
            [searchUi1, searchUi2].filter(Boolean).forEach((ui) => {
                if (ui.pollTimer) {
                    clearInterval(ui.pollTimer);
                }
            });
        });

        function bindAutofillHandler(ui) {
            ui.listEl.addEventListener("click", (e) => {
                const btn = e.target.closest(".job-autofill-btn");
                if (!btn) return;
                const jobUrl = btn.dataset.jobUrl;
                const jobTitle = btn.dataset.jobTitle || "Job Application";
                const jobCompany = btn.dataset.jobCompany || "";
                if (!jobUrl) return;

                window.open(jobUrl, "_blank", "noopener,noreferrer");

                let domain = "";
                try { domain = new URL(jobUrl).hostname; } catch {}

                fetch("/api/autofill/log-application", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        title: jobTitle,
                        company: jobCompany,
                        domain: domain,
                        url: jobUrl,
                        date: new Date().toLocaleDateString("de-DE"),
                        status: "Gestartet (Extension)",
                        fieldsFilled: 0
                    })
                }).catch(() => {});

                btn.textContent = "✓ Geöffnet";
                btn.style.background = "#10b981";
                btn.style.color = "#ffffff";
                setTimeout(() => {
                    btn.textContent = "⚡ Open & Autofill";
                    btn.style.background = "";
                    btn.style.color = "";
                }, 3000);
            });

            // Vibe Radar Handler (Culture & Du vs. Sie)
            ui.listEl.addEventListener("click", async (e) => {
                const btn = e.target.closest(".job-vibe-btn");
                if (!btn) return;
                const card = btn.closest(".job-item");
                if (!card) return;
                const panel = card.querySelector(".job-ai-panel");
                if (!panel) return;

                if (!panel.classList.contains("hidden") && panel.dataset.currentType === "vibe") {
                    panel.classList.add("hidden");
                    return;
                }

                panel.classList.remove("hidden");
                panel.dataset.currentType = "vibe";
                panel.innerHTML = '<span style="color:#64748b;">🧭 Analysiere Unternehmenskultur mit Luna...</span>';

                try {
                    const company = btn.dataset.company || "";
                    const title = btn.dataset.title || "";
                    const resp = await fetch("/api/pdf/culture-vibe", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ company_name: company, job_title: title })
                    });
                    const data = await resp.json();
                    if (!resp.ok || !data.success) throw new Error(data.error || "Fehler beim Vibe-Check");

                    const costLabel = data.from_cache ? "⚡ Aus Cache ($0.00)" : `⚡ ${data.usage?.total_tokens || 30} Tokens ($${(data.usage?.estimated_cost_usd || 0.00001).toFixed(6)})`;

                    panel.innerHTML = `
                        <div class="vibe-card-inner">
                            <div class="vibe-tag-row">
                                <span class="vibe-pill vibe-pill-tag">${data.icon || '🏢'} ${escapeHtml(data.vibe)}</span>
                                <span class="vibe-pill vibe-pill-formality">Anrede: ${escapeHtml(data.formality)}</span>
                            </div>
                            <div class="vibe-tip-text">💡 <strong>Empfehlung:</strong> ${escapeHtml(data.tone_tip)}</div>
                            <div class="ai-cost-tag">${costLabel}</div>
                        </div>
                    `;
                } catch (err) {
                    panel.innerHTML = `<span style="color:#ef4444;">${escapeHtml(err.message)}</span>`;
                }
            });

            // ATS Heatmap Handler (Match & Skill Radar)
            ui.listEl.addEventListener("click", async (e) => {
                const btn = e.target.closest(".job-heatmap-btn");
                if (!btn) return;
                const card = btn.closest(".job-item");
                if (!card) return;
                const panel = card.querySelector(".job-ai-panel");
                if (!panel) return;

                if (!panel.classList.contains("hidden") && panel.dataset.currentType === "heatmap") {
                    panel.classList.add("hidden");
                    return;
                }

                panel.classList.remove("hidden");
                panel.dataset.currentType = "heatmap";
                panel.innerHTML = '<span style="color:#64748b;">📊 Berechne ATS Heatmap mit Luna...</span>';

                try {
                    const company = btn.dataset.company || "";
                    const title = btn.dataset.title || "";
                    const resp = await fetch("/api/pdf/ats-heatmap", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ company_name: company, job_title: title, requirements: title })
                    });
                    const data = await resp.json();
                    if (!resp.ok || !data.success) throw new Error(data.error || "Fehler beim Heatmap-Berechnen");

                    const costLabel = data.from_cache ? "⚡ Aus Cache ($0.00)" : `⚡ ${data.usage?.total_tokens || 60} Tokens ($${(data.usage?.estimated_cost_usd || 0.00002).toFixed(6)})`;

                    const matchedPills = (data.matched || []).map(m => `<span class="heatmap-pill heatmap-pill-match">✓ ${escapeHtml(m)}</span>`).join("");
                    const transferPills = (data.transferable || []).map(t => `<span class="heatmap-pill heatmap-pill-transfer">≈ ${escapeHtml(t)}</span>`).join("");
                    const gapPills = (data.gaps || []).map(g => `<span class="heatmap-pill heatmap-pill-gap">○ ${escapeHtml(g)}</span>`).join("");

                    panel.innerHTML = `
                        <div class="heatmap-card-inner">
                            <div class="heatmap-score-bar">
                                <span>🎯 ATS Eignungs-Score</span>
                                <span class="heatmap-score-pill">${data.match_percent}% Match</span>
                            </div>
                            <div class="heatmap-pills-wrap">
                                ${matchedPills}
                                ${transferPills}
                                ${gapPills}
                            </div>
                            <div class="heatmap-tip-box">
                                💡 <strong>Bridge-Tipp:</strong> ${escapeHtml(data.bridge_tip)}
                            </div>
                            <div class="ai-cost-tag">${costLabel}</div>
                        </div>
                    `;
                } catch (err) {
                    panel.innerHTML = `<span style="color:#ef4444;">${escapeHtml(err.message)}</span>`;
                }
            });

            // Single Job "⚡ Anschreiben" button handler
            ui.listEl.addEventListener("click", async (e) => {
                const btn = e.target.closest(".job-single-anschreiben-btn");
                if (!btn) return;
                const idx = parseInt(btn.dataset.index, 10);
                const job = ui.lastJobs && ui.lastJobs[idx];
                if (!job) return;

                const orig = btn.textContent;
                btn.disabled = true;
                btn.textContent = "⚡ Übertrage...";
                try {
                    await transferJobsToCoverLetterStudio(ui, [job]);
                } finally {
                    btn.disabled = false;
                    btn.textContent = orig;
                }
            });
        }

        bindAutofillHandler(searchUi1);
        if (searchUi2) bindAutofillHandler(searchUi2);

        restoreIndexState();
        bindIndexStatePersistence();
        handleSearchSourceChange();

        // Auto-reconnect to active/paused auto-extraction job and load previous tasks
        (async function reconnectActiveAutoJob() {
            try {
                loadPreviousTasks(searchUi1);
                // Periodically refresh previous tasks list in background
                setInterval(() => {
                    loadPreviousTasks(searchUi1);
                }, 6000);

                let activeId = "";
                let activeRunId = "";
                if (searchUi1.currentSearchRunId) {
                    try {
                        activeId = localStorage.getItem("jobscout_active_auto_job_id_" + searchUi1.currentSearchRunId) || "";
                    } catch (_) {}
                }
                if (!activeId) {
                    const actUrl = searchUi1.currentSearchRunId
                        ? `/api/inline/auto-jobs/active?search_run_id=${encodeURIComponent(searchUi1.currentSearchRunId)}`
                        : "/api/inline/auto-jobs/active";
                    const actResp = await fetch(actUrl);
                    const actData = await actResp.json();
                    if (actData.has_active && actData.job_id && actData.status === "running") {
                        activeId = actData.job_id;
                        activeRunId = actData.search_run_id || "";
                    }
                }
                if (!activeId) return;

                // Session Isolation: Do not attach active extraction task to a different search run
                if (activeRunId && searchUi1.currentSearchRunId && activeRunId !== searchUi1.currentSearchRunId) {
                    return;
                }

                const stResp = await fetch(`/api/inline/auto-jobs/status/${encodeURIComponent(activeId)}`);
                const stData = await stResp.json();
                if (stData.success && stData.job && (stData.job.is_running || stData.job.current_index > 0)) {
                    if (stData.job.search_run_id && searchUi1.currentSearchRunId && stData.job.search_run_id !== searchUi1.currentSearchRunId) {
                        return;
                    }
                    searchUi1.autoJobId = activeId;
                    searchUi1.progressPanel.classList.add("visible");
                    renderAutoProgress(searchUi1, stData.job);
                    if (stData.job.is_running) {
                        if (searchUi1.pollTimer) clearInterval(searchUi1.pollTimer);
                        searchUi1.pollTimer = setInterval(() => { pollAutoProgress(searchUi1); }, 1500);
                    }
                }
            } catch (_) {}
        })();

        const srcElInit = document.getElementById("search_source_1");
        if (srcElInit) {
            srcElInit.addEventListener("change", handleSearchSourceChange);
        }

        return {
            show() {
                const url = new URL(window.location.href);
                const requested = url.pathname === "/google-maps" ? "google_maps" : url.searchParams.get("source");
                if (srcElInit && ["all", "job_portals", "google_maps"].includes(requested)) {
                    srcElInit.value = requested;
                }
                handleSearchSourceChange();
            },
            hide() {
            },
        };
    };

    window.SPASections = sections;
})();

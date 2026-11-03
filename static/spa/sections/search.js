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

            // 5. Google Maps Live Crawler
            if (progressData.google_maps_metrics) {
                const gm = progressData.google_maps_metrics;
                const gmCard = document.getElementById("mon_gmaps_monitor");
                if (gmCard) gmCard.style.display = "block";
                const cityEl = document.getElementById("mon_gmaps_city");
                if (cityEl) cityEl.textContent = gm.city || "-";
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
                exportBtn.href = `/api/search/download?filter=${encodeURIComponent(activeFilter)}`;
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

        function renderAutoProgress(ui, data) {
            ui.progressPanel.classList.add("visible");
            ui.processedEl.textContent = String(data.current_index || 0);
            ui.emailsEl.textContent = String(data.emails_found || 0);
            ui.captchaEl.textContent = String(data.captchas_solved || 0);
            ui.failedEl.textContent = String(data.failed || 0);

            const pct = window.SPAUtils.clampPercent(data.percentage || 0);
            ui.progressFill.style.width = `${pct}%`;
            ui.progressFill.textContent = `${Math.round(pct)}%`;

            if (data.last_error) {
                ui.progressError.textContent = data.last_error;
                ui.progressError.style.display = "block";
            } else {
                ui.progressError.textContent = "";
                ui.progressError.style.display = "none";
            }

            let status = "Idle";
            const isCompleted = !data.is_running && Number(data.current_index || 0) >= Number(data.total_jobs || 0) && Number(data.total_jobs || 0) > 0;
            if (isCompleted) {
                status = "Extraction completed";
            } else if (data.stop_requested) {
                status = "Stopped";
            } else if (data.paused) {
                status = data.last_error ? "Paused - Error" : "Paused";
            } else if (data.is_running) {
                status = `Processing position ${data.current_index}/${data.total_jobs}...`;
            }
            ui.progressStatus.textContent = status;

            // Stop button: ONLY visible while actively running or paused; hidden when extraction is finished or stopped
            if (ui.stopBtn) {
                ui.stopBtn.style.display = (data.is_running || data.paused) ? "inline-flex" : "none";
            }

            // Continue button: ONLY visible when paused
            if (ui.continueBtn) {
                ui.continueBtn.style.display = data.paused ? "inline-flex" : "none";
            }

            // Download button: visible when extraction is finished, stopped, or when idle with collected results
            const canDownload = Boolean(
                isCompleted ||
                data.stop_requested ||
                (!data.is_running && Number(data.current_index || 0) > 0)
            );
            if (ui.downloadBtn) {
                ui.downloadBtn.style.display = (canDownload && !data.is_running) ? "inline-flex" : "none";
            }

            // Go to Cover Letters button: visible when completed or stopped with collected results
            const canGoToAnschreiben = Boolean(!data.is_running && !data.paused && Number(data.current_index || 0) > 0);
            if (ui.anschreibenBtn) {
                ui.anschreibenBtn.style.display = canGoToAnschreiben ? "inline-flex" : "none";
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

                renderAutoProgress(ui, data.job);

                if (!data.job.is_running && !data.job.paused) {
                    if (ui.pollTimer) {
                        clearInterval(ui.pollTimer);
                        ui.pollTimer = null;
                    }
                    setAutoBtnIdle(ui.autoBtn);
                }
            } catch (error) {
                ui.progressError.textContent = error.message || "Statusfehler";
                ui.progressError.style.display = "block";
            }
        }

        async function startAutoExtraction(ui) {
            if (!Array.isArray(ui.lastJobs) || !ui.lastJobs.length) {
                showError(ui, "Please perform a search first to discover job opportunities.");
                return;
            }

            setAutoBtnLoading(ui.autoBtn, "Starte...");

            try {
                const response = await fetch("/api/inline/auto-jobs/start", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        jobs: ui.lastJobs,
                        keyword: ui.keywordEl.value.trim(),
                        location: ui.locationEl.value.trim(),
                        published_since: ui.publishedSinceEl.value,
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

                ui.progressPanel.classList.add("visible");
                if (ui.pollTimer) {
                    clearInterval(ui.pollTimer);
                }
                ui.pollTimer = setInterval(() => {
                    pollAutoProgress(ui);
                }, 1500);
                await pollAutoProgress(ui);
            } catch (error) {
                setAutoBtnIdle(ui.autoBtn);
                showError(ui, error.message || "Auto-Extraktion konnte nicht gestartet werden");
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
            } catch (error) {
                ui.progressError.textContent = error.message || "Fortsetzen fehlgeschlagen";
                ui.progressError.style.display = "block";
            }
        }

        async function stopAndDownloadAuto(ui) {
            if (!ui.autoJobId) {
                ui.progressError.textContent = "Kein aktiver Job auf dieser Seite.";
                ui.progressError.style.display = "block";
                return;
            }

            try {
                const response = await fetch(`/api/inline/auto-jobs/stop/${encodeURIComponent(ui.autoJobId)}`, { method: "POST" });
                const data = await response.json().catch(() => ({}));

                if (!response.ok || !data.success) {
                    throw new Error(data.message || "Stoppen fehlgeschlagen");
                }

                setTimeout(() => {
                    const filterParam = encodeURIComponent(ui.activeFilter || "all");
                    window.location.href = `/api/inline/auto-jobs/download/${encodeURIComponent(ui.autoJobId)}?filter=${filterParam}`;
                }, 1200);
            } catch (error) {
                ui.progressError.textContent = error.message || "Stoppen fehlgeschlagen";
                ui.progressError.style.display = "block";
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

            saveIndexState();
            setLoading(ui, true);

            const searchScope = "both";
            const autoCategoriesEl = document.getElementById("auto_categories_toggle");
            const autoCategories = autoCategoriesEl ? String(autoCategoriesEl.checked) : "true";
            const customCategoriesEl = document.getElementById("custom_categories");
            const customCategories = customCategoriesEl ? customCategoriesEl.value : "";

            const params = new URLSearchParams({
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
                            searchCompleted = true;
                            setSearchProgress(ui, {
                                percent: 100,
                                stage: `Fertig: ${data.total || 0} Stellen gefunden!`,
                                found: data.total || 0,
                            });
                            renderResults(ui, data);
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

                        searchCompleted = true;
                        setSearchProgress(ui, {
                            percent: 100,
                            stage: `Fertig: ${data.total || 0} Stellen gefunden!`,
                            found: data.total || 0,
                        });
                        renderResults(ui, data);
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
            emailsEl: document.getElementById("emails_1"),
            captchaEl: document.getElementById("captcha_1"),
            failedEl: document.getElementById("failed_1"),
            progressFill: document.getElementById("progress_fill_1"),
            progressStatus: document.getElementById("progress_status_1"),
            progressError: document.getElementById("progress_error_1"),
            stopBtn: document.getElementById("stop_btn_1"),
            continueBtn: document.getElementById("continue_btn_1"),
            downloadBtn: document.getElementById("download_btn_1"),
            anschreibenBtn: document.getElementById("anschreiben_btn_1"),
            generateCoverLettersBtn: document.getElementById("btn_generate_cover_letters_1"),
            filterBar: document.getElementById("results_filter_bar_1"),
            activeFilter: "all",
            lastJobs: [],
            autoJobId: "",
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
            await startAutoExtraction(searchUi1);
        });

        searchUi1.continueBtn.addEventListener("click", async () => {
            await continueAutoExtraction(searchUi1);
        });

        searchUi1.stopBtn.addEventListener("click", async () => {
            await stopAndDownloadAuto(searchUi1);
        });

        searchUi1.downloadBtn.addEventListener("click", () => {
            if (!searchUi1.autoJobId) {
                return;
            }
            const filterParam = encodeURIComponent(searchUi1.activeFilter || "all");
            window.location.href = `/api/inline/auto-jobs/download/${encodeURIComponent(searchUi1.autoJobId)}?filter=${filterParam}`;
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

            searchUi2.downloadBtn.addEventListener("click", () => {
                if (!searchUi2.autoJobId) {
                    return;
                }
                const filterParam = encodeURIComponent(searchUi2.activeFilter || "all");
                window.location.href = `/api/inline/auto-jobs/download/${encodeURIComponent(searchUi2.autoJobId)}?filter=${filterParam}`;
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

        const srcElInit = document.getElementById("search_source_1");
        if (srcElInit) {
            srcElInit.addEventListener("change", handleSearchSourceChange);
        }

        return sections.createSearchSources();
    };

    window.SPASections = sections;
})();

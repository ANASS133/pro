(function () {
    const sections = window.SPASections || {};

    sections.createAusbildungenSection = function createAusbildungenSection() {
        const filesRoot = document.getElementById("ausbildungen-files");
        const emptyState = document.getElementById("ausbildungen-empty");
        const statusNode = document.getElementById("ausbildungen-status");

        // Enhanced elements
        const statTotalFiles = document.getElementById("ab-stat-total-files");
        const statTotalRows = document.getElementById("ab-stat-total-rows");
        const statTotalSize = document.getElementById("ab-stat-total-size");
        const searchInput = document.getElementById("ausbildung-search-input");
        const searchClearBtn = document.getElementById("ausbildung-search-clear");
        const topicChipsRoot = document.getElementById("ab-topic-chips");
        const sortSelect = document.getElementById("ab-sort-select");
        const viewGridBtn = document.getElementById("ab-view-grid");
        const viewTableBtn = document.getElementById("ab-view-table");

        const batchBar = document.getElementById("ab-batch-bar");
        const selectAllCheckbox = document.getElementById("ab-select-all-checkbox");
        const batchSelectedCount = document.getElementById("ab-batch-selected-count");
        const batchRowsPreview = document.getElementById("ab-batch-rows-preview");
        const deleteSourcesCheckbox = document.getElementById("ab-delete-sources-checkbox");
        const btnBatchMerge = document.getElementById("btn-batch-merge");
        const btnClearSelection = document.getElementById("btn-clear-selection");

        // Preview Modal elements
        const previewModal = document.getElementById("ausbildung-preview-modal");
        const modalDialog = document.getElementById("ab-modal-dialog");
        const previewTitle = document.getElementById("ab-preview-title");
        const previewFilename = document.getElementById("ab-preview-filename");
        const previewStats = document.getElementById("ab-preview-stats");
        const previewColCount = document.getElementById("ab-preview-col-count");
        const previewMaximizeBtn = document.getElementById("ab-preview-maximize-btn");
        const maximizeLabel = document.getElementById("ab-maximize-label");
        const previewDownloadBtn = document.getElementById("ab-preview-download-btn");
        const previewCloseBtn = document.getElementById("ab-preview-close-btn");
        const previewFooterClose = document.getElementById("ab-preview-footer-close");
        const previewSearch = document.getElementById("ab-preview-search");
        const previewCounter = document.getElementById("ab-preview-counter");
        const previewThead = document.getElementById("ab-preview-thead");
        const previewTbody = document.getElementById("ab-preview-tbody");
        const colModeAllBtn = document.getElementById("ab-col-mode-all");
        const colModeCompactBtn = document.getElementById("ab-col-mode-compact");
        const colDropdownBtn = document.getElementById("ab-col-dropdown-btn");
        const colDropdownMenu = document.getElementById("ab-col-dropdown-menu");
        const colCheckboxList = document.getElementById("ab-col-checkbox-list");
        const colSelectAllBtn = document.getElementById("ab-col-select-all");
        const colSelectResetBtn = document.getElementById("ab-col-select-reset");

        if (!filesRoot || !emptyState || !statusNode) {
            return {
                show() {},
                hide() {},
            };
        }

        const escapeHtml = window.SPAUtils.escapeHtml;
        const fetchJson = window.SPAUtils.fetchJson;
        const activePolls = new Map();
        let isVisible = false;
        let isLoading = false;

        // In-memory file cache & filter state
        let allFiles = [];
        let activeTopic = "all";
        let searchQuery = "";
        let sortBy = "newest";
        let viewMode = "grid";
        const selectedFiles = new Set();

        // Preview state
        let currentPreviewRows = [];
        let currentPreviewCols = [];

        function setStatus(message, isError) {
            if (!message) {
                statusNode.hidden = true;
                statusNode.textContent = "";
                statusNode.classList.remove("is-error", "is-success");
                return;
            }

            statusNode.hidden = false;
            statusNode.textContent = message;
            statusNode.classList.toggle("is-error", Boolean(isError));
            statusNode.classList.toggle("is-success", !isError);
        }

        function setIdleState(card) {
            const updateButton = card.querySelector("[data-update-button]");
            const updateSplit = card.querySelector("[data-update-split]");
            const stopButton = card.querySelector("[data-stop-button]");
            const solverLink = card.querySelector("[data-solver-link]");
            const progressWrap = card.querySelector("[data-update-progress]");

            if (updateSplit) updateSplit.hidden = false;
            if (updateButton) {
                updateButton.hidden = false;
                updateButton.disabled = false;
                updateButton.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg> <span>Update</span>';
            }
            if (stopButton) {
                stopButton.hidden = true;
                stopButton.disabled = false;
                stopButton.textContent = "Stop updating";
            }
            if (solverLink) {
                solverLink.hidden = true;
            }
            if (progressWrap) {
                progressWrap.hidden = true;
            }
            card.classList.remove("is-updating");
            card.dataset.jobId = "";
        }

        function setRunningState(card) {
            const updateButton = card.querySelector("[data-update-button]");
            const updateSplit = card.querySelector("[data-update-split]");
            const updateMenu = card.querySelector("[data-update-menu]");
            const stopButton = card.querySelector("[data-stop-button]");

            if (updateMenu) updateMenu.hidden = true;
            if (updateSplit) updateSplit.hidden = true;
            if (updateButton) {
                updateButton.hidden = true;
                updateButton.disabled = true;
            }
            if (stopButton) {
                stopButton.hidden = false;
                stopButton.disabled = false;
                stopButton.textContent = "Stop updating";
            }
            card.classList.add("is-updating");
        }

        function buildStatusText(job) {
            const phase = String(job.phase || "");
            const mode = String(job.mode || "incremental");
            if (phase === "cleaning") {
                return "Bereinige & dedupliziere bestehende Zeilen...";
            }
            if (phase === "searching") {
                const page = Number(job.search_page || 0);
                const fetched = Number(job.search_fetched || 0);
                if (fetched > 0) {
                    return `Suche nach neuen Stellen (Seite ${page} • ${fetched} gefunden)...`;
                }
                return "Suche nach neuen Stellen...";
            }
            if (phase === "extracting") {
                const current = Number(job.current_index || 0);
                const total = Number(job.total_jobs || 0);
                const found = Number(job.emails_found || 0);
                const skipped = Number(job.skipped_known || 0);
                const enriched = Number(job.rows_enriched || 0);
                if (mode === "enrich") {
                    return `Anreicherung ${current}/${total} • +${found} E-Mails • ${enriched} ergänzt`;
                }
                const skipPart = skipped > 0 ? ` • ${skipped} bekannt übersprungen` : "";
                return `Extraktion ${current}/${total} • +${found} E-Mails${skipPart}`;
            }
            if (phase === "saving") {
                return "Datei wird aktualisiert...";
            }
            if (phase === "captcha") {
                return "CAPTCHA detected. Please solve in browser window and confirm.";
            }
            if (phase === "stopping") {
                return "Update wird gestoppt...";
            }
            if (phase === "stopped") {
                return "Update gestoppt.";
            }
            return "Update läuft...";
        }

        function computeJobPercent(job) {
            if (!job) return 0;
            if (typeof job.percent === "number" && job.percent > 0) {
                return Math.min(100, Math.max(4, Math.round(job.percent)));
            }
            const phase = String(job.phase || "");
            if (phase === "searching") return 15;
            if (phase === "extracting") {
                const cur = Number(job.current_index || 0);
                const tot = Math.max(Number(job.total_jobs || 0), 1);
                return Math.min(95, 20 + Math.round((cur / tot) * 75));
            }
            if (phase === "saving") return 96;
            if (phase === "completed") return 100;
            return 8;
        }

        function renderUpdateSplitControl(isRunning) {
            return `
                <div class="ab-update-split" data-update-split ${isRunning ? "hidden" : ""}>
                    <button type="button" class="ab-btn-card-action update-btn" data-update-button ${isRunning ? "hidden" : ""} title="Find new leads (skips already-known listings)">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>
                        <span>Update</span>
                    </button>
                    <button type="button" class="ab-btn-update-caret" data-update-menu-toggle title="Choose update mode" aria-label="Update options">
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"></polyline></svg>
                    </button>
                    <div class="ab-update-menu" data-update-menu hidden>
                        <button type="button" class="ab-update-menu-item" data-update-mode="incremental">
                            <span class="ab-menu-item-title">Find New Leads</span>
                            <span class="ab-menu-item-sub">Crawl portals &amp; skip known rows</span>
                        </button>
                        <button type="button" class="ab-update-menu-item" data-update-mode="enrich">
                            <span class="ab-menu-item-title">Enrich Missing Contacts</span>
                            <span class="ab-menu-item-sub">Re-crawl incomplete rows in file</span>
                        </button>
                        <button type="button" class="ab-update-menu-item" data-update-mode="clean">
                            <span class="ab-menu-item-title">Clean &amp; Deduplicate</span>
                            <span class="ab-menu-item-sub">Instant repair &amp; deduplication</span>
                        </button>
                    </div>
                </div>
            `;
        }

        // Formatting and topic calculation
        function formatDomainTitle(rawName) {
            if (!rawName) return "Dataset";
            let text = String(rawName).trim();
            // Strip leading ID numbers or timestamps, e.g. 740944, 20261028_121614_...
            text = text.replace(/^[\d_-]+\s*/g, "").trim();
            if (!text) return "Dataset";

            // Clean up corrupted umlauts and scrape stem artifacts
            text = text
                .replace(/\bf\s*r\b/gi, "für")
                .replace(/\bk\s*lte\b/gi, "Kälte")
                .replace(/\bmechatroniker\s+f[uü]r\s+k[aä]lte\s+und\s+klimatechnik\b/gi, "Mechatroniker für Kälte- und Klimatechnik")
                .replace(/\bfachinformatiker\s+anwendungsentwicklung\b/gi, "Fachinformatiker Anwendungsentwicklung")
                .replace(/\bfachinformatiker\s+systemintegration\b/gi, "Fachinformatiker Systemintegration")
                .replace(/\bfachinformatiker\b/gi, "Fachinformatiker")
                .replace(/\bmechatroniker\b/gi, "Mechatroniker")
                .replace(/\bkoch\b/gi, "Koch");

            // Standardize "ausbildung als" / "ausbildung zu" prefix
            if (/^ausbildung\s+(als\s+|zu\s+|zum\s+|zur\s+)?/i.test(text)) {
                text = text.replace(/^ausbildung\s+(als\s+|zu\s+|zum\s+|zur\s+)?/i, "Ausbildung: ");
            } else if (!/^ausbildung/i.test(text)) {
                text = "Ausbildung: " + text.charAt(0).toUpperCase() + text.slice(1);
            }

            // Ensure first letter after "Ausbildung: " is capitalized
            text = text.replace(/^Ausbildung:\s*([a-zäöü])/i, (_, c) => `Ausbildung: ${c.toUpperCase()}`);

            return text;
        }

        function getTopicKey(dn) {
            if (!dn) return "";
            let clean = String(dn).toLowerCase().replace(/^[\d_-]+\s*/g, "").trim();
            if (clean.includes("mechatronik")) return "mechatroniker";
            if (clean.includes("fachinformatik") || clean.includes("informatik")) return "fachinformatiker";
            if (clean.includes("koch") || clean.includes("köch")) return "koch";
            if (clean.includes("suchergebnisse")) return "suchergebnisse";
            if (clean.includes("aluminium") || clean.includes("alu")) return "aluminiumbauer";

            clean = clean
                .replace(/^ausbildung\s+(als\s+|zu\s+|zum\s+|zur\s+)?/i, "")
                .replace(/^ausbildung\s*/i, "")
                .replace(/^stellenangebote?\s*/i, "")
                .trim();

            const words = clean.split(/\s+/).filter(w => !/^\d+$/.test(w) && w.length > 2);
            return words[0] || "";
        }

        function getFilteredFiles() {
            const filtered = allFiles.filter(item => {
                // Search query match
                if (searchQuery) {
                    const q = searchQuery.toLowerCase();
                    const text = `${item.filename || ""} ${item.domain_name || ""}`.toLowerCase();
                    if (!text.includes(q)) return false;
                }

                // Topic chip filter
                if (activeTopic !== "all") {
                    const key = getTopicKey(item.domain_name);
                    const d = (item.domain_name || "").toLowerCase();
                    if (key !== activeTopic && !d.includes(activeTopic.toLowerCase())) {
                        return false;
                    }
                }

                return true;
            });

            return filtered.slice().sort((a, b) => {
                if (sortBy === "rows") {
                    return (Number(b.row_count) || 0) - (Number(a.row_count) || 0);
                }
                if (sortBy === "size") {
                    return (Number(b.size_kb) || 0) - (Number(a.size_kb) || 0);
                }
                if (sortBy === "name") {
                    return formatDomainTitle(a.domain_name).localeCompare(formatDomainTitle(b.domain_name));
                }
                // "newest": compare modified_at or filename timestamp descending
                const fa = String(a.filename || "");
                const fb = String(b.filename || "");
                return fb.localeCompare(fa);
            });
        }

        function updateStatsAndChips() {
            const filtered = getFilteredFiles();
            const totalFiles = allFiles.length;
            const totalRows = allFiles.reduce((acc, f) => acc + (Number(f.row_count) || 0), 0);
            const totalSize = allFiles.reduce((acc, f) => acc + (Number(f.size_kb) || 0), 0);

            if (statTotalFiles) statTotalFiles.textContent = String(totalFiles);
            if (statTotalRows) statTotalRows.textContent = totalRows.toLocaleString();
            if (statTotalSize) statTotalSize.textContent = `${Math.round(totalSize)} KB`;

            // Build dynamic topic chips
            if (topicChipsRoot) {
                const topicCounts = new Map();
                allFiles.forEach(f => {
                    const key = getTopicKey(f.domain_name);
                    if (key) {
                        topicCounts.set(key, (topicCounts.get(key) || 0) + 1);
                    }
                });

                let html = `<button type="button" class="ab-chip ${activeTopic === "all" ? "is-active" : ""}" data-topic="all">All (${totalFiles})</button>`;
                topicCounts.forEach((count, key) => {
                    let label = key;
                    if (key === "mechatroniker") label = "Mechatroniker";
                    else if (key === "fachinformatiker") label = "Fachinformatiker";
                    else if (key === "koch") label = "Koch";
                    else if (key === "suchergebnisse") label = "Suchergebnisse";
                    else if (key === "aluminiumbauer") label = "Aluminiumbauer";
                    else label = key.charAt(0).toUpperCase() + key.slice(1);

                    const isActive = activeTopic === key ? "is-active" : "";
                    html += `<button type="button" class="ab-chip ${isActive}" data-topic="${escapeHtml(key)}">${escapeHtml(label)} (${count})</button>`;
                });
                topicChipsRoot.innerHTML = html;
            }
        }

        function updateBatchBar() {
            if (!batchBar) return;
            const filtered = getFilteredFiles();
            const selectedInFiltered = filtered.filter(f => selectedFiles.has(f.filename));

            if (selectedFiles.size >= 2) {
                batchBar.hidden = false;
                if (batchSelectedCount) {
                    batchSelectedCount.textContent = `${selectedFiles.size} files selected`;
                }
                if (batchRowsPreview) {
                    const rowsEst = allFiles
                        .filter(f => selectedFiles.has(f.filename))
                        .reduce((acc, f) => acc + (Number(f.row_count) || 0), 0);
                    batchRowsPreview.textContent = `(~${rowsEst} total leads)`;
                }
                if (selectAllCheckbox) {
                    selectAllCheckbox.checked = filtered.length > 0 && selectedInFiltered.length === filtered.length;
                    selectAllCheckbox.indeterminate = selectedInFiltered.length > 0 && selectedInFiltered.length < filtered.length;
                }
            } else if (selectedFiles.size === 1) {
                batchBar.hidden = false;
                if (batchSelectedCount) {
                    batchSelectedCount.textContent = "1 file selected (select at least 2 to merge)";
                }
                if (batchRowsPreview) batchRowsPreview.textContent = "";
                if (btnBatchMerge) btnBatchMerge.disabled = true;
                return;
            } else {
                batchBar.hidden = true;
                if (selectAllCheckbox) {
                    selectAllCheckbox.checked = false;
                    selectAllCheckbox.indeterminate = false;
                }
            }
            if (btnBatchMerge) btnBatchMerge.disabled = selectedFiles.size < 2;
        }

        function getFileExtension(filename) {
            const parts = String(filename || "").split(".");
            return parts.length > 1 ? parts.pop().toUpperCase() : "XLSX";
        }

        function formatShortId(filename) {
            const name = String(filename || "").replace(/\.[^.]+$/, "");
            const hashMatch = name.match(/_([a-f0-9]{6,10})$/i);
            if (hashMatch) return `#${hashMatch[1]}`;
            const timeMatch = name.match(/^\d{8}_(\d{6})/);
            if (timeMatch) {
                const t = timeMatch[1];
                return `${t.slice(0, 2)}:${t.slice(2, 4)}:${t.slice(4, 6)}`;
            }
            return "";
        }

        function formatRowCount(item) {
            const num = Number(item.row_count);
            if (!Number.isNaN(num) && num >= 0 && item.row_count !== null && item.row_count !== undefined && item.row_count !== "") {
                return num.toLocaleString();
            }
            return item.row_count_display || "N/A";
        }

        function renderFileCard(item) {
            const activeJob = item.active_job || null;
            const isRunning = Boolean(activeJob && activeJob.is_running);
            const isSelected = selectedFiles.has(item.filename);
            const domainTitle = formatDomainTitle(item.domain_name);
            const ext = getFileExtension(item.filename);
            const shortId = formatShortId(item.filename);
            const rowsFormatted = formatRowCount(item);
            const topicKey = getTopicKey(item.domain_name);
            const topicLabel = topicKey ? (topicKey.charAt(0).toUpperCase() + topicKey.slice(1)) : "Dataset";

            return `
                <article
                    class="ab-file-card file-card ${isSelected ? "is-selected" : ""} ${isRunning ? "is-updating" : ""}"
                    data-export-card
                    data-filename="${escapeHtml(item.filename || "")}"
                    data-job-id="${escapeHtml((activeJob && activeJob.job_id) || "")}"
                >
                    <div class="ab-card-top">
                        <div class="ab-card-top-left">
                            <label class="ab-card-checkbox-wrap" title="Select for merge">
                                <input
                                    type="checkbox"
                                    class="ab-card-checkbox"
                                    data-select-card
                                    ${isSelected ? "checked" : ""}
                                >
                            </label>
                            <span class="ab-format-pill">${escapeHtml(ext)}</span>
                            <span class="ab-topic-pill">${escapeHtml(topicLabel)}</span>
                            ${shortId ? `<span class="ab-short-id" title="${escapeHtml(item.filename || "")}">${escapeHtml(shortId)}</span>` : ""}
                        </div>
                        <button type="button" class="ab-icon-delete-btn" data-delete-btn title="Delete dataset" aria-label="Delete dataset">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                        </button>
                    </div>

                    <div class="ab-card-body">
                        <h2 class="ab-card-title" title="${escapeHtml(item.domain_name || "")}">${escapeHtml(domainTitle)}</h2>
                        <div class="ab-card-metric-row">
                            <div class="ab-lead-metric">
                                <span class="ab-lead-number" data-line-count>${escapeHtml(rowsFormatted)}</span>
                                <span class="ab-lead-unit">leads</span>
                            </div>
                            <span class="ab-size-badge">${escapeHtml(item.size_kb || 0)} KB</span>
                        </div>
                    </div>

                    <div class="ab-card-meta-row">
                        <span class="ab-meta-item" title="Last modified">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>
                            ${escapeHtml(item.modified_at || "N/A")}
                        </span>
                        <span class="ab-meta-filename" title="${escapeHtml(item.filename || "")}">${escapeHtml(item.filename || "")}</span>
                    </div>

                    <div class="ab-card-actions">
                        <button type="button" class="ab-btn-card-action ab-btn-preview" data-preview-btn title="Preview dataset in table">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                            <span>Preview</span>
                        </button>
                        <a href="/api/ausbildungen/file/${encodeURIComponent(item.filename || "")}/download" class="ab-btn-card-action ab-btn-download" title="Download dataset file" download>
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                            <span>Export</span>
                        </a>
                        ${renderUpdateSplitControl(isRunning)}
                        <button type="button" class="stop-btn" data-stop-button ${isRunning ? "" : "hidden"}>Stop updating</button>
                        <a href="/captcha_solve" target="_blank" rel="noopener noreferrer" class="solver-link" data-solver-link hidden>Open CAPTCHA</a>
                    </div>
                    <div class="ab-update-progress" data-update-progress ${isRunning ? "" : "hidden"}>
                        <div class="ab-progress-track">
                            <div class="ab-progress-fill" data-progress-fill style="width: ${isRunning ? computeJobPercent(activeJob) : 0}%"></div>
                        </div>
                    </div>
                    <div class="update-status" data-update-status ${isRunning ? "" : "hidden"}>${isRunning ? escapeHtml(buildStatusText(activeJob)) : ""}</div>
                </article>
            `;
        }

        function renderTableView(items) {
            const rowsHtml = items.map(item => {
                const activeJob = item.active_job || null;
                const isRunning = Boolean(activeJob && activeJob.is_running);
                const isSelected = selectedFiles.has(item.filename);
                const domainTitle = formatDomainTitle(item.domain_name);
                const ext = getFileExtension(item.filename);
                const rowsFormatted = formatRowCount(item);

                return `
                    <tr
                        class="ab-table-row ${isSelected ? "is-selected" : ""}"
                        data-export-card
                        data-filename="${escapeHtml(item.filename || "")}"
                        data-job-id="${escapeHtml((activeJob && activeJob.job_id) || "")}"
                    >
                        <td class="ab-td-check">
                            <input type="checkbox" class="ab-card-checkbox" data-select-card ${isSelected ? "checked" : ""} aria-label="Select ${escapeHtml(item.filename || "")}">
                        </td>
                        <td class="ab-td-name">
                            <div class="ab-table-title-wrap">
                                <span class="ab-format-pill">${escapeHtml(ext)}</span>
                                <div>
                                    <div class="ab-table-title">${escapeHtml(domainTitle)}</div>
                                    <div class="ab-table-sub" title="${escapeHtml(item.filename || "")}">${escapeHtml(item.filename || "")}</div>
                                    <div class="ab-update-progress" data-update-progress ${isRunning ? "" : "hidden"}>
                                        <div class="ab-progress-track">
                                            <div class="ab-progress-fill" data-progress-fill style="width: ${isRunning ? computeJobPercent(activeJob) : 0}%"></div>
                                        </div>
                                    </div>
                                    <div class="update-status" data-update-status>${isRunning ? escapeHtml(buildStatusText(activeJob)) : ""}</div>
                                </div>
                            </div>
                        </td>
                        <td class="ab-td-leads">
                            <span class="ab-table-leads-pill" data-line-count>${escapeHtml(rowsFormatted)}</span>
                        </td>
                        <td class="ab-td-size">${escapeHtml(item.size_kb || 0)} KB</td>
                        <td class="ab-td-date">${escapeHtml(item.modified_at || "N/A")}</td>
                        <td class="ab-td-actions">
                            <div class="ab-table-actions">
                                <button type="button" class="ab-btn-card-action ab-btn-preview" data-preview-btn title="Preview dataset">
                                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                                    <span>Preview</span>
                                </button>
                                <a href="/api/ausbildungen/file/${encodeURIComponent(item.filename || "")}/download" class="ab-btn-card-action ab-btn-download" title="Download" download>
                                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                                    <span>Export</span>
                                </a>
                                ${renderUpdateSplitControl(isRunning)}
                                <button type="button" class="stop-btn" data-stop-button ${isRunning ? "" : "hidden"}>Stop</button>
                                <a href="/captcha_solve" target="_blank" rel="noopener noreferrer" class="solver-link" data-solver-link hidden>CAPTCHA</a>
                                <button type="button" class="ab-icon-delete-btn" data-delete-btn title="Delete dataset">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                                </button>
                            </div>
                        </td>
                    </tr>
                `;
            }).join("");

            return `
                <div class="ab-table-card">
                    <table class="ab-datasets-table">
                        <thead>
                            <tr>
                                <th class="ab-th-check"></th>
                                <th>Dataset</th>
                                <th>Leads</th>
                                <th>Size</th>
                                <th>Last Updated</th>
                                <th class="ab-th-actions">Actions</th>
                            </tr>
                        </thead>
                        <tbody>${rowsHtml}</tbody>
                    </table>
                </div>
            `;
        }

        function renderGrid() {
            const filtered = getFilteredFiles();
            emptyState.hidden = filtered.length > 0;
            if (filtered.length === 0) {
                if (searchQuery || activeTopic !== "all") {
                    emptyState.textContent = "No apprenticeship datasets match the current filter.";
                } else {
                    emptyState.textContent = "No exported apprenticeship datasets found.";
                }
            }
            if (viewMode === "table") {
                filesRoot.classList.remove("ab-files-grid");
                filesRoot.classList.add("ab-files-table-wrap");
                filesRoot.innerHTML = filtered.length ? renderTableView(filtered) : "";
            } else {
                filesRoot.classList.remove("ab-files-table-wrap");
                filesRoot.classList.add("ab-files-grid");
                filesRoot.innerHTML = filtered.map(renderFileCard).join("");
            }
            updateStatsAndChips();
            updateBatchBar();
        }

        function stopAllPolls() {
            activePolls.forEach((timer) => {
                window.clearInterval(timer);
            });
            activePolls.clear();
        }

        function updateCardFromJob(card, job) {
            const statusNodeLocal = card.querySelector("[data-update-status]");
            const lineCount = card.querySelector("[data-line-count]");
            const stopButton = card.querySelector("[data-stop-button]");
            const solverLink = card.querySelector("[data-solver-link]");
            const progressWrap = card.querySelector("[data-update-progress]");
            const progressFill = card.querySelector("[data-progress-fill]");

            if (!statusNodeLocal) return;
            statusNodeLocal.hidden = false;

            if (lineCount && Number(job.result_rows || 0) > 0) {
                const countFormatted = Number(job.result_rows || 0).toLocaleString();
                lineCount.textContent = countFormatted;
            }

            card.dataset.jobId = String(job.job_id || "");
            const mode = String(job.mode || "incremental");

            if (job.phase === "completed" && !job.is_running) {
                const newRows = Number(job.new_rows_added || 0);
                const enriched = Number(job.rows_enriched || 0);
                const deduped = Number(job.duplicates_removed || 0);
                const skipped = Number(job.skipped_known || 0);
                statusNodeLocal.className = "update-status success";
                if (mode === "clean") {
                    statusNodeLocal.textContent = `Bereinigt: ${deduped} Duplikate entfernt • ${enriched} Zeilen repariert.`;
                } else if (mode === "enrich") {
                    statusNodeLocal.textContent = `Fertig: ${enriched} Zeilen angereichert (+${Number(job.emails_found || 0)} E-Mails).`;
                } else {
                    const skipNote = skipped > 0 ? ` (${skipped} bekannt übersprungen)` : "";
                    statusNodeLocal.textContent = `Fertig. ${newRows} neue Leads hinzugefügt${skipNote}.`;
                }
                setIdleState(card);
                return;
            }

            if (job.phase === "stopped" && !job.is_running) {
                const newRows = Number(job.new_rows_added || 0);
                const enriched = Number(job.rows_enriched || 0);
                statusNodeLocal.className = "update-status";
                if (mode === "enrich" && enriched > 0) {
                    statusNodeLocal.textContent = `Gestoppt. ${enriched} Zeilen angereichert.`;
                } else {
                    statusNodeLocal.textContent = newRows > 0
                        ? `Gestoppt. ${newRows} neue E-Mails gespeichert.`
                        : "Update gestoppt.";
                }
                setIdleState(card);
                return;
            }

            if (job.phase === "failed" && !job.is_running) {
                statusNodeLocal.className = "update-status error";
                statusNodeLocal.textContent = job.last_error || "Update fehlgeschlagen.";
                setIdleState(card);
                return;
            }

            setRunningState(card);
            if (progressWrap) {
                progressWrap.hidden = false;
                if (progressFill) {
                    progressFill.style.width = `${computeJobPercent(job)}%`;
                }
            }
            if (stopButton && job.phase === "stopping") {
                stopButton.disabled = true;
                stopButton.textContent = "Stoppen...";
            }
            if (solverLink) {
                solverLink.hidden = job.phase !== "captcha";
            }
            statusNodeLocal.className = "update-status";
            statusNodeLocal.textContent = buildStatusText(job);
        }

        async function pollJob(jobId, filename) {
            const key = `${filename}:${jobId}`;
            if (activePolls.has(key)) {
                window.clearInterval(activePolls.get(key));
            }

            const poll = async () => {
                const card = filesRoot.querySelector(`[data-export-card][data-filename="${CSS.escape(filename)}"]`);
                if (!card) {
                    if (activePolls.has(key)) {
                        window.clearInterval(activePolls.get(key));
                        activePolls.delete(key);
                    }
                    return;
                }

                try {
                    const payload = await fetchJson(`/api/ausbildungen/update/${encodeURIComponent(jobId)}`);
                    if (!payload.success || !payload.job) {
                        throw new Error(payload.message || "Failed to load update status");
                    }

                    const job = payload.job;
                    updateCardFromJob(card, job);

                    if (!job.is_running) {
                        if (activePolls.has(key)) {
                            window.clearInterval(activePolls.get(key));
                            activePolls.delete(key);
                        }
                        window.setTimeout(() => {
                            if (isVisible) {
                                loadFiles();
                            }
                        }, 800);
                    }
                } catch (error) {
                    const statusNodeLocal = card.querySelector("[data-update-status]");
                    if (statusNodeLocal) {
                        statusNodeLocal.className = "update-status error";
                        statusNodeLocal.textContent = error.message || "Could not load update status.";
                    }
                    setIdleState(card);
                    if (activePolls.has(key)) {
                        window.clearInterval(activePolls.get(key));
                        activePolls.delete(key);
                    }
                }
            };

            await poll();
            activePolls.set(key, window.setInterval(poll, 2500));
        }

        async function loadFiles() {
            if (isLoading) return;

            isLoading = true;
            stopAllPolls();

            try {
                const payload = await fetchJson("/api/ausbildungen/files");
                if (!payload.success || !Array.isArray(payload.files)) {
                    throw new Error(payload.message || "Failed to load exported datasets");
                }

                allFiles = payload.files;
                window.dispatchEvent(new CustomEvent("ausbildungDatasetsChanged", {
                    detail: { files: allFiles, updatedAt: payload.updated_at }
                }));
                renderGrid();
                setStatus("", false);

                allFiles.forEach((item) => {
                    if (item.active_job && item.active_job.job_id && item.active_job.is_running) {
                        pollJob(String(item.active_job.job_id), String(item.filename || "")).catch(() => {});
                    }
                });
            } catch (error) {
                setStatus(error.message || "Failed to load exported datasets.", true);
            } finally {
                isLoading = false;
            }
        }

        // Preview state
        let activeCols = [];
        let colDisplayMode = "all"; // 'all' | 'compact' | 'custom'
        let currentFilteredRows = [];

        const CANONICAL_COL_ORDER = [
            "title",
            "company",
            "location",
            "city",
            "email",
            "phone",
            "contact_person",
            "arbeitsgeber",
            "anrede",
            "application_method",
            "bewerbung_art",
            "direct_application_url",
            "employer_website",
            "employer_website_url",
            "job_listing_url",
            "apply_url",
            "form_link",
            "bewerbung_link",
            "source",
            "start_date",
            "published_date",
            "vacancies",
            "salary",
            "validation_status",
            "validation_reason",
            "application_url_type",
            "has_form",
            "required_documents",
            "extraction_status",
            "postal_code",
        ];

        const COMPACT_PREFERRED_COLS = [
            "title",
            "company",
            "location",
            "email",
            "application_method",
            "direct_application_url",
            "apply_url",
            "job_listing_url",
        ];

        function sortColumnsByCanonical(rawCols) {
            const rawSet = new Set(rawCols || []);
            const ordered = [];
            for (const col of CANONICAL_COL_ORDER) {
                if (rawSet.has(col)) {
                    ordered.push(col);
                    rawSet.delete(col);
                }
            }
            // Append any other columns in the dataset not in canonical list
            for (const col of rawCols || []) {
                if (rawSet.has(col)) {
                    ordered.push(col);
                }
            }
            return ordered;
        }

        function getCompactCols(orderedCols) {
            const compact = [];
            for (const col of COMPACT_PREFERRED_COLS) {
                if (orderedCols.includes(col) && !compact.includes(col)) {
                    compact.push(col);
                    if (compact.length >= 6) break;
                }
            }
            return compact.length > 0 ? compact : orderedCols.slice(0, 6);
        }

        // Preview Modal functionality
        async function openPreview(filename) {
            if (!previewModal) return;
            previewTitle.textContent = "Loading preview...";
            previewFilename.textContent = filename;
            previewStats.textContent = "";
            if (previewColCount) previewColCount.textContent = "";
            previewThead.innerHTML = "";
            previewTbody.innerHTML = '<tr><td colspan="8" class="ab-table-empty">Lade Datensätze...</td></tr>';
            previewModal.hidden = false;
            if (previewDownloadBtn) {
                previewDownloadBtn.href = `/api/ausbildungen/file/${encodeURIComponent(filename)}/download`;
            }

            try {
                const res = await fetchJson(`/api/ausbildungen/file/${encodeURIComponent(filename)}/preview`);
                if (!res.ok && !res.success) {
                    throw new Error(res.message || "Failed to load preview");
                }

                currentPreviewCols = sortColumnsByCanonical(res.columns || []);
                currentPreviewRows = res.rows || [];
                currentFilteredRows = currentPreviewRows;

                // Default to ALL columns so user can see every single column
                colDisplayMode = "all";
                activeCols = [...currentPreviewCols];

                previewTitle.textContent = "Dataset Preview";
                previewStats.textContent = `${res.total_rows} rows • ${res.email_count} with email`;

                syncColumnModeButtons();
                buildColumnDropdownMenu();
                updateCounterText();
                renderPreviewRows(currentPreviewRows);
            } catch (err) {
                previewTbody.innerHTML = `<tr><td colspan="8" class="ab-table-empty is-error">Failed to load preview: ${escapeHtml(err.message)}</td></tr>`;
            }
        }

        function syncColumnModeButtons() {
            if (colModeAllBtn) colModeAllBtn.classList.toggle("active", colDisplayMode === "all");
            if (colModeCompactBtn) colModeCompactBtn.classList.toggle("active", colDisplayMode === "compact");
            if (previewColCount) {
                previewColCount.textContent = `${activeCols.length} of ${currentPreviewCols.length} Columns`;
            }
        }

        function updateCounterText() {
            if (!previewCounter) return;
            const q = previewSearch ? previewSearch.value.trim() : "";
            if (q) {
                previewCounter.textContent = `Filtered: ${currentFilteredRows.length} of ${currentPreviewRows.length} entries (${activeCols.length} cols)`;
            } else {
                previewCounter.textContent = `Showing ${currentPreviewRows.length} entries (${activeCols.length} cols)`;
            }
        }

        function buildColumnDropdownMenu() {
            if (!colCheckboxList) return;
            colCheckboxList.innerHTML = currentPreviewCols.map(col => {
                const checked = activeCols.includes(col) ? "checked" : "";
                const label = formatColHeader(col);
                return `
                    <label class="ab-col-checkbox-item">
                        <input type="checkbox" data-col="${escapeHtml(col)}" ${checked}>
                        <span>${escapeHtml(label)}</span>
                    </label>
                `;
            }).join("");

            // Attach checkbox change handlers
            colCheckboxList.querySelectorAll('input[type="checkbox"]').forEach(input => {
                input.addEventListener("change", (e) => {
                    const col = e.target.dataset.col;
                    if (e.target.checked) {
                        if (!activeCols.includes(col)) {
                            // Maintain canonical ordering
                            const next = new Set([...activeCols, col]);
                            activeCols = currentPreviewCols.filter(c => next.has(c));
                        }
                    } else {
                        if (activeCols.length <= 1) {
                            e.target.checked = true;
                            return; // keep at least 1 column
                        }
                        activeCols = activeCols.filter(c => c !== col);
                    }
                    colDisplayMode = "custom";
                    syncColumnModeButtons();
                    updateCounterText();
                    renderPreviewRows(currentFilteredRows);
                });
            });
        }

        function updateDropdownCheckboxes() {
            if (!colCheckboxList) return;
            colCheckboxList.querySelectorAll('input[type="checkbox"]').forEach(input => {
                input.checked = activeCols.includes(input.dataset.col);
            });
        }

        function formatUrlCell(val, col) {
            if (!val || typeof val !== "string") return "-";
            const trimmed = val.trim();
            if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) {
                return escapeHtml(trimmed);
            }
            let label = "Open ↗";
            try {
                const u = new URL(trimmed);
                if (col === "direct_application_url") {
                    label = "Apply URL ↗";
                } else if (col === "form_link") {
                    label = "Form ↗";
                } else if (col === "employer_website" || col === "employer_website_url") {
                    label = u.hostname.replace(/^www\./, "");
                } else if (col === "job_listing_url") {
                    label = "Job Ad ↗";
                } else {
                    label = u.hostname.replace(/^www\./, "");
                }
            } catch {
                label = "Open ↗";
            }
            return `<a href="${escapeHtml(trimmed)}" target="_blank" rel="noopener noreferrer" class="ab-cell-link-pill" title="${escapeHtml(trimmed)}"><span>${escapeHtml(label)}</span> ↗</a>`;
        }

        function renderPreviewRows(rows) {
            if (!previewThead || !previewTbody) return;

            const colsToShow = activeCols.length > 0 ? activeCols : currentPreviewCols;

            // Render Header with Sticky Index (#)
            previewThead.innerHTML = `
                <tr>
                    <th class="ab-col-idx">#</th>
                    ${colsToShow.map(c => `<th>${escapeHtml(formatColHeader(c))}</th>`).join("")}
                </tr>
            `;

            if (!rows || rows.length === 0) {
                previewTbody.innerHTML = `<tr><td colspan="${colsToShow.length + 1}" class="ab-table-empty">No matching rows in preview.</td></tr>`;
                return;
            }

            previewTbody.innerHTML = rows.map((r, idx) => {
                const email = String(r.email || "").trim();
                const hasEmail = Boolean(email && email.includes("@") && !email.toLowerCase().includes("failed"));
                const appMethod = String(r.application_method || r.bewerbung_art || "").toLowerCase().trim();

                return `
                    <tr>
                        <td class="ab-row-idx">${idx + 1}</td>
                        ${colsToShow.map(col => {
                            const val = String(r[col] !== undefined && r[col] !== null ? r[col] : "").trim();

                            if (col === "email") {
                                return hasEmail
                                    ? `<td><span class="ab-email-badge" title="${escapeHtml(val)}">✉️ ${escapeHtml(val)}</span></td>`
                                    : `<td><span class="ab-no-email">No email</span></td>`;
                            }

                            if (col === "phone") {
                                return val
                                    ? `<td><a href="tel:${escapeHtml(val)}" class="ab-phone-badge" title="${escapeHtml(val)}">📞 ${escapeHtml(val)}</a></td>`
                                    : `<td><span class="ab-no-email">-</span></td>`;
                            }

                            if (col === "application_method" || col === "bewerbung_art") {
                                const m = val.toLowerCase() || appMethod || "unknown";
                                let pillClass = "method-unknown";
                                if (m.includes("form") || m === "direct_application_form") pillClass = "method-form";
                                else if (m.includes("portal") || m.includes("login")) pillClass = "method-portal";
                                else if (m.includes("both")) pillClass = "method-both";
                                else if (m.includes("email") || m.includes("e-mail")) pillClass = "method-email";
                                else if (m.includes("link") || m.includes("external")) pillClass = "method-external";
                                return `<td><span class="ab-method-pill ${pillClass}">${escapeHtml(val || appMethod || "-")}</span></td>`;
                            }

                            if (col === "validation_status" || col === "extraction_status") {
                                const st = val.toLowerCase();
                                let stClass = "status-no-contact";
                                let stLabel = val || "No Status";
                                if (st.includes("verified_email") || st === "email") {
                                    stClass = "status-verified-email";
                                    stLabel = "✓ Verified Email";
                                } else if (st.includes("verified_form") || st.includes("application_form")) {
                                    stClass = "status-verified-form";
                                    stLabel = "✓ Verified Form";
                                } else if (st.includes("verified_application_link") || st.includes("verified_link")) {
                                    stClass = "status-verified-link";
                                    stLabel = "✓ Verified Link";
                                } else if (st.includes("portal_login") || st.includes("portal")) {
                                    stClass = "status-portal";
                                    stLabel = "Portal Login";
                                } else if (st.includes("region_restricted")) {
                                    stClass = "status-region";
                                    stLabel = "Region Restricted";
                                } else if (st.includes("manual_review") || st.includes("manual_required")) {
                                    stClass = "status-manual-review";
                                    stLabel = "⚠ Manual Review";
                                } else if (st.includes("no_contact")) {
                                    stClass = "status-no-contact";
                                    stLabel = "No Contact";
                                }
                                return `<td><span class="ab-status-badge ${stClass}">${escapeHtml(stLabel)}</span></td>`;
                            }

                            if (col === "source") {
                                return `<td><span class="ab-source-pill" title="${escapeHtml(val)}">${escapeHtml(val || "-")}</span></td>`;
                            }

                            if (col === "has_form") {
                                const isTrue = val === "True" || val === "true" || val === "1" || r[col] === true;
                                return `<td><span class="ab-bool-badge ${isTrue ? 'is-true' : 'is-false'}">${isTrue ? 'Yes' : 'No'}</span></td>`;
                            }

                            if (
                                col === "direct_application_url" ||
                                col === "employer_website" ||
                                col === "employer_website_url" ||
                                col === "job_listing_url" ||
                                col === "apply_url" ||
                                col === "form_link" ||
                                col === "bewerbung_link" ||
                                col === "url"
                            ) {
                                return `<td>${formatUrlCell(val, col)}</td>`;
                            }

                            const cellClass = `ab-cell-text is-${col}`;
                            return `<td class="${cellClass}" title="${escapeHtml(val)}">${escapeHtml(val || "-")}</td>`;
                        }).join("")}
                    </tr>
                `;
            }).join("");
        }

        function formatColHeader(col) {
            const map = {
                title: "Profession / Title",
                company: "Company",
                location: "Location",
                city: "City",
                email: "Email Address",
                phone: "Telephone",
                contact_person: "Contact Person",
                arbeitsgeber: "Contact Person",
                anrede: "Salutation",
                application_method: "Application Method",
                bewerbung_art: "Method",
                direct_application_url: "Direct Application URL",
                employer_website: "Employer Website",
                employer_website_url: "Employer Website",
                job_listing_url: "Job Listing Link",
                apply_url: "Apply Link",
                form_link: "Form Link",
                bewerbung_link: "Application Link",
                source: "Source Portal",
                start_date: "Start Date",
                published_date: "Published Date",
                vacancies: "Vacancies",
                salary: "Salary",
                validation_status: "Validation Status",
                validation_reason: "Validation Reason",
                application_url_type: "URL Type",
                has_form: "Has Online Form",
                required_documents: "Documents",
                extraction_status: "Status",
                postal_code: "PLZ",
            };
            return map[col] || col.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
        }

        function closePreview() {
            if (previewModal) previewModal.hidden = true;
            if (previewSearch) previewSearch.value = "";
            if (modalDialog) modalDialog.classList.remove("is-maximized");
            if (maximizeLabel) maximizeLabel.textContent = "Expand";
            if (colDropdownMenu) colDropdownMenu.hidden = true;
            currentPreviewRows = [];
            currentFilteredRows = [];
        }

        // Search inside preview across all columns
        if (previewSearch) {
            previewSearch.addEventListener("input", (e) => {
                const q = e.target.value.toLowerCase().trim();
                if (!q) {
                    currentFilteredRows = currentPreviewRows;
                    renderPreviewRows(currentPreviewRows);
                    updateCounterText();
                    return;
                }
                currentFilteredRows = currentPreviewRows.filter(row => {
                    return Object.values(row).some(v => String(v || "").toLowerCase().includes(q));
                });
                renderPreviewRows(currentFilteredRows);
                updateCounterText();
            });
        }

        // Maximize / Expand button handler
        if (previewMaximizeBtn) {
            previewMaximizeBtn.addEventListener("click", () => {
                if (!modalDialog) return;
                const isMax = modalDialog.classList.toggle("is-maximized");
                if (maximizeLabel) {
                    maximizeLabel.textContent = isMax ? "Collapse" : "Expand";
                }
            });
        }

        // Column View Mode Toggle: All Columns
        if (colModeAllBtn) {
            colModeAllBtn.addEventListener("click", () => {
                colDisplayMode = "all";
                activeCols = [...currentPreviewCols];
                syncColumnModeButtons();
                updateDropdownCheckboxes();
                updateCounterText();
                renderPreviewRows(currentFilteredRows);
            });
        }

        // Column View Mode Toggle: Compact (6)
        if (colModeCompactBtn) {
            colModeCompactBtn.addEventListener("click", () => {
                colDisplayMode = "compact";
                activeCols = getCompactCols(currentPreviewCols);
                syncColumnModeButtons();
                updateDropdownCheckboxes();
                updateCounterText();
                renderPreviewRows(currentFilteredRows);
            });
        }

        // Column Dropdown Toggle
        if (colDropdownBtn) {
            colDropdownBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                if (colDropdownMenu) {
                    colDropdownMenu.hidden = !colDropdownMenu.hidden;
                }
            });
        }

        // Column Quick Actions: Select All
        if (colSelectAllBtn) {
            colSelectAllBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                colDisplayMode = "all";
                activeCols = [...currentPreviewCols];
                syncColumnModeButtons();
                updateDropdownCheckboxes();
                updateCounterText();
                renderPreviewRows(currentFilteredRows);
            });
        }

        // Column Quick Actions: Reset (Compact)
        if (colSelectResetBtn) {
            colSelectResetBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                colDisplayMode = "compact";
                activeCols = getCompactCols(currentPreviewCols);
                syncColumnModeButtons();
                updateDropdownCheckboxes();
                updateCounterText();
                renderPreviewRows(currentFilteredRows);
            });
        }

        // Close column dropdown on outside click
        document.addEventListener("click", (e) => {
            if (colDropdownMenu && !colDropdownMenu.hidden) {
                if (!colDropdownMenu.contains(e.target) && !colDropdownBtn.contains(e.target)) {
                    colDropdownMenu.hidden = true;
                }
            }
        });

        if (previewCloseBtn) previewCloseBtn.addEventListener("click", closePreview);
        if (previewFooterClose) previewFooterClose.addEventListener("click", closePreview);
        if (previewModal) {
            previewModal.addEventListener("click", (e) => {
                if (e.target === previewModal) closePreview();
            });
        }

        // Delete File
        async function deleteFile(filename) {
            const confirmed = window.confirm(`Are you sure you want to permanently delete "${filename}"?\n\nThis will free up disk space and remove incomplete scrape data.`);
            if (!confirmed) return;

            try {
                // Optimistically remove from selection and in-memory list, re-render immediately
                selectedFiles.delete(filename);
                allFiles = allFiles.filter(f => f.filename !== filename);
                renderGrid();
                window.dispatchEvent(new CustomEvent("ausbildungDatasetsChanged", {
                    detail: { files: allFiles, updatedAt: new Date().toISOString() }
                }));

                const res = await fetchJson(`/api/ausbildungen/file/${encodeURIComponent(filename)}/delete`, {
                    method: "POST",
                });
                if (!res.success) {
                    throw new Error(res.message || "Failed to delete dataset");
                }
                setStatus(`✓ Dataset "${filename}" deleted successfully.`, false);
                await loadFiles();
            } catch (err) {
                setStatus(`Error deleting dataset: ${err.message}`, true);
                await loadFiles();
            }
        }

        // Batch Merge Files
        async function runBatchMerge() {
            if (selectedFiles.size < 2) {
                alert("Please select at least 2 files to merge.");
                return;
            }

            const fileList = Array.from(selectedFiles);
            const deleteSources = deleteSourcesCheckbox ? deleteSourcesCheckbox.checked : false;

            const confirmMsg = `Are you sure you want to merge ${fileList.length} files into a single deduplicated dataset?` +
                (deleteSources ? "\n\nSource files will be permanently deleted after deduplication." : "\n\nSource files will be preserved.");

            if (!window.confirm(confirmMsg)) return;

            btnBatchMerge.disabled = true;
            btnBatchMerge.textContent = "Merging...";

            try {
                const res = await fetchJson("/api/ausbildungen/merge", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        filenames: fileList,
                        delete_sources: deleteSources,
                    }),
                });

                if (!res.success) {
                    throw new Error(res.message || "Merge failed");
                }

                selectedFiles.clear();
                setStatus(`✓ ${res.message} (New file: ${res.merged_filename})`, false);
                await loadFiles();
            } catch (err) {
                setStatus(`Merge error: ${err.message}`, true);
            } finally {
                btnBatchMerge.disabled = false;
                btnBatchMerge.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"></path></svg> <span>Merge &amp; Deduplicate</span>';
            }
        }

        // Crawler Update actions
        async function startUpdate(button, mode = "incremental") {
            const card = button.closest("[data-export-card]");
            const filename = String((card && card.dataset.filename) || "").trim();
            const statusNodeLocal = card && card.querySelector("[data-update-status]");
            const progressWrap = card && card.querySelector("[data-update-progress]");
            const progressFill = card && card.querySelector("[data-progress-fill]");

            if (!card || !filename || !statusNodeLocal) return;

            setRunningState(card);
            statusNodeLocal.hidden = false;
            statusNodeLocal.className = "update-status";
            if (mode === "clean") {
                statusNodeLocal.textContent = "Bereinige & dedupliziere...";
            } else if (mode === "enrich") {
                statusNodeLocal.textContent = "Starte Anreicherung unvollständiger Zeilen...";
            } else {
                statusNodeLocal.textContent = "Suche nach neuen Stellen...";
            }
            if (progressWrap) {
                progressWrap.hidden = false;
                if (progressFill) progressFill.style.width = "6%";
            }

            try {
                const payload = await fetchJson("/api/ausbildungen/update", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ filename, mode }),
                });
                if (!payload.success || !payload.job_id) {
                    throw new Error(payload.message || "Failed to start update");
                }

                card.dataset.jobId = String(payload.job_id);
                await pollJob(String(payload.job_id), filename);
            } catch (error) {
                setIdleState(card);
                statusNodeLocal.className = "update-status error";
                statusNodeLocal.textContent = error.message || "Failed to start update.";
            }
        }

        async function stopUpdate(button) {
            const card = button.closest("[data-export-card]");
            const jobId = String((card && card.dataset.jobId) || "").trim();
            const statusNodeLocal = card && card.querySelector("[data-update-status]");

            if (!card || !jobId || !statusNodeLocal) return;

            button.disabled = true;
            button.textContent = "Stopping...";

            try {
                const payload = await fetchJson(`/api/ausbildungen/update/${encodeURIComponent(jobId)}/stop`, {
                    method: "POST",
                });
                if (!payload.success) {
                    throw new Error(payload.message || "Failed to request stop");
                }
                statusNodeLocal.className = "update-status";
                statusNodeLocal.textContent = "Requesting stop...";
            } catch (error) {
                button.disabled = false;
                button.textContent = "Stop updating";
                statusNodeLocal.className = "update-status error";
                statusNodeLocal.textContent = error.message || "Failed to request stop.";
            }
        }

        // Event Listeners
        // 1. Grid Interactions (delegated)
        filesRoot.addEventListener("click", (event) => {
            const card = event.target.closest("[data-export-card]");
            const filename = card ? card.dataset.filename : "";

            // Update mode dropdown toggle
            const menuToggle = event.target.closest("[data-update-menu-toggle]");
            if (menuToggle && card) {
                event.stopPropagation();
                const menu = card.querySelector("[data-update-menu]");
                const wasOpen = menu && !menu.hidden;
                filesRoot.querySelectorAll("[data-update-menu]").forEach(m => { m.hidden = true; });
                if (menu) menu.hidden = Boolean(wasOpen);
                return;
            }

            // Update mode option click
            const modeItem = event.target.closest("[data-update-mode]");
            if (modeItem && card) {
                event.stopPropagation();
                const chosenMode = modeItem.dataset.updateMode || "incremental";
                const menu = card.querySelector("[data-update-menu]");
                if (menu) menu.hidden = true;
                startUpdate(modeItem, chosenMode).catch(() => {});
                return;
            }

            // Checkbox click
            const checkbox = event.target.closest("[data-select-card]");
            if (checkbox && filename) {
                if (checkbox.checked) {
                    selectedFiles.add(filename);
                    card.classList.add("is-selected");
                } else {
                    selectedFiles.delete(filename);
                    card.classList.remove("is-selected");
                }
                updateBatchBar();
                return;
            }

            // Preview button
            const previewBtn = event.target.closest("[data-preview-btn]");
            if (previewBtn && filename) {
                openPreview(filename);
                return;
            }

            // Delete button
            const deleteBtn = event.target.closest("[data-delete-btn]");
            if (deleteBtn && filename) {
                deleteFile(filename);
                return;
            }

            // Update button (default incremental mode)
            const updateButton = event.target.closest("[data-update-button]");
            if (updateButton) {
                startUpdate(updateButton, "incremental").catch(() => {});
                return;
            }

            // Stop button
            const stopButton = event.target.closest("[data-stop-button]");
            if (stopButton) {
                stopUpdate(stopButton).catch(() => {});
            }
        });

        document.addEventListener("click", (event) => {
            if (!event.target.closest("[data-update-split]")) {
                filesRoot.querySelectorAll("[data-update-menu]").forEach(m => { m.hidden = true; });
            }
        });

        // 2. Toolbar & Filters
        if (searchInput) {
            searchInput.addEventListener("input", (e) => {
                searchQuery = e.target.value.trim();
                if (searchClearBtn) searchClearBtn.hidden = !searchQuery;
                renderGrid();
            });
        }

        if (searchClearBtn) {
            searchClearBtn.addEventListener("click", () => {
                if (searchInput) searchInput.value = "";
                searchQuery = "";
                searchClearBtn.hidden = true;
                renderGrid();
            });
        }

        if (topicChipsRoot) {
            topicChipsRoot.addEventListener("click", (e) => {
                const chip = e.target.closest(".ab-chip");
                if (!chip) return;
                activeTopic = chip.dataset.topic || "all";
                renderGrid();
            });
        }

        if (sortSelect) {
            sortSelect.addEventListener("change", (e) => {
                sortBy = e.target.value || "newest";
                renderGrid();
            });
        }

        function setViewMode(mode) {
            viewMode = mode === "table" ? "table" : "grid";
            if (viewGridBtn) viewGridBtn.classList.toggle("is-active", viewMode === "grid");
            if (viewTableBtn) viewTableBtn.classList.toggle("is-active", viewMode === "table");
            renderGrid();
        }

        if (viewGridBtn) {
            viewGridBtn.addEventListener("click", () => setViewMode("grid"));
        }

        if (viewTableBtn) {
            viewTableBtn.addEventListener("click", () => setViewMode("table"));
        }

        // 3. Batch Merge Bar
        if (selectAllCheckbox) {
            selectAllCheckbox.addEventListener("change", (e) => {
                const filtered = getFilteredFiles();
                if (e.target.checked) {
                    filtered.forEach(f => selectedFiles.add(f.filename));
                } else {
                    filtered.forEach(f => selectedFiles.delete(f.filename));
                }
                renderGrid();
            });
        }

        if (btnClearSelection) {
            btnClearSelection.addEventListener("click", () => {
                selectedFiles.clear();
                renderGrid();
            });
        }

        if (btnBatchMerge) {
            btnBatchMerge.addEventListener("click", runBatchMerge);
        }


        window.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && previewModal && !previewModal.hidden) {
                closePreview();
            }
        });

        window.addEventListener("beforeunload", stopAllPolls);

        return {
            show() {
                isVisible = true;
                loadFiles();
            },
            hide() {
                isVisible = false;
                stopAllPolls();
                closePreview();
            },
        };
    };

    window.SPASections = sections;
})();

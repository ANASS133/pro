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

        const batchBar = document.getElementById("ab-batch-bar");
        const selectAllCheckbox = document.getElementById("ab-select-all-checkbox");
        const batchSelectedCount = document.getElementById("ab-batch-selected-count");
        const batchRowsPreview = document.getElementById("ab-batch-rows-preview");
        const deleteSourcesCheckbox = document.getElementById("ab-delete-sources-checkbox");
        const btnBatchMerge = document.getElementById("btn-batch-merge");
        const btnClearSelection = document.getElementById("btn-clear-selection");

        // Preview Modal elements
        const previewModal = document.getElementById("ausbildung-preview-modal");
        const previewTitle = document.getElementById("ab-preview-title");
        const previewFilename = document.getElementById("ab-preview-filename");
        const previewStats = document.getElementById("ab-preview-stats");
        const previewDownloadBtn = document.getElementById("ab-preview-download-btn");
        const previewCloseBtn = document.getElementById("ab-preview-close-btn");
        const previewFooterClose = document.getElementById("ab-preview-footer-close");
        const previewSearch = document.getElementById("ab-preview-search");
        const previewCounter = document.getElementById("ab-preview-counter");
        const previewThead = document.getElementById("ab-preview-thead");
        const previewTbody = document.getElementById("ab-preview-tbody");

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
            const stopButton = card.querySelector("[data-stop-button]");
            const solverLink = card.querySelector("[data-solver-link]");

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
            card.dataset.jobId = "";
        }

        function setRunningState(card) {
            const updateButton = card.querySelector("[data-update-button]");
            const stopButton = card.querySelector("[data-stop-button]");

            if (updateButton) {
                updateButton.hidden = true;
                updateButton.disabled = true;
            }
            if (stopButton) {
                stopButton.hidden = false;
                stopButton.disabled = false;
                stopButton.textContent = "Stop updating";
            }
        }

        function buildStatusText(job) {
            const phase = String(job.phase || "");
            if (phase === "searching") {
                return "Suche nach neuen Stellen...";
            }
            if (phase === "extracting") {
                const current = Number(job.current_index || 0);
                const total = Number(job.total_jobs || 0);
                const found = Number(job.emails_found || 0);
                const duplicates = Number(job.duplicate_emails || 0);
                return `Suche ${current}/${total} | neue E-Mails: ${found} | Duplikate: ${duplicates}`;
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
            return allFiles.filter(item => {
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

        function renderFileCard(item) {
            const activeJob = item.active_job || null;
            const isRunning = Boolean(activeJob && activeJob.is_running);
            const isSelected = selectedFiles.has(item.filename);
            const domainTitle = formatDomainTitle(item.domain_name);

            return `
                <article
                    class="file-card ${isSelected ? "is-selected" : ""}"
                    data-export-card
                    data-filename="${escapeHtml(item.filename || "")}"
                    data-job-id="${escapeHtml((activeJob && activeJob.job_id) || "")}"
                >
                    <div class="file-top">
                        <label class="ab-card-checkbox-wrap" title="Select for merge">
                            <input
                                type="checkbox"
                                class="ab-card-checkbox"
                                data-select-card
                                ${isSelected ? "checked" : ""}
                            >
                            <span class="file-pill">XLSX</span>
                        </label>
                        <div class="ab-pill-group">
                            <span class="line-count" data-line-count>${escapeHtml(item.row_count_display || "N/A")} rows</span>
                        </div>
                    </div>

                    <h2 title="${escapeHtml(item.domain_name || "")}">${escapeHtml(domainTitle)}</h2>
                    <div class="ab-filename-sub" title="${escapeHtml(item.filename || "")}">${escapeHtml(item.filename || "")}</div>

                    <div class="file-meta">
                        <span>📅 ${escapeHtml(item.modified_at || "N/A")}</span>
                        <span>💾 ${escapeHtml(item.size_kb || 0)} KB</span>
                    </div>

                    <div class="file-actions">
                        <button type="button" class="ab-btn-card-action ab-btn-preview" data-preview-btn title="Preview dataset in table">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                            <span>Preview</span>
                        </button>
                        <a href="/api/ausbildungen/file/${encodeURIComponent(item.filename || "")}/download" class="ab-btn-card-action ab-btn-download" title="Download dataset file" download>
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                            <span>Export</span>
                        </a>
                        <button type="button" class="update-btn" data-update-button ${isRunning ? "hidden" : ""} title="Run web crawler for new emails">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>
                            <span>Update</span>
                        </button>
                        <button type="button" class="stop-btn" data-stop-button ${isRunning ? "" : "hidden"}>Stop</button>
                        <button type="button" class="ab-btn-card-action ab-btn-delete" data-delete-btn title="Delete dataset">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                        </button>
                        <a href="/captcha_solve" target="_blank" rel="noopener noreferrer" class="solver-link" data-solver-link hidden>Open CAPTCHA</a>
                    </div>
                    <div class="update-status" data-update-status>${isRunning ? escapeHtml(buildStatusText(activeJob)) : ""}</div>
                </article>
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
            filesRoot.innerHTML = filtered.map(renderFileCard).join("");
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

            if (!statusNodeLocal) return;

            if (lineCount && Number(job.result_rows || 0) > 0) {
                lineCount.textContent = `${Number(job.result_rows || 0)} rows`;
            }

            card.dataset.jobId = String(job.job_id || "");

            if (job.phase === "completed" && !job.is_running) {
                const newRows = Number(job.new_rows_added || 0);
                statusNodeLocal.className = "update-status success";
                statusNodeLocal.textContent = `Fertig. ${newRows} neue E-Mails hinzugefügt.`;
                setIdleState(card);
                return;
            }

            if (job.phase === "stopped" && !job.is_running) {
                const newRows = Number(job.new_rows_added || 0);
                statusNodeLocal.className = "update-status";
                statusNodeLocal.textContent = newRows > 0
                    ? `Gestoppt. ${newRows} neue E-Mails gespeichert.`
                    : "Update gestoppt.";
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

        // Preview Modal functionality
        async function openPreview(filename) {
            if (!previewModal) return;
            previewTitle.textContent = "Loading preview...";
            previewFilename.textContent = filename;
            previewStats.textContent = "";
            previewThead.innerHTML = "";
            previewTbody.innerHTML = '<tr><td colspan="6" class="ab-table-empty">Lade Datensätze...</td></tr>';
            previewModal.hidden = false;
            if (previewDownloadBtn) {
                previewDownloadBtn.href = `/api/ausbildungen/file/${encodeURIComponent(filename)}/download`;
            }

            try {
                const res = await fetchJson(`/api/ausbildungen/file/${encodeURIComponent(filename)}/preview`);
                if (!res.ok && !res.success) {
                    throw new Error(res.message || "Failed to load preview");
                }

                currentPreviewCols = res.columns || [];
                currentPreviewRows = res.rows || [];

                previewTitle.textContent = "Dataset Preview";
                previewStats.textContent = `${res.total_rows} rows • ${res.email_count} with email`;
                if (previewCounter) {
                    previewCounter.textContent = `Showing ${currentPreviewRows.length} of ${res.total_rows} entries`;
                }

                renderPreviewRows(currentPreviewRows);
            } catch (err) {
                previewTbody.innerHTML = `<tr><td colspan="6" class="ab-table-empty is-error">Failed to load preview: ${escapeHtml(err.message)}</td></tr>`;
            }
        }

        function renderPreviewRows(rows) {
            if (!previewThead || !previewTbody) return;

            // Preferred columns display
            const targetCols = ["title", "company", "location", "email", "application_method", "apply_url"];
            const availableCols = targetCols.filter(col => currentPreviewCols.includes(col));
            const colsToShow = availableCols.length > 0 ? availableCols : currentPreviewCols.slice(0, 6);

            // Render Header
            previewThead.innerHTML = `
                <tr>
                    <th style="width: 40px;">#</th>
                    ${colsToShow.map(c => `<th>${escapeHtml(formatColHeader(c))}</th>`).join("")}
                </tr>
            `;

            if (rows.length === 0) {
                previewTbody.innerHTML = `<tr><td colspan="${colsToShow.length + 1}" class="ab-table-empty">No matching rows in preview.</td></tr>`;
                return;
            }

            previewTbody.innerHTML = rows.map((r, idx) => {
                const email = String(r.email || "").trim();
                const hasEmail = Boolean(email && email.includes("@"));
                const appMethod = String(r.application_method || r.bewerbung_art || "email").toLowerCase();

                return `
                    <tr>
                        <td class="ab-row-idx">${idx + 1}</td>
                        ${colsToShow.map(col => {
                            const val = String(r[col] || "").trim();
                            if (col === "email") {
                                return hasEmail
                                    ? `<td><span class="ab-email-badge">✉️ ${escapeHtml(val)}</span></td>`
                                    : `<td><span class="ab-no-email">No email</span></td>`;
                            }
                            if (col === "application_method") {
                                const pillClass = appMethod.includes("form") ? "method-form" : (appMethod.includes("portal") ? "method-portal" : "method-email");
                                return `<td><span class="ab-method-pill ${pillClass}">${escapeHtml(val || appMethod)}</span></td>`;
                            }
                            if (col === "apply_url" || col === "form_link" || col === "bewerbung_link") {
                                return val ? `<td><a href="${escapeHtml(val)}" target="_blank" rel="noopener noreferrer" class="ab-cell-link">Open ↗</a></td>` : "<td>-</td>";
                            }
                            return `<td class="ab-cell-text" title="${escapeHtml(val)}">${escapeHtml(val || "-")}</td>`;
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
                application_method: "Application Method",
                apply_url: "Link / Portal",
                source: "Source",
            };
            return map[col] || col.charAt(0).toUpperCase() + col.slice(1);
        }

        function closePreview() {
            if (previewModal) previewModal.hidden = true;
            if (previewSearch) previewSearch.value = "";
            currentPreviewRows = [];
        }

        // Search inside preview
        if (previewSearch) {
            previewSearch.addEventListener("input", (e) => {
                const q = e.target.value.toLowerCase().trim();
                if (!q) {
                    renderPreviewRows(currentPreviewRows);
                    if (previewCounter) previewCounter.textContent = `Showing ${currentPreviewRows.length} entries`;
                    return;
                }
                const filtered = currentPreviewRows.filter(row => {
                    return Object.values(row).some(v => String(v || "").toLowerCase().includes(q));
                });
                renderPreviewRows(filtered);
                if (previewCounter) previewCounter.textContent = `Filtered: ${filtered.length} of ${currentPreviewRows.length} entries`;
            });
        }

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
        async function startUpdate(button) {
            const card = button.closest("[data-export-card]");
            const filename = String((card && card.dataset.filename) || "").trim();
            const statusNodeLocal = card && card.querySelector("[data-update-status]");

            if (!card || !filename || !statusNodeLocal) return;

            setRunningState(card);
            statusNodeLocal.className = "update-status";
            statusNodeLocal.textContent = "Starting update...";

            try {
                const payload = await fetchJson("/api/ausbildungen/update", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ filename }),
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

            // Update button
            const updateButton = event.target.closest("[data-update-button]");
            if (updateButton) {
                startUpdate(updateButton).catch(() => {});
                return;
            }

            // Stop button
            const stopButton = event.target.closest("[data-stop-button]");
            if (stopButton) {
                stopUpdate(stopButton).catch(() => {});
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

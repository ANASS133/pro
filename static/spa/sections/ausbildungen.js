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
        const statCandidateName = document.getElementById("ab-stat-candidate-name");
        const statCandidateRole = document.getElementById("ab-stat-candidate-role");

        const searchInput = document.getElementById("ausbildung-search-input");
        const searchClearBtn = document.getElementById("ausbildung-search-clear");
        const btnToggleCandidateFilter = document.getElementById("btn-toggle-candidate-filter");
        const candidateFilterLabel = document.getElementById("candidate-filter-label");
        const candidateMatchCount = document.getElementById("candidate-match-count");
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
        let activeCandidate = null;
        let candidateFilterActive = true;
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
                updateButton.textContent = "Update";
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

        // Active Candidate Retrieval & Matching
        async function fetchActiveCandidate() {
            try {
                const res = await fetch("/api/clients/active");
                if (!res.ok) {
                    activeCandidate = null;
                    updateCandidateDisplay();
                    return;
                }
                const data = await res.json();
                if (data.success && data.applicant) {
                    const app = data.applicant;
                    const personal = app.personal || {};
                    const prof = app.professional_profile || {};
                    activeCandidate = {
                        id: data.client_id || "",
                        name: personal.full_name || `${personal.first_name || ""} ${personal.last_name || ""}`.trim() || "Kandidat",
                        title: prof.current_title || prof.headline || "",
                        fields: Array.isArray(prof.primary_fields) ? prof.primary_fields : [],
                    };
                } else {
                    activeCandidate = null;
                }
            } catch (_) {
                activeCandidate = null;
            }
            updateCandidateDisplay();
        }

        function updateCandidateDisplay() {
            if (!statCandidateName) return;

            if (activeCandidate && activeCandidate.name) {
                statCandidateName.textContent = activeCandidate.name;
                if (statCandidateRole) {
                    statCandidateRole.textContent = activeCandidate.title ? `• ${activeCandidate.title}` : "";
                }
                if (candidateFilterLabel) {
                    candidateFilterLabel.textContent = `⭐ ${activeCandidate.name.split(" ")[0] || "Candidate"} Matches`;
                }
            } else {
                statCandidateName.textContent = "No Candidate Active";
                if (statCandidateRole) statCandidateRole.textContent = "";
                if (candidateFilterLabel) candidateFilterLabel.textContent = "All Datasets";
            }
        }

        function isFileRelevantForCandidate(fileItem) {
            if (!activeCandidate || !activeCandidate.title) {
                return true; // No candidate restriction
            }

            const title = activeCandidate.title.toLowerCase();
            if (title === "bewerber" || title.length < 3) {
                // If generic title, check primary fields
                if (activeCandidate.fields && activeCandidate.fields.length > 0) {
                    const fieldsStr = activeCandidate.fields.join(" ").toLowerCase();
                    const fText = `${fileItem.filename || ""} ${fileItem.domain_name || ""}`.toLowerCase();
                    return activeCandidate.fields.some(f => f.length >= 4 && fText.includes(f.toLowerCase()));
                }
                return true;
            }

            // Extract tokens from candidate title
            const tokens = title
                .replace(/[^a-z0-9äöüß]/gi, " ")
                .split(/\s+/)
                .filter(t => t.length >= 4 && !["fuer", "für", "oder", "und", "junior", "senior"].includes(t));

            const fileText = `${fileItem.filename || ""} ${fileItem.domain_name || ""}`.toLowerCase();

            // Match if any token is found in file name or domain name
            for (const token of tokens) {
                if (fileText.includes(token)) return true;
                // Stemming check e.g. "informatik" matches "fachinformatiker"
                if (token.startsWith("informatik") && fileText.includes("informatik")) return true;
                if (token.startsWith("fachinformatik") && fileText.includes("fachinformatik")) return true;
                if (token.startsWith("koch") && fileText.includes("koch")) return true;
            }

            // Cross-check: does domain name appear in candidate title?
            const domainTokens = (fileItem.domain_name || "")
                .toLowerCase()
                .replace(/[^a-z0-9äöüß]/gi, " ")
                .split(/\s+/)
                .filter(t => t.length >= 4 && !["ausbildung", "platz", "suche", "suchergebnisse"].includes(t));

            return domainTokens.some(dt => title.includes(dt));
        }

        // Filter and topic calculation
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
                    const d = (item.domain_name || "").toLowerCase();
                    if (!d.includes(activeTopic.toLowerCase())) return false;
                }

                // Candidate relevance toggle
                if (candidateFilterActive && activeCandidate && activeCandidate.title && activeCandidate.title.toLowerCase() !== "bewerber") {
                    if (!isFileRelevantForCandidate(item)) return false;
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

            // Candidate match count
            if (candidateMatchCount) {
                const matchCount = allFiles.filter(isFileRelevantForCandidate).length;
                candidateMatchCount.textContent = String(matchCount);
            }

            // Build dynamic topic chips
            if (topicChipsRoot) {
                const topicCounts = new Map();
                allFiles.forEach(f => {
                    const dn = (f.domain_name || "").trim().toLowerCase();
                    let key = "other";
                    if (dn.includes("fachinformatiker") || dn.includes("informatik")) {
                        key = "fachinformatiker";
                    } else if (dn.includes("koch")) {
                        key = "koch";
                    } else if (dn.includes("suchergebnisse")) {
                        key = "suchergebnisse";
                    } else if (dn) {
                        key = dn.split(" ")[0];
                    }
                    topicCounts.set(key, (topicCounts.get(key) || 0) + 1);
                });

                let html = `<button type="button" class="ab-chip ${activeTopic === "all" ? "is-active" : ""}" data-topic="all">All (${totalFiles})</button>`;
                topicCounts.forEach((count, key) => {
                    const label = key === "fachinformatiker" ? "Fachinformatiker" : (key === "koch" ? "Koch" : (key === "suchergebnisse" ? "Suchergebnisse" : key.charAt(0).toUpperCase() + key.slice(1)));
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
            const isRelevant = isFileRelevantForCandidate(item);
            const domainTitle = item.domain_name ? (item.domain_name.charAt(0).toUpperCase() + item.domain_name.slice(1)) : "Datensatz";

            return `
                <article
                    class="file-card ${isSelected ? "is-selected" : ""} ${isRelevant ? "is-candidate-match" : ""}"
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
                            ${isRelevant && activeCandidate && activeCandidate.title ? '<span class="ab-candidate-tag" title="Matches active candidate target role">⭐ Matches</span>' : ""}
                            <span class="line-count" data-line-count>${escapeHtml(item.row_count_display || "k. A.")} Zeilen</span>
                        </div>
                    </div>

                    <h2 title="${escapeHtml(item.domain_name || "")}">${escapeHtml(domainTitle)}</h2>
                    <div class="ab-filename-sub" title="${escapeHtml(item.filename || "")}">${escapeHtml(item.filename || "")}</div>

                    <div class="file-meta">
                        <span>📅 ${escapeHtml(item.modified_at || "N/A")}</span>
                        <span>💾 ${escapeHtml(item.size_kb || 0)} KB</span>
                    </div>

                    <div class="file-actions">
                        <button type="button" class="ab-btn-card-action ab-btn-preview" data-preview-btn title="Datensätze in Tabelle ansehen">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                            <span>Vorschau</span>
                        </button>
                        <a href="/api/ausbildungen/file/${encodeURIComponent(item.filename || "")}/download" class="ab-btn-card-action ab-btn-download" title="Datei herunterladen" download>
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                            <span>Export</span>
                        </a>
                        <button type="button" class="update-btn" data-update-button ${isRunning ? "hidden" : ""} title="Webcrawler für neue E-Mails ausführen">Update</button>
                        <button type="button" class="stop-btn" data-stop-button ${isRunning ? "" : "hidden"}>Stop</button>
                        <button type="button" class="ab-btn-card-action ab-btn-delete" data-delete-btn title="Test-Scrap löschen">
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
                if (searchQuery || candidateFilterActive || activeTopic !== "all") {
                    emptyState.textContent = "Keine Ausbildungs-Dateien entsprechen den gewählten Filtern.";
                } else {
                    emptyState.textContent = "Keine exportierten Ausbildungs-Dateien gefunden.";
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
                lineCount.textContent = `${Number(job.result_rows || 0)} Zeilen`;
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
                        throw new Error(payload.message || "Status konnte nicht geladen werden");
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
                        statusNodeLocal.textContent = error.message || "Update-Status konnte nicht geladen werden.";
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
                await fetchActiveCandidate();
                const payload = await fetchJson("/api/ausbildungen/files");
                if (!payload.success || !Array.isArray(payload.files)) {
                    throw new Error(payload.message || "Exportdateien konnten nicht geladen werden");
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
                setStatus(error.message || "Exportdateien konnten nicht geladen werden.", true);
            } finally {
                isLoading = false;
            }
        }

        // Preview Modal functionality
        async function openPreview(filename) {
            if (!previewModal) return;
            previewTitle.textContent = "Lade Vorschau...";
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
                    throw new Error(res.message || "Vorschau konnte nicht geladen werden");
                }

                currentPreviewCols = res.columns || [];
                currentPreviewRows = res.rows || [];

                previewTitle.textContent = "Datensatz-Vorschau";
                previewStats.textContent = `${res.total_rows} Zeilen • ${res.email_count} mit E-Mail`;
                if (previewCounter) {
                    previewCounter.textContent = `Zeige ${currentPreviewRows.length} von ${res.total_rows} Einträgen`;
                }

                renderPreviewRows(currentPreviewRows);
            } catch (err) {
                previewTbody.innerHTML = `<tr><td colspan="6" class="ab-table-empty is-error">Fehler beim Laden: ${escapeHtml(err.message)}</td></tr>`;
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
                previewTbody.innerHTML = `<tr><td colspan="${colsToShow.length + 1}" class="ab-table-empty">Keine passenden Zeilen in der Vorschau.</td></tr>`;
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
                                    : `<td><span class="ab-no-email">Keine E-Mail</span></td>`;
                            }
                            if (col === "application_method") {
                                const pillClass = appMethod.includes("form") ? "method-form" : (appMethod.includes("portal") ? "method-portal" : "method-email");
                                return `<td><span class="ab-method-pill ${pillClass}">${escapeHtml(val || appMethod)}</span></td>`;
                            }
                            if (col === "apply_url" || col === "form_link" || col === "bewerbung_link") {
                                return val ? `<td><a href="${escapeHtml(val)}" target="_blank" rel="noopener noreferrer" class="ab-cell-link">Öffnen ↗</a></td>` : "<td>-</td>";
                            }
                            return `<td class="ab-cell-text" title="${escapeHtml(val)}">${escapeHtml(val || "-")}</td>`;
                        }).join("")}
                    </tr>
                `;
            }).join("");
        }

        function formatColHeader(col) {
            const map = {
                title: "Beruf / Stelle",
                company: "Unternehmen",
                location: "Ort",
                city: "Stadt",
                email: "E-Mail Adresse",
                application_method: "Bewerbungsart",
                apply_url: "Link / Portal",
                source: "Quelle",
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
                    if (previewCounter) previewCounter.textContent = `Zeige ${currentPreviewRows.length} Einträge`;
                    return;
                }
                const filtered = currentPreviewRows.filter(row => {
                    return Object.values(row).some(v => String(v || "").toLowerCase().includes(q));
                });
                renderPreviewRows(filtered);
                if (previewCounter) previewCounter.textContent = `Gefiltert: ${filtered.length} von ${currentPreviewRows.length} Einträgen`;
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
            const confirmed = window.confirm(`Möchten Sie die Datei "${filename}" wirklich unwiderruflich löschen?\n\nDies bereinigt den Speicher und entfernt unvollständige Test-Scraps.`);
            if (!confirmed) return;

            try {
                const res = await fetchJson(`/api/ausbildungen/file/${encodeURIComponent(filename)}/delete`, {
                    method: "POST",
                });
                if (!res.success) {
                    throw new Error(res.message || "Datei konnte nicht gelöscht werden");
                }
                selectedFiles.delete(filename);
                setStatus(`✓ Datei "${filename}" wurde erfolgreich gelöscht.`, false);
                await loadFiles();
            } catch (err) {
                setStatus(`Fehler beim Löschen: ${err.message}`, true);
            }
        }

        // Batch Merge Files
        async function runBatchMerge() {
            if (selectedFiles.size < 2) {
                alert("Bitte wählen Sie mindestens 2 Dateien zum Zusammenführen aus.");
                return;
            }

            const fileList = Array.from(selectedFiles);
            const deleteSources = deleteSourcesCheckbox ? deleteSourcesCheckbox.checked : false;

            const confirmMsg = `Möchten Sie ${fileList.length} Dateien zu einem bereinigten Datensatz zusammenführen?` +
                (deleteSources ? "\n\nDie Quell-Dateien werden nach der Deduplizierung automatisch gelöscht." : "\n\nDie Quell-Dateien bleiben erhalten.");

            if (!window.confirm(confirmMsg)) return;

            btnBatchMerge.disabled = true;
            btnBatchMerge.textContent = "Führe zusammen...";

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
                    throw new Error(res.message || "Zusammenführen fehlgeschlagen");
                }

                selectedFiles.clear();
                setStatus(`✓ ${res.message} (Neue Datei: ${res.merged_filename})`, false);
                await loadFiles();
            } catch (err) {
                setStatus(`Merge-Fehler: ${err.message}`, true);
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
            statusNodeLocal.textContent = "Update wird gestartet...";

            try {
                const payload = await fetchJson("/api/ausbildungen/update", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ filename }),
                });
                if (!payload.success || !payload.job_id) {
                    throw new Error(payload.message || "Update konnte nicht gestartet werden");
                }

                card.dataset.jobId = String(payload.job_id);
                await pollJob(String(payload.job_id), filename);
            } catch (error) {
                setIdleState(card);
                statusNodeLocal.className = "update-status error";
                statusNodeLocal.textContent = error.message || "Update konnte nicht gestartet werden.";
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
                    throw new Error(payload.message || "Stop konnte nicht angefordert werden");
                }
                statusNodeLocal.className = "update-status";
                statusNodeLocal.textContent = "Stop wird angefordert...";
            } catch (error) {
                button.disabled = false;
                button.textContent = "Stop updating";
                statusNodeLocal.className = "update-status error";
                statusNodeLocal.textContent = error.message || "Stop konnte nicht angefordert werden.";
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

        if (btnToggleCandidateFilter) {
            btnToggleCandidateFilter.addEventListener("click", () => {
                candidateFilterActive = !candidateFilterActive;
                btnToggleCandidateFilter.classList.toggle("is-active", candidateFilterActive);
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

(function () {
    const sections = window.SPASections || {};

    sections.createAusbildungenSection = function createAusbildungenSection() {
        const filesRoot = document.getElementById("ausbildungen-files");
        const emptyState = document.getElementById("ausbildungen-empty");
        const statusNode = document.getElementById("ausbildungen-status");

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

        function setStatus(message, isError) {
            if (!message) {
                statusNode.hidden = true;
                statusNode.textContent = "";
                statusNode.classList.remove("is-error");
                return;
            }

            statusNode.hidden = false;
            statusNode.textContent = message;
            statusNode.classList.toggle("is-error", Boolean(isError));
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
                return "CAPTCHA gefunden. Bitte im Selenium-Fenster loesen und dann bestaetigen.";
            }
            if (phase === "stopping") {
                return "Update wird gestoppt...";
            }
            if (phase === "stopped") {
                return "Update gestoppt.";
            }
            return "Update laeuft...";
        }

        function renderFileCard(item) {
            const activeJob = item.active_job || null;
            const isRunning = Boolean(activeJob && activeJob.is_running);
            return `
                <article
                    class="file-card"
                    data-export-card
                    data-filename="${escapeHtml(item.filename || "")}"
                    data-job-id="${escapeHtml(activeJob && activeJob.job_id || "")}"
                >
                    <div class="file-top">
                        <span class="file-pill">FILE</span>
                        <span class="line-count" data-line-count>${escapeHtml(item.row_count_display || "k. A.")} Zeilen</span>
                    </div>
                    <h2>${escapeHtml(item.domain_name || "unbekannt")}</h2>
                    <div class="file-meta">
                        Geaendert: ${escapeHtml(item.modified_at || "k. A.")}<br>
                        Groesse: ${escapeHtml(item.size_kb || 0)} KB
                    </div>
                    <div class="file-actions">
                        <button type="button" class="update-btn" data-update-button ${isRunning ? "hidden" : ""}>Update</button>
                        <button type="button" class="stop-btn" data-stop-button ${isRunning ? "" : "hidden"}>Stop updating</button>
                        <a href="/captcha_solve" target="_blank" rel="noopener noreferrer" class="solver-link" data-solver-link hidden>Open CAPTCHA</a>
                    </div>
                    <div class="update-status${isRunning ? "" : ""}" data-update-status>${isRunning ? escapeHtml(buildStatusText(activeJob)) : ""}</div>
                </article>
            `;
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

            if (!statusNodeLocal) {
                return;
            }

            if (lineCount && Number(job.result_rows || 0) > 0) {
                lineCount.textContent = `${Number(job.result_rows || 0)} Zeilen`;
            }

            card.dataset.jobId = String(job.job_id || "");

            if (job.phase === "completed" && !job.is_running) {
                const newRows = Number(job.new_rows_added || 0);
                statusNodeLocal.className = "update-status success";
                statusNodeLocal.textContent = `Fertig. ${newRows} neue E-Mails hinzugefuegt.`;
                setIdleState(card);
                return;
            }

            if (job.phase === "stopped" && !job.is_running) {
                const newRows = Number(job.new_rows_added || 0);
                statusNodeLocal.className = "update-status";
                statusNodeLocal.textContent = newRows > 0
                    ? `Gestoppt. ${newRows} neue E-Mails wurden bereits gespeichert.`
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
                stopButton.textContent = "Stopping...";
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
            if (isLoading) {
                return;
            }

            isLoading = true;
            stopAllPolls();

            try {
                const payload = await fetchJson("/api/ausbildungen/files");
                if (!payload.success || !Array.isArray(payload.files)) {
                    throw new Error(payload.message || "Exportdateien konnten nicht geladen werden");
                }

                const files = payload.files;
                emptyState.hidden = files.length > 0;
                filesRoot.innerHTML = files.map(renderFileCard).join("");
                setStatus("", false);

                files.forEach((item) => {
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

        async function startUpdate(button) {
            const card = button.closest("[data-export-card]");
            const filename = String(card && card.dataset.filename || "").trim();
            const statusNodeLocal = card && card.querySelector("[data-update-status]");

            if (!card || !filename || !statusNodeLocal) {
                return;
            }

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
            const jobId = String(card && card.dataset.jobId || "").trim();
            const statusNodeLocal = card && card.querySelector("[data-update-status]");

            if (!card || !jobId || !statusNodeLocal) {
                return;
            }

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

        // --- Ausbildung.de Integration Elements ---
        const tabBtnAdb = document.getElementById("tab-btn-ausbildung-de");
        const tabBtnFiles = document.getElementById("tab-btn-ausbildung-files");
        const panelAdb = document.getElementById("panel-ausbildung-de-search");
        const panelFiles = document.getElementById("panel-ausbildung-files");

        const adbKeywordEl = document.getElementById("adb_keyword");
        const adbLocationEl = document.getElementById("adb_location");
        const adbMaxJobsEl = document.getElementById("adb_max_jobs");
        const adbSearchBtn = document.getElementById("adb_search_btn");
        const adbLoadingEl = document.getElementById("adb_loading");
        const adbResultsContainer = document.getElementById("adb_results_container");
        const adbResultsMeta = document.getElementById("adb_results_meta");
        const adbResultsList = document.getElementById("adb_results_list");
        const adbErrorEl = document.getElementById("adb_error");
        const adbExportCsvBtn = document.getElementById("adb_export_csv");
        const adbExportJsonBtn = document.getElementById("adb_export_json");

        let lastAdbJobs = [];

        // Tab Switching
        if (tabBtnAdb && tabBtnFiles && panelAdb && panelFiles) {
            tabBtnAdb.addEventListener("click", () => {
                tabBtnAdb.classList.add("is-active");
                tabBtnFiles.classList.remove("is-active");
                panelAdb.style.display = "block";
                panelFiles.style.display = "none";
            });

            tabBtnFiles.addEventListener("click", () => {
                tabBtnFiles.classList.add("is-active");
                tabBtnAdb.classList.remove("is-active");
                panelAdb.style.display = "none";
                panelFiles.style.display = "block";
                loadFiles();
            });
        }

        // Search Ausbildungs-Portale (Ausbildung.de & Azubiyo.de)
        async function runAusbildungDeSearch() {
            if (!adbKeywordEl) return;
            const keyword = adbKeywordEl.value.trim();
            const location = adbLocationEl ? adbLocationEl.value.trim() : "";
            const maxJobs = adbMaxJobsEl ? adbMaxJobsEl.value : 40;
            const portalEl = document.getElementById("adb_portal");
            const portal = portalEl ? portalEl.value : "all";

            if (!keyword) {
                if (adbErrorEl) {
                    adbErrorEl.textContent = "Bitte einen Ausbildungsberuf oder ein Stichwort eingeben.";
                    adbErrorEl.style.display = "block";
                }
                return;
            }

            if (adbErrorEl) adbErrorEl.style.display = "none";
            if (adbLoadingEl) adbLoadingEl.style.display = "block";
            if (adbSearchBtn) {
                adbSearchBtn.disabled = true;
                adbSearchBtn.textContent = "Suche läuft...";
            }

            try {
                const params = new URLSearchParams({
                    keyword,
                    location,
                    max_jobs: maxJobs,
                });

                let combinedJobs = [];

                if (portal === "azubiyo") {
                    const res = await fetch(`/api/azubiyo/search?${params.toString()}`);
                    if (!res.ok) throw new Error(`Azubiyo HTTP ${res.status}`);
                    const data = await res.json();
                    combinedJobs = data.jobs || [];
                } else if (portal === "ausbildung_de") {
                    const res = await fetch(`/api/ausbildung-de/search?${params.toString()}`);
                    if (!res.ok) throw new Error(`Ausbildung.de HTTP ${res.status}`);
                    const data = await res.json();
                    combinedJobs = data.jobs || [];
                } else if (portal === "aubi_plus") {
                    const res = await fetch(`/api/aubi-plus/search?${params.toString()}`);
                    if (!res.ok) throw new Error(`AUBI-plus HTTP ${res.status}`);
                    const data = await res.json();
                    combinedJobs = data.jobs || [];
                } else if (portal === "ihk") {
                    const res = await fetch(`/api/ihk/search?${params.toString()}`);
                    if (!res.ok) throw new Error(`IHK HTTP ${res.status}`);
                    const data = await res.json();
                    combinedJobs = data.jobs || [];
                } else {
                    // Fetch all 4 portals in parallel
                    const [resAdb, resAzu, resAubi, resIhk] = await Promise.allSettled([
                        fetch(`/api/ausbildung-de/search?${params.toString()}`).then((r) => r.json()),
                        fetch(`/api/azubiyo/search?${params.toString()}`).then((r) => r.json()),
                        fetch(`/api/aubi-plus/search?${params.toString()}`).then((r) => r.json()),
                        fetch(`/api/ihk/search?${params.toString()}`).then((r) => r.json()),
                    ]);
                    const jobsAdb = (resAdb.status === "fulfilled" && resAdb.value.jobs) ? resAdb.value.jobs : [];
                    const jobsAzu = (resAzu.status === "fulfilled" && resAzu.value.jobs) ? resAzu.value.jobs : [];
                    const jobsAubi = (resAubi.status === "fulfilled" && resAubi.value.jobs) ? resAubi.value.jobs : [];
                    const jobsIhk = (resIhk.status === "fulfilled" && resIhk.value.jobs) ? resIhk.value.jobs : [];
                    
                    const seen = new Set();
                    [...jobsAdb, ...jobsAzu, ...jobsAubi, ...jobsIhk].forEach((j) => {
                        const ref = j.reference || j.url;
                        if (!seen.has(ref)) {
                            seen.add(ref);
                            combinedJobs.push(j);
                        }
                    });
                }

                lastAdbJobs = combinedJobs;

                if (adbResultsMeta) {
                    const portalNames = {
                        azubiyo: "Azubiyo.de",
                        ausbildung_de: "Ausbildung.de",
                        aubi_plus: "AUBI-plus",
                        ihk: "IHK Lehrstellenbörse",
                        all: "allen 4 Portalen (Ausbildung.de, Azubiyo, AUBI-plus, IHK)"
                    };
                    const portalLabel = portalNames[portal] || "den Portalen";
                    adbResultsMeta.textContent = `${lastAdbJobs.length} Ausbildungsstellen auf ${portalLabel} gefunden`;
                }

                if (adbResultsList) {
                    if (!lastAdbJobs.length) {
                        adbResultsList.innerHTML = '<div class="job-item">Keine passenden Ausbildungsplätze auf den ausgewählten Portalen gefunden.</div>';
                    } else {
                        adbResultsList.innerHTML = lastAdbJobs.map((job) => {
                            const title = escapeHtml(job.title || "Ausbildung");
                            const company = escapeHtml(job.company || "k. A.");
                            const locationStr = escapeHtml(job.location || job.city || "Deutschland");
                            const startDate = escapeHtml(job.start_date || "nach Absprache");
                            const vacancies = escapeHtml(job.vacancies || "1 Platz");
                            const salaryStr = job.salary ? ` • Vergütung: <span class="hub-pill pill-success">${escapeHtml(job.salary)}</span>` : "";
                            const rawUrl = String(job.url || "").trim();
                            const url = escapeHtml(rawUrl);

                            const src = String(job.source || "ausbildung.de").toLowerCase();
                            let sourceLabel = "ausbildung.de";
                            let sourceBadgeClass = "source-ausbildung-de";
                            if (src.includes("azubiyo")) {
                                sourceLabel = "azubiyo.de";
                                sourceBadgeClass = "source-azubiyo";
                            } else if (src.includes("aubi")) {
                                sourceLabel = "aubi-plus.de";
                                sourceBadgeClass = "source-aubi-plus";
                            } else if (src.includes("ihk")) {
                                sourceLabel = "ihk.de";
                                sourceBadgeClass = "source-ihk";
                            }

                            const email = String(job.email || "").trim();
                            const hasValidEmail = email && email.includes("@") && !email.toLowerCase().includes("failed") && !email.toLowerCase().includes("error") && !email.toLowerCase().includes("duplicate");

                            let contactBadge = "";
                            let linkHtml = "";

                            if (hasValidEmail) {
                                contactBadge = `<span class="job-contact-pill has-email" title="E-Mail vorhanden">✉️ ${escapeHtml(email)}</span>`;
                                linkHtml = `
                                    <div class="job-actions-row">
                                        ${url ? `<a class="job-link" href="${url}" target="_blank" rel="noopener noreferrer">Stelle ansehen ↗</a>` : ""}
                                        <a class="job-link job-mail-btn" href="mailto:${escapeHtml(email)}?subject=Bewerbung%20als%20${encodeURIComponent(job.title || '')}" title="E-Mail senden">✉️ E-Mail senden</a>
                                        ${url ? `<button type="button" class="job-link job-autofill-btn" data-job-url="${url}" data-job-title="${title}" data-job-company="${company}" title="Stelle öffnen & mit Chrome Extension ausfüllen">⚡ Open & Autofill</button>` : ""}
                                    </div>
                                `;
                            } else {
                                contactBadge = `<span class="job-contact-pill has-form" title="Bewerbung über Online-Formular">📝 Online-Bewerbungsformular</span>`;
                                linkHtml = url
                                    ? `<div class="job-actions-row">
                                        <a class="job-link job-form-apply-btn" href="${url}" target="_blank" rel="noopener noreferrer" title="Bewerbungsformular öffnen">📝 Zum Bewerbungsformular ↗</a>
                                        <button type="button" class="job-link job-autofill-btn" data-job-url="${url}" data-job-title="${title}" data-job-company="${company}" title="Bewerbungsformular öffnen & mit Chrome Extension ausfüllen">⚡ Mit Formular bewerben (Autofill)</button>
                                    </div>`
                                    : `<div class="job-actions-row"><span class="job-no-link">Kein Bewerbungslink hinterlegt</span></div>`;
                            }

                            return `
                                <article class="job-item">
                                    <div class="job-item-header">
                                        <h4 class="job-title">${title}</h4>
                                        <div class="job-badges-wrap">
                                            <span class="job-source-pill ${sourceBadgeClass}">${sourceLabel}</span>
                                            ${contactBadge}
                                        </div>
                                    </div>
                                    <div class="job-meta">
                                        Unternehmen: <strong>${company}</strong><br>
                                        Ort: ${locationStr}<br>
                                        Ausbildungsbeginn: ${startDate} • Verfügbarkeit: <span class="hub-pill">${vacancies}</span>${salaryStr}
                                    </div>
                                    ${linkHtml}
                                </article>
                            `;
                        }).join("");
                    }
                }

                if (adbResultsContainer) adbResultsContainer.style.display = "block";
            } catch (err) {
                if (adbErrorEl) {
                    adbErrorEl.textContent = "Fehler bei der Suche: " + err.message;
                    adbErrorEl.style.display = "block";
                }
            } finally {
                if (adbLoadingEl) adbLoadingEl.style.display = "none";
                if (adbSearchBtn) {
                    adbSearchBtn.disabled = false;
                    adbSearchBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg> Ausbildungsplätze live suchen`;
                }
            }
        }

        adbSearchBtn?.addEventListener("click", runAusbildungDeSearch);

        // Autofill click delegation on Ausbildung.de results
        adbResultsList?.addEventListener("click", (e) => {
            const btn = e.target.closest(".job-autofill-btn");
            if (!btn) return;
            const jobUrl = btn.dataset.jobUrl;
            const jobTitle = btn.dataset.jobTitle || "Ausbildungsplatz";
            const jobCompany = btn.dataset.jobCompany || "";
            if (!jobUrl) return;

            window.open(jobUrl, "_blank", "noopener,noreferrer");

            fetch("/api/autofill/log-application", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    title: jobTitle,
                    company: jobCompany,
                    domain: "ausbildung.de",
                    url: jobUrl,
                    date: new Date().toLocaleDateString("de-DE"),
                    status: "Gestartet (Ausbildung.de)",
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

        // Export Ausbildung.de Results to CSV & JSON
        adbExportCsvBtn?.addEventListener("click", () => {
            if (!lastAdbJobs.length) return;
            const headers = ["Title", "Company", "Location", "StartDate", "Vacancies", "URL"];
            const rows = lastAdbJobs.map(j => [
                `"${(j.title || "").replace(/"/g, '""')}"`,
                `"${(j.company || "").replace(/"/g, '""')}"`,
                `"${(j.location || j.city || "").replace(/"/g, '""')}"`,
                `"${(j.start_date || "").replace(/"/g, '""')}"`,
                `"${(j.vacancies || "").replace(/"/g, '""')}"`,
                `"${(j.url || "").replace(/"/g, '""')}"`
            ]);
            const csvContent = "\uFEFF" + [headers.join(";"), ...rows.map(r => r.join(";"))].join("\r\n");
            const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `ausbildung_de_stellen_${Date.now()}.csv`;
            a.click();
            URL.revokeObjectURL(url);
        });

        adbExportJsonBtn?.addEventListener("click", () => {
            if (!lastAdbJobs.length) return;
            const blob = new Blob([JSON.stringify(lastAdbJobs, null, 2)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `ausbildung_de_stellen_${Date.now()}.json`;
            a.click();
            URL.revokeObjectURL(url);
        });

        filesRoot.addEventListener("click", (event) => {
            const updateButton = event.target.closest("[data-update-button]");
            if (updateButton) {
                startUpdate(updateButton).catch(() => {});
                return;
            }

            const stopButton = event.target.closest("[data-stop-button]");
            if (stopButton) {
                stopUpdate(stopButton).catch(() => {});
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
            },
        };
    };

    window.SPASections = sections;
})();

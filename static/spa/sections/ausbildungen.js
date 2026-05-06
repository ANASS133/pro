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

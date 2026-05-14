(function () {
    const sections = window.SPASections || {};

    sections.createSearchSection = function createSearchSection() {
        const formOne = document.getElementById("search_form_1");
        const formTwo = document.getElementById("search_form_2");

        if (!formOne || !formTwo) {
            return {
                show() {},
                hide() {},
            };
        }

        const escapeHtml = window.SPAUtils.escapeHtml;
        const INDEX_STATE_KEY = "aa_index_form_state_v1";

        function saveIndexState() {
            const state = {
                keyword: document.getElementById("keyword").value,
                location: document.getElementById("location").value,
                published_since: document.getElementById("published_since").value,
                keyword_2: document.getElementById("keyword_2").value,
                location_2: document.getElementById("location_2").value,
                published_since_2: document.getElementById("published_since_2").value,
            };
            localStorage.setItem(INDEX_STATE_KEY, JSON.stringify(state));
        }

        function restoreIndexState() {
            const raw = localStorage.getItem(INDEX_STATE_KEY);
            if (!raw) {
                return;
            }

            try {
                const state = JSON.parse(raw);
                Object.entries(state).forEach(([id, value]) => {
                    const element = document.getElementById(id);
                    if (!element) {
                        return;
                    }
                    if (typeof value === "string" || typeof value === "number") {
                        element.value = String(value);
                    }
                });
            } catch (_error) {
                // Ignore invalid local state.
            }
        }

        function bindIndexStatePersistence() {
            [
                "keyword",
                "location",
                "published_since",
                "keyword_2",
                "location_2",
                "published_since_2",
            ].forEach((id) => {
                const element = document.getElementById(id);
                if (!element) {
                    return;
                }
                element.addEventListener("input", saveIndexState);
                element.addEventListener("change", saveIndexState);
            });
        }

        function publishedSinceLabel(value) {
            const labels = {
                all: "Alle anzeigen",
                today: "Heute",
                yesterday: "Gestern",
                "1week": "1 Woche",
                "2weeks": "2 Wochen",
                "4weeks": "4 Wochen",
            };
            return labels[value] || "Alle anzeigen";
        }

        function setLoading(ui, loading) {
            ui.loadingEl.style.display = loading ? "block" : "none";
            ui.searchBtn.disabled = loading;
            ui.searchBtn.textContent = loading ? "Suche laeuft..." : "Suchen";
        }

        function renderResults(ui, data) {
            ui.resultsBox.classList.add("visible");
            ui.errorEl.style.display = "none";
            ui.lastJobs = Array.isArray(data.jobs) ? data.jobs : [];

            const total = Number(data.total || 0);
            const publishedSince = publishedSinceLabel(data.published_since || "all");
            ui.metaEl.textContent = `${total} Stellen gefunden | Veroeffentlicht seit: ${publishedSince}`;

            if (!ui.lastJobs.length) {
                ui.listEl.innerHTML = '<div class="job-item">Keine Stellen für diese Suche gefunden.</div>';
                ui.autoBtn.style.display = "none";
                return;
            }

            ui.autoBtn.style.display = "inline-flex";
            ui.listEl.innerHTML = ui.lastJobs.map((job) => {
                const title = escapeHtml(job.title || "Ohne Titel");
                const company = escapeHtml(job.company || "k. A.");
                const location = escapeHtml(job.location || "k. A.");
                const scrapedAt = escapeHtml(job.scraped_at || "k. A.");
                const url = escapeHtml(job.url || "");
                const linkHtml = url
                    ? `<a class="job-link" href="${url}" target="_blank" rel="noopener noreferrer">Stelle ansehen</a>`
                    : "";

                return `
                    <article class="job-item">
                        <h4 class="job-title">${title}</h4>
                        <div class="job-meta">Unternehmen: ${company}<br>Ort: ${location}<br>Erfasst: ${scrapedAt}</div>
                        ${linkHtml}
                    </article>
                `;
            }).join("");
        }

        function showError(ui, message) {
            ui.resultsBox.classList.add("visible");
            ui.metaEl.textContent = "";
            ui.listEl.innerHTML = "";
            ui.autoBtn.style.display = "none";
            ui.errorEl.textContent = message || "Suche fehlgeschlagen.";
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

            let status = "Leerlauf";
            if (!data.is_running && Number(data.current_index || 0) >= Number(data.total_jobs || 0) && Number(data.total_jobs || 0) > 0) {
                status = "Extraktion abgeschlossen";
            } else if (data.stop_requested) {
                status = "Gestoppt";
            } else if (data.paused) {
                status = "Pausiert - Fehler";
            } else if (data.is_running) {
                status = `Verarbeite Stelle ${data.current_index}/${data.total_jobs}...`;
            }
            ui.progressStatus.textContent = status;

            ui.continueBtn.style.display = data.paused ? "inline-flex" : "none";
            const canDownload = Boolean(data.stop_requested || (!data.is_running && Number(data.current_index || 0) > 0));
            ui.downloadBtn.style.display = canDownload ? "inline-flex" : "none";
            const canGoToAnschreiben = Boolean(!data.is_running && !data.paused && Number(data.current_index || 0) > 0);
            ui.anschreibenBtn.style.display = canGoToAnschreiben ? "inline-flex" : "none";
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
                    ui.autoBtn.disabled = false;
                    ui.autoBtn.textContent = "Automatisch extrahieren";
                }
            } catch (error) {
                ui.progressError.textContent = error.message || "Statusfehler";
                ui.progressError.style.display = "block";
            }
        }

        async function startAutoExtraction(ui) {
            if (!Array.isArray(ui.lastJobs) || !ui.lastJobs.length) {
                showError(ui, "Bitte zuerst eine Suche ausfuehren, damit Stellen vorliegen.");
                return;
            }

            ui.autoBtn.disabled = true;
            const originalText = ui.autoBtn.textContent;
            ui.autoBtn.textContent = "Starte...";

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
                ui.autoBtn.disabled = false;
                ui.autoBtn.textContent = originalText;
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
                    window.location.href = `/api/inline/auto-jobs/download/${encodeURIComponent(ui.autoJobId)}`;
                }, 1200);
            } catch (error) {
                ui.progressError.textContent = error.message || "Stoppen fehlgeschlagen";
                ui.progressError.style.display = "block";
            }
        }

        async function runInlineSearch(ui) {
            const keyword = ui.keywordEl.value.trim();
            const location = ui.locationEl.value.trim();
            const publishedSince = ui.publishedSinceEl.value;

            if (!keyword) {
                showError(ui, "Bitte ein Stichwort eingeben.");
                return;
            }

            saveIndexState();
            setLoading(ui, true);

            try {
                const params = new URLSearchParams({
                    keyword,
                    location,
                    published_since: publishedSince,
                });
                const response = await fetch(`/api/search?${params.toString()}`);
                const data = await response.json();

                if (!response.ok || data.status !== "success") {
                    throw new Error(data.message || "Suche fehlgeschlagen");
                }

                renderResults(ui, data);
            } catch (error) {
                showError(ui, error.message || "Suche fehlgeschlagen");
            } finally {
                setLoading(ui, false);
            }
        }

        const searchUi1 = {
            form: formOne,
            keywordEl: document.getElementById("keyword"),
            locationEl: document.getElementById("location"),
            publishedSinceEl: document.getElementById("published_since"),
            searchBtn: document.getElementById("search_btn_1"),
            loadingEl: document.getElementById("loading_1"),
            resultsBox: document.getElementById("results_1"),
            metaEl: document.getElementById("results_meta_1"),
            listEl: document.getElementById("results_list_1"),
            errorEl: document.getElementById("results_error_1"),
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
            lastJobs: [],
            autoJobId: "",
            pollTimer: null,
        };

        const searchUi2 = {
            form: formTwo,
            keywordEl: document.getElementById("keyword_2"),
            locationEl: document.getElementById("location_2"),
            publishedSinceEl: document.getElementById("published_since_2"),
            searchBtn: document.getElementById("search_btn_2"),
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
            lastJobs: [],
            autoJobId: "",
            pollTimer: null,
        };

        searchUi1.form.addEventListener("submit", async (event) => {
            event.preventDefault();
            await runInlineSearch(searchUi1);
        });

        searchUi2.form.addEventListener("submit", async (event) => {
            event.preventDefault();
            await runInlineSearch(searchUi2);
        });

        searchUi1.autoBtn.addEventListener("click", async () => {
            await startAutoExtraction(searchUi1);
        });

        searchUi2.autoBtn.addEventListener("click", async () => {
            await startAutoExtraction(searchUi2);
        });

        searchUi1.continueBtn.addEventListener("click", async () => {
            await continueAutoExtraction(searchUi1);
        });
        searchUi2.continueBtn.addEventListener("click", async () => {
            await continueAutoExtraction(searchUi2);
        });

        searchUi1.stopBtn.addEventListener("click", async () => {
            await stopAndDownloadAuto(searchUi1);
        });
        searchUi2.stopBtn.addEventListener("click", async () => {
            await stopAndDownloadAuto(searchUi2);
        });

        searchUi1.downloadBtn.addEventListener("click", () => {
            if (!searchUi1.autoJobId) {
                return;
            }
            window.location.href = `/api/inline/auto-jobs/download/${encodeURIComponent(searchUi1.autoJobId)}`;
        });
        searchUi2.downloadBtn.addEventListener("click", () => {
            if (!searchUi2.autoJobId) {
                return;
            }
            window.location.href = `/api/inline/auto-jobs/download/${encodeURIComponent(searchUi2.autoJobId)}`;
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

        window.addEventListener("beforeunload", () => {
            [searchUi1, searchUi2].forEach((ui) => {
                if (ui.pollTimer) {
                    clearInterval(ui.pollTimer);
                }
            });
        });

        restoreIndexState();
        bindIndexStatePersistence();

        return {
            show() {},
            hide() {},
        };
    };

    window.SPASections = sections;
})();

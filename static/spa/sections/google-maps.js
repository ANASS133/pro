(function () {
    const sections = window.SPASections || {};

    sections.createGoogleMapsSection = function createGoogleMapsSection() {
        const escapeHtml = (window.SPAUtils && window.SPAUtils.escapeHtml) || function fallbackEscapeHtml(value) { return String(value || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;"); };

        // ── DOM references ───────────────────────────────────────────
        const form = document.getElementById("gmaps-search-form");
        const queryInput = document.getElementById("gmaps-query");
        const maxResultsInput = document.getElementById("gmaps-max-results");
        const maxResultsValue = document.getElementById("gmaps-max-results-value");
        const radiusSelect = document.getElementById("gmaps-radius");
        const searchBtn = document.getElementById("gmaps-search-btn");
        const loadingEl = document.getElementById("gmaps-loading");

        const progressPanel = document.getElementById("gmaps-progress-panel");
        const progressFill = document.getElementById("gmaps-progress-fill");
        const progressStatus = document.getElementById("gmaps-progress-status");
        const progressError = document.getElementById("gmaps-progress-error");
        const statBusinesses = document.getElementById("gmaps-stat-businesses");
        const statEmails = document.getElementById("gmaps-stat-emails");
        const statNoEmail = document.getElementById("gmaps-stat-no-email");
        const statFailed = document.getElementById("gmaps-stat-failed");
        const phaseLabel = document.getElementById("gmaps-phase-label");
        const stopBtn = document.getElementById("gmaps-stop-btn");

        const resultsPanel = document.getElementById("gmaps-results-panel");
        const resultsBody = document.getElementById("gmaps-results-body");
        const resultsSummary = document.getElementById("gmaps-results-summary");

        const exportBar = document.getElementById("gmaps-export-bar");
        const dlExcelBtn = document.getElementById("gmaps-dl-excel");
        const dlCsvBtn = document.getElementById("gmaps-dl-csv");
        const dlJsonBtn = document.getElementById("gmaps-dl-json");

        // Two-step UI elements
        const discoverySummary = document.getElementById("gmaps-discovery-summary");
        const discoveryCount = document.getElementById("gmaps-discovery-count");
        const startExtractBtn = document.getElementById("gmaps-start-extract-btn");

        if (!form) {
            return { show() {}, hide() {} };
        }

        let jobId = "";
        let pollTimer = null;

        // ── Slider sync ──────────────────────────────────────────────
        if (maxResultsInput && maxResultsValue) {
            maxResultsInput.addEventListener("input", () => {
                maxResultsValue.textContent = maxResultsInput.value;
            });
        }

        // ── Status label helpers ─────────────────────────────────────
        function phaseToLabel(phase) {
            const labels = {
                queued: "Warte auf Start…",
                scraping_maps: "Google Maps wird durchsucht…",
                ready_to_extract: "Bereit zur Extraktion",
                extracting_emails: "E-Mails werden extrahiert…",
                done: "Fertig",
                stopped: "Gestoppt",
                error: "Fehler",
            };
            return labels[phase] || phase;
        }

        function statusBadge(status) {
            const map = {
                success: '<span class="gmaps-badge gmaps-badge--success">Erfolg</span>',
                no_email: '<span class="gmaps-badge gmaps-badge--muted">Keine E-Mail</span>',
                no_website: '<span class="gmaps-badge gmaps-badge--muted">Keine Website</span>',
                error: '<span class="gmaps-badge gmaps-badge--error">Fehler</span>',
                pending: '<span class="gmaps-badge gmaps-badge--pending">Ausstehend</span>',
                stopped: '<span class="gmaps-badge gmaps-badge--muted">Gestoppt</span>',
            };
            return map[status] || '<span class="gmaps-badge">' + escapeHtml(status) + "</span>";
        }

        // ── UI state helpers ─────────────────────────────────────────
        function setLoading(loading) {
            if (loadingEl) loadingEl.hidden = !loading;
            if (searchBtn) {
                searchBtn.disabled = loading;
                searchBtn.textContent = loading ? "Suche läuft…" : "Businesses & Emails von Google Maps extrahieren";
            }
        }

        function showProgress(data) {
            if (progressPanel) progressPanel.hidden = false;

            const pct = window.SPAUtils.clampPercent(data.percentage || 0);
            if (progressFill) {
                progressFill.style.width = pct + "%";
                progressFill.textContent = Math.round(pct) + "%";
            }

            if (statBusinesses) statBusinesses.textContent = String(data.total_businesses || 0);
            if (statEmails) statEmails.textContent = String(data.emails_found || 0);
            if (statNoEmail) statNoEmail.textContent = String(data.no_email || 0);
            if (statFailed) statFailed.textContent = String(data.failed || 0);

            if (phaseLabel) phaseLabel.textContent = phaseToLabel(data.phase);

            let statusText = "";
            if (data.phase === "scraping_maps") {
                statusText = "Google Maps wird nach Unternehmen durchsucht…";
            } else if (data.phase === "extracting_emails") {
                statusText = `E-Mail-Extraktion: ${data.current_index || 0}/${data.total_businesses || 0} Unternehmen verarbeitet`;
            } else if (data.phase === "done") {
                statusText = "Extraktion abgeschlossen";
            } else if (data.phase === "stopped") {
                statusText = "Gestoppt";
            } else if (data.phase === "error") {
                statusText = "Fehler aufgetreten";
            }
            if (progressStatus) progressStatus.textContent = statusText;

            if (data.last_error) {
                if (progressError) {
                    progressError.textContent = data.last_error;
                    progressError.hidden = false;
                }
            } else if (progressError) {
                progressError.textContent = "";
                progressError.hidden = true;
            }

            // Stop button visibility
            if (stopBtn) stopBtn.hidden = !data.is_running;

            // Export bar visibility
            const hasResults = (data.total_businesses || 0) > 0 && !data.is_running;
            if (exportBar) exportBar.hidden = !hasResults;
        }

        function renderResults(results) {
            if (!resultsPanel || !resultsBody) return;
            resultsPanel.hidden = false;

            if (!results || !results.length) {
                resultsBody.innerHTML = '<tr><td colspan="7" class="gmaps-empty-row">Keine Ergebnisse gefunden.</td></tr>';
                if (resultsSummary) resultsSummary.textContent = "";
                return;
            }

            const emailCount = results.filter(r => r.emails && r.emails.length > 0).length;
            if (resultsSummary) {
                resultsSummary.textContent = `${results.length} Unternehmen gefunden · ${emailCount} mit E-Mail`;
            }

            resultsBody.innerHTML = results.map((biz, idx) => {
                const name = escapeHtml(biz.name || "—");
                const address = escapeHtml(biz.address || "—");
                const phone = escapeHtml(biz.phone || "—");
                const website = biz.website
                    ? `<a href="${escapeHtml(biz.website)}" target="_blank" rel="noopener" class="gmaps-link">${escapeHtml(biz.website.replace(/^https?:\/\//, "").slice(0, 35))}</a>`
                    : "—";
                const emails = (biz.emails || []).length
                    ? biz.emails.map(e => `<span class="gmaps-email">${escapeHtml(e)}</span>`).join("<br>")
                    : "—";
                const rating = biz.rating
                    ? `<span class="gmaps-rating">★ ${escapeHtml(biz.rating)}</span>`
                    : "—";
                const badge = statusBadge(biz.status || "pending");

                return `<tr class="gmaps-row gmaps-row--${biz.status || 'pending'}">
                    <td class="gmaps-cell-num">${idx + 1}</td>
                    <td class="gmaps-cell-name">${name}</td>
                    <td>${address}</td>
                    <td>${phone}</td>
                    <td>${website}</td>
                    <td>${emails}</td>
                    <td>${rating}</td>
                    <td>${badge}</td>
                </tr>`;
            }).join("");
        }

        // ── API calls ────────────────────────────────────────────────
        // Step 1: Discover businesses on Google Maps (discovery phase only)
        async function discoverBusinesses() {
            const query = (queryInput ? queryInput.value : "").trim();
            if (!query) {
                if (progressError) {
                    progressError.textContent = "Bitte einen Suchbegriff eingeben.";
                    progressError.hidden = false;
                }
                return;
            }

            setLoading(true);
            if (progressError) { progressError.textContent = ""; progressError.hidden = true; }
            if (resultsPanel) resultsPanel.hidden = true;
            if (exportBar) exportBar.hidden = true;
            if (discoverySummary) discoverySummary.hidden = true;
            if (startExtractBtn) startExtractBtn.hidden = true;

            try {
                const response = await fetch("/api/google-maps/discover", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        query: query,
                        max_results: parseInt(maxResultsInput ? maxResultsInput.value : "50", 10),
                        radius: parseInt(radiusSelect ? radiusSelect.value : "10", 10),
                    }),
                });
                const data = await response.json();

                if (!response.ok || !data.success) {
                    throw new Error(data.message || "Discovery fehlgeschlagen");
                }

                jobId = data.job_id || "";
                if (!jobId) throw new Error("Keine Job-ID erhalten");

                if (progressPanel) progressPanel.hidden = false;
                startPolling();
            } catch (error) {
                if (progressError) {
                    progressError.textContent = error.message || "Discovery fehlgeschlagen";
                    progressError.hidden = false;
                }
            } finally {
                setLoading(false);
            }
        }

        // Step 2: Start link-by-link email extraction
        async function startExtraction() {
            if (!jobId) return;

            setLoading(true);
            if (progressError) { progressError.textContent = ""; progressError.hidden = true; }

            // Hide discovery summary, show extraction progress
            if (discoverySummary) discoverySummary.hidden = true;
            if (startExtractBtn) startExtractBtn.hidden = true;
            if (searchBtn) {
                searchBtn.disabled = true;
                searchBtn.textContent = "E-Mails werden extrahiert\u2026";
            }

            try {
                const response = await fetch("/api/google-maps/extract/" + encodeURIComponent(jobId), {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                });
                const data = await response.json();

                if (!response.ok || !data.success) {
                    throw new Error(data.message || "Extraktion fehlgeschlagen");
                }

                if (progressPanel) progressPanel.hidden = false;
                startPolling();
            } catch (error) {
                if (progressError) {
                    progressError.textContent = error.message || "Extraktion fehlgeschlagen";
                    progressError.hidden = false;
                }
            } finally {
                setLoading(false);
            }
        }

        // Legacy: one-click start (both phases at once) - kept for backward compatibility
        async function startSearch() {
            const query = (queryInput ? queryInput.value : "").trim();
            if (!query) {
                if (progressError) {
                    progressError.textContent = "Bitte einen Suchbegriff eingeben.";
                    progressError.hidden = false;
                }
                return;
            }

            setLoading(true);
            if (progressError) { progressError.textContent = ""; progressError.hidden = true; }
            if (resultsPanel) resultsPanel.hidden = true;
            if (exportBar) exportBar.hidden = true;

            try {
                const response = await fetch("/api/google-maps/start", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        query: query,
                        max_results: parseInt(maxResultsInput ? maxResultsInput.value : "50", 10),
                        radius: parseInt(radiusSelect ? radiusSelect.value : "10", 10),
                    }),
                });
                const data = await response.json();

                if (!response.ok || !data.success) {
                    throw new Error(data.message || "Start fehlgeschlagen");
                }

                jobId = data.job_id || "";
                if (!jobId) throw new Error("Keine Job-ID erhalten");

                if (progressPanel) progressPanel.hidden = false;
                startPolling();
            } catch (error) {
                if (progressError) {
                    progressError.textContent = error.message || "Start fehlgeschlagen";
                    progressError.hidden = false;
                }
            } finally {
                setLoading(false);
            }
        }

        function startPolling() {
            if (pollTimer) clearInterval(pollTimer);
            pollTimer = setInterval(() => pollStatus(), 2000);
            pollStatus();
        }

        async function pollStatus() {
            if (!jobId) return;

            try {
                const response = await fetch(`/api/google-maps/status/${encodeURIComponent(jobId)}`);
                const data = await response.json();

                if (!response.ok || !data.success || !data.job) {
                    throw new Error(data.message || "Statusabfrage fehlgeschlagen");
                }

                const job = data.job;
                showProgress(job);
                renderResults(job.results);

                if (!job.is_running) {
                    if (pollTimer) {
                        clearInterval(pollTimer);
                        pollTimer = null;
                    }

                    // Show extraction button when discovery is done
                    if (job.phase === "ready_to_extract") {
                        if (discoverySummary) {
                            discoverySummary.hidden = false;
                            if (discoveryCount) discoveryCount.textContent = job.total_businesses;
                        }
                        if (startExtractBtn) startExtractBtn.hidden = false;
                        if (searchBtn) {
                            searchBtn.disabled = true;
                            searchBtn.textContent = "Businesses gefunden: " + job.total_businesses;
                        }
                    } else {
                        if (searchBtn) {
                            searchBtn.disabled = false;
                            searchBtn.textContent = "Businesses & Emails von Google Maps extrahieren";
                        }
                    }
                }
            } catch (error) {
                if (progressError) {
                    progressError.textContent = error.message || "Statusfehler";
                    progressError.hidden = false;
                }
            }
        }

        async function stopJob() {
            if (!jobId) return;
            try {
                await fetch(`/api/google-maps/stop/${encodeURIComponent(jobId)}`, { method: "POST" });
            } catch (error) {
                if (progressError) {
                    progressError.textContent = error.message || "Stopp fehlgeschlagen";
                    progressError.hidden = false;
                }
            }
        }

        // ── Event listeners ──────────────────────────────────────────
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            discoverBusinesses();
        });

        if (stopBtn) {
            stopBtn.addEventListener("click", () => stopJob());
        }

        if (startExtractBtn) {
            startExtractBtn.addEventListener("click", () => startExtraction());
        }

        if (dlExcelBtn) {
            dlExcelBtn.addEventListener("click", () => {
                if (jobId) window.location.href = `/api/google-maps/export/${encodeURIComponent(jobId)}/xlsx`;
            });
        }
        if (dlCsvBtn) {
            dlCsvBtn.addEventListener("click", () => {
                if (jobId) window.location.href = `/api/google-maps/export/${encodeURIComponent(jobId)}/csv`;
            });
        }
        if (dlJsonBtn) {
            dlJsonBtn.addEventListener("click", () => {
                if (jobId) window.location.href = `/api/google-maps/export/${encodeURIComponent(jobId)}/json`;
            });
        }

        // ── Cleanup ──────────────────────────────────────────────────
        window.addEventListener("beforeunload", () => {
            if (pollTimer) clearInterval(pollTimer);
        });

        return {
            show() {},
            hide() {
                if (pollTimer) {
                    clearInterval(pollTimer);
                    pollTimer = null;
                }
            },
        };
    };

    window.SPASections = sections;
})();

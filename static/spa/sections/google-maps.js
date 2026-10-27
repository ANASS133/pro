(function () {
    const sections = window.SPASections || {};

    sections.createGoogleMapsSection = function createGoogleMapsSection() {
        const escapeHtml = (window.SPAUtils && window.SPAUtils.escapeHtml) || function fallbackEscapeHtml(value) {
            return String(value || "")
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#39;");
        };

        // ── DOM references ───────────────────────────────────────────
        const form = document.getElementById("gmaps-search-form");
        const queryInput = document.getElementById("gmaps-query");
        const maxResultsInput = document.getElementById("gmaps-max-results");
        const maxResultsValue = document.getElementById("gmaps-max-results-value");
        const radiusSelect = document.getElementById("gmaps-radius");
        const searchBtn = document.getElementById("gmaps-search-btn");
        const loadingEl = document.getElementById("gmaps-loading");

        // Opportunity verification controls
        const verifyToggle = document.getElementById("gmaps-verify-toggle");
        const verificationOptions = document.getElementById("gmaps-verification-options");
        const jobTypeSelect = document.getElementById("gmaps-job-type");
        const targetTitleInput = document.getElementById("gmaps-target-title");
        const clientSelect = document.getElementById("gmaps-client-select");

        const progressPanel = document.getElementById("gmaps-progress-panel");
        const progressFill = document.getElementById("gmaps-progress-fill");
        const progressStatus = document.getElementById("gmaps-progress-status");
        const progressError = document.getElementById("gmaps-progress-error");
        const statBusinesses = document.getElementById("gmaps-stat-businesses");
        const statEmails = document.getElementById("gmaps-stat-emails");
        const statVacancies = document.getElementById("gmaps-stat-vacancies");
        const statForms = document.getElementById("gmaps-stat-forms");
        const statNoEmail = document.getElementById("gmaps-stat-no-email");
        const statFailed = document.getElementById("gmaps-stat-failed");
        const phaseLabel = document.getElementById("gmaps-phase-label");
        const stopBtn = document.getElementById("gmaps-stop-btn");

        const resultsPanel = document.getElementById("gmaps-results-panel");
        const resultsBody = document.getElementById("gmaps-results-body");
        const resultsSummary = document.getElementById("gmaps-results-summary");

        const countVerified = document.getElementById("gmaps-count-verified");
        const countForms = document.getElementById("gmaps-count-forms");
        const countEmails = document.getElementById("gmaps-count-emails");
        const filterBtns = document.querySelectorAll(".gmaps-filter-btn");

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
        let latestResults = [];
        let currentFilter = "all";
        let clientProfiles = {};

        // ── Slider sync ──────────────────────────────────────────────
        if (maxResultsInput && maxResultsValue) {
            maxResultsInput.addEventListener("input", () => {
                maxResultsValue.textContent = maxResultsInput.value;
            });
        }

        // ── Verification toggle listener ──────────────────────────────
        if (verifyToggle && verificationOptions) {
            verifyToggle.addEventListener("change", () => {
                verificationOptions.hidden = !verifyToggle.checked;
            });
        }

        // ── Job Type Ausbildung auto-prefill for target title ──────────
        if (jobTypeSelect && targetTitleInput) {
            jobTypeSelect.addEventListener("change", (e) => {
                if (e.target.value === "ausbildung") {
                    const prefix = "Ausbildung als ";
                    if (!targetTitleInput.value || targetTitleInput.value.trim() === "") {
                        targetTitleInput.value = prefix;
                    } else if (!targetTitleInput.value.startsWith(prefix)) {
                        targetTitleInput.value = prefix + targetTitleInput.value.replace(/^Ausbildung\s+(als\s+)?/i, "").trimStart();
                    }
                    targetTitleInput.focus();
                    const len = targetTitleInput.value.length;
                    targetTitleInput.setSelectionRange(len, len);
                } else if (e.target.value === "employment") {
                    if (targetTitleInput.value === "Ausbildung als " || targetTitleInput.value.trim() === "Ausbildung als") {
                        targetTitleInput.value = "";
                    } else if (targetTitleInput.value.startsWith("Ausbildung als ")) {
                        targetTitleInput.value = targetTitleInput.value.slice("Ausbildung als ".length);
                    }
                }
            });
        }

        // ── Load client profiles for dossier dropdown ────────────────
        async function loadClients() {
            if (!clientSelect) return;
            try {
                const resp = await fetch("/api/clients");
                const data = await resp.json();
                if (data.success && Array.isArray(data.clients)) {
                    clientSelect.innerHTML = '<option value="">Manuelle Kriterien / Allgemein</option>';
                    data.clients.forEach(c => {
                        const opt = document.createElement("option");
                        opt.value = c.id;
                        opt.textContent = `${c.name || c.id} ${c.title ? '(' + c.title + ')' : ''}`;
                        if (c.id === data.active_client_id) {
                            opt.selected = true;
                            if (targetTitleInput && !targetTitleInput.value && c.title) {
                                targetTitleInput.value = c.title;
                            }
                        }
                        clientSelect.appendChild(opt);
                        clientProfiles[c.id] = c;
                    });
                }
            } catch (err) {
                console.debug("Could not load clients for Google Maps selector", err);
            }
        }
        loadClients();

        if (clientSelect) {
            clientSelect.addEventListener("change", () => {
                const selId = clientSelect.value;
                if (selId && clientProfiles[selId] && targetTitleInput && !targetTitleInput.value) {
                    targetTitleInput.value = clientProfiles[selId].title || "";
                }
            });
        }

        // ── Quick Filter Buttons ──────────────────────────────────────
        filterBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                filterBtns.forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                currentFilter = btn.dataset.filter || "all";
                renderFilteredResults();
            });
        });

        // ── Status label helpers ─────────────────────────────────────
        function phaseToLabel(phase) {
            const labels = {
                queued: "Warte auf Start…",
                scraping_maps: "Google Maps wird durchsucht…",
                ready_to_extract: "Bereit zur Extraktion & Verifizierung",
                extracting_emails: "Websites & Karrieren werden analysiert…",
                done: "Fertiggestellt",
                stopped: "Gestoppt",
                error: "Fehler",
            };
            return labels[phase] || phase;
        }

        function verificationStatusBadge(status) {
            const st = String(status || "").toUpperCase();
            if (st === "OPEN_VERIFIED" || st === "VERIFIED_AUSBILDUNG" || st === "VERIFIED_JOB") {
                return '<span class="gmaps-badge gmaps-badge--verified">&#10003; Bestätigt offen</span>';
            }
            if (st === "POTENTIALLY_OPEN") {
                return '<span class="gmaps-badge gmaps-badge--potential">&#9733; Initiativ / Offen</span>';
            }
            if (st === "NO_MATCHING_VACANCY" || st === "NO_MATCHING_AUSBILDUNG") {
                return '<span class="gmaps-badge gmaps-badge--muted">Keine passende Stelle</span>';
            }
            if (st === "EXPIRED") {
                return '<span class="gmaps-badge gmaps-badge--error">Frist abgelaufen</span>';
            }
            if (st === "VERIFICATION_FAILED" || st === "INACCESSIBLE_WEBSITE") {
                return '<span class="gmaps-badge gmaps-badge--error">Prüfung fehlgeschlagen</span>';
            }
            return '<span class="gmaps-badge gmaps-badge--muted">Keine Karriereseite</span>';
        }

        function scoreBadge(score, reasons) {
            const s = parseInt(score, 10) || 0;
            const tooltip = (reasons && reasons.length) ? escapeHtml(reasons.join(" • ")) : `${s}% Relevanz`;
            let cls = "gmaps-score-low";
            if (s >= 60) cls = "gmaps-score-high";
            else if (s >= 35) cls = "gmaps-score-mid";

            return `<span class="gmaps-score-pill ${cls}" title="${tooltip}">${s}% Passung</span>`;
        }

        function applicationMethodBadge(method, urlType, applyUrl) {
            const m = String(method || "").toLowerCase();
            const cleanUrl = escapeHtml(applyUrl || "#");

            if (urlType === "DIRECT_APPLICATION_FORM" || m.includes("form")) {
                return `<a href="${cleanUrl}" target="_blank" rel="noopener" class="gmaps-method-pill gmaps-method-form" title="Direktes Bewerbungsformular">Formular &rarr;</a>`;
            }
            if (urlType === "APPLICATION_PORTAL" || m.includes("portal")) {
                return `<a href="${cleanUrl}" target="_blank" rel="noopener" class="gmaps-method-pill gmaps-method-portal" title="ATS Bewerberportal (z.B. Personio, Workday)">Portal &rarr;</a>`;
            }
            if (m.includes("email") || m.includes("e-mail")) {
                return `<span class="gmaps-method-pill gmaps-method-email">E-Mail</span>`;
            }
            if (urlType === "CAREERS_PAGE") {
                return `<a href="${cleanUrl}" target="_blank" rel="noopener" class="gmaps-method-pill gmaps-method-none">Karriereseite</a>`;
            }
            return `<span class="gmaps-method-pill gmaps-method-none">Nicht spezifiziert</span>`;
        }

        // ── UI state helpers ─────────────────────────────────────────
        function setLoading(loading) {
            if (loadingEl) loadingEl.hidden = !loading;
            if (searchBtn) {
                searchBtn.disabled = loading;
                searchBtn.textContent = loading ? "Entdecke Unternehmen & Karrieren…" : "Unternehmen & Karrieren via Google Maps entdecken";
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
            if (statVacancies) statVacancies.textContent = String(data.vacancies_found || 0);
            if (statForms) statForms.textContent = String(data.forms_found || 0);
            if (statNoEmail) statNoEmail.textContent = String(data.no_email || 0);
            if (statFailed) statFailed.textContent = String(data.failed || 0);

            if (phaseLabel) phaseLabel.textContent = phaseToLabel(data.phase);

            let statusText = "";
            if (data.phase === "scraping_maps") {
                statusText = "Google Maps wird nach Unternehmen durchsucht…";
            } else if (data.phase === "extracting_emails") {
                const cur = data.current_index || 0;
                const tot = data.total_businesses || 0;
                statusText = `Website & Karriere-Crawling: ${cur}/${tot} Unternehmen analysiert`;
            } else if (data.phase === "done") {
                statusText = "Extraktion & Verifizierung abgeschlossen";
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

        function updateFilterCounts(results) {
            if (!results) return;
            const verified = results.filter(r => r.has_verified_vacancy || r.primary_verification_status === "OPEN_VERIFIED").length;
            const forms = results.filter(r => r.primary_url_type === "DIRECT_APPLICATION_FORM" || r.primary_url_type === "APPLICATION_PORTAL").length;
            const emails = results.filter(r => r.emails && r.emails.length > 0).length;

            if (countVerified) countVerified.textContent = String(verified);
            if (countForms) countForms.textContent = String(forms);
            if (countEmails) countEmails.textContent = String(emails);
        }

        function renderFilteredResults() {
            if (!resultsPanel || !resultsBody) return;
            resultsPanel.hidden = false;

            if (!latestResults || !latestResults.length) {
                resultsBody.innerHTML = '<tr><td colspan="8" class="gmaps-empty-row">Keine Unternehmen gefunden.</td></tr>';
                if (resultsSummary) resultsSummary.textContent = "";
                return;
            }

            let filtered = latestResults;
            if (currentFilter === "verified") {
                filtered = latestResults.filter(r => r.has_verified_vacancy || r.primary_verification_status === "OPEN_VERIFIED");
            } else if (currentFilter === "forms") {
                filtered = latestResults.filter(r => r.primary_url_type === "DIRECT_APPLICATION_FORM" || r.primary_url_type === "APPLICATION_PORTAL");
            } else if (currentFilter === "emails") {
                filtered = latestResults.filter(r => r.emails && r.emails.length > 0);
            }

            const emailCount = latestResults.filter(r => r.emails && r.emails.length > 0).length;
            const verifiedCount = latestResults.filter(r => r.has_verified_vacancy || r.primary_verification_status === "OPEN_VERIFIED").length;
            if (resultsSummary) {
                resultsSummary.textContent = `${latestResults.length} Unternehmen gefunden · ${verifiedCount} Stellen bestätigt · ${emailCount} mit E-Mail`;
            }

            if (!filtered.length) {
                resultsBody.innerHTML = `<tr><td colspan="8" class="gmaps-empty-row">Keine Ergebnisse für Filter '${escapeHtml(currentFilter)}'.</td></tr>`;
                return;
            }

            resultsBody.innerHTML = filtered.map((biz) => {
                const isPending = biz.status === "pending";
                const name = escapeHtml(biz.name || "—");
                const phone = biz.phone ? `<span class="gmaps-subtext">&#128382; ${escapeHtml(biz.phone)}</span>` : "";
                const mapsLink = biz.maps_url ? `<a href="${escapeHtml(biz.maps_url)}" target="_blank" rel="noopener" class="gmaps-mini-link" title="Auf Google Maps öffnen">&#128506; Maps</a>` : "";

                const address = biz.address ? escapeHtml(biz.address) : (isPending ? '<span class="gmaps-muted">Wird geladen...</span>' : "—");

                // Website & Career
                let webCell = "—";
                if (biz.website) {
                    const host = escapeHtml(biz.website.replace(/^https?:\/\//, "").replace(/\/$/, "").slice(0, 28));
                    const siteLink = `<a href="${escapeHtml(biz.website)}" target="_blank" rel="noopener" class="gmaps-link">${host}</a>`;
                    const careerLink = biz.career_page
                        ? `<br><a href="${escapeHtml(biz.career_page)}" target="_blank" rel="noopener" class="gmaps-vacancy-link">&#128188; Karriereseite</a>`
                        : "";
                    webCell = siteLink + careerLink;
                } else if (isPending) {
                    webCell = '<span class="gmaps-muted">Wird analysiert...</span>';
                }

                // Vacancy & Title
                let vacancyCell = '<span class="gmaps-muted">Keine passende Stelle</span>';
                if (biz.primary_job_title) {
                    const typeLabel = biz.ausbildung_available ? '<span class="job-badge badge-ausbildung">Ausbildung</span>' : '<span class="job-badge badge-arbeit">Festanstellung</span>';
                    const multiBadge = (biz.vacancies_count > 1) ? ` <span class="gmaps-badge gmaps-badge--muted">+${biz.vacancies_count - 1} weitere</span>` : "";
                    vacancyCell = `<div class="gmaps-detail-cell">
                        <span class="gmaps-detail-title">${escapeHtml(biz.primary_job_title)}</span>
                        ${typeLabel}${multiBadge}
                    </div>`;
                } else if (biz.has_career_page) {
                    vacancyCell = '<span class="gmaps-muted">&#128188; Karriereseite vorhanden</span>';
                }

                // Matching Score
                const scoreBadgeHtml = biz.primary_matching_score > 0
                    ? scoreBadge(biz.primary_matching_score, biz.primary_matching_reasons)
                    : '<span class="gmaps-score-pill gmaps-score-low">—</span>';

                // Application destination
                const applyMethodHtml = applicationMethodBadge(
                    biz.primary_apply_method,
                    biz.primary_url_type,
                    biz.primary_apply_url
                );

                // Emails
                const emails = (biz.emails || []).length
                    ? biz.emails.map(e => `<a href="mailto:${escapeHtml(e)}" class="gmaps-email">${escapeHtml(e)}</a>`).join("<br>")
                    : (isPending ? '<span class="gmaps-muted">Wird extrahiert...</span>' : '<span class="gmaps-muted">Keine E-Mail</span>');

                // Status
                const statusBadgeHtml = verificationStatusBadge(biz.primary_verification_status || biz.status);

                return `<tr class="gmaps-row gmaps-row--${biz.status || 'pending'}">
                    <td class="gmaps-cell-name">
                        <strong>${name}</strong>
                        <div>${phone} ${mapsLink}</div>
                    </td>
                    <td>${address}</td>
                    <td>${webCell}</td>
                    <td>${vacancyCell}</td>
                    <td>${scoreBadgeHtml}</td>
                    <td>${applyMethodHtml}</td>
                    <td>${emails}</td>
                    <td>${statusBadgeHtml}</td>
                </tr>`;
            }).join("");
        }

        function renderResults(results) {
            latestResults = results || [];
            updateFilterCounts(latestResults);
            renderFilteredResults();
        }

        // ── Helper to build request payload with verification options ──
        function buildPayload() {
            const query = (queryInput ? queryInput.value : "").trim();
            const maxResults = parseInt(maxResultsInput ? maxResultsInput.value : "50", 10);
            const radius = parseInt(radiusSelect ? radiusSelect.value : "10", 10);
            const isVerify = verifyToggle ? verifyToggle.checked : false;
            const jobType = jobTypeSelect ? jobTypeSelect.value : "both";
            const targetTitle = (targetTitleInput ? targetTitleInput.value : "").trim();
            const clientId = clientSelect ? clientSelect.value : "";

            return {
                query: query,
                max_results: maxResults,
                radius: radius,
                verify_opportunities: isVerify,
                job_type: jobType,
                target_title: targetTitle,
                client_id: clientId,
            };
        }

        // ── API calls ────────────────────────────────────────────────
        async function discoverBusinesses() {
            const payload = buildPayload();
            if (!payload.query) {
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
                    body: JSON.stringify(payload),
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

        async function startExtraction() {
            if (!jobId) return;

            setLoading(true);
            if (progressError) { progressError.textContent = ""; progressError.hidden = true; }

            if (discoverySummary) discoverySummary.hidden = true;
            if (startExtractBtn) startExtractBtn.hidden = true;
            if (searchBtn) {
                searchBtn.disabled = true;
                searchBtn.textContent = "Websites & Karrieren werden analysiert…";
            }

            try {
                const payload = buildPayload();
                const response = await fetch("/api/google-maps/extract/" + encodeURIComponent(jobId), {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
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

        async function startSearch() {
            const payload = buildPayload();
            if (!payload.query) {
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
                const response = await fetch("/api/google-maps/start", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
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

                    if (job.phase === "ready_to_extract") {
                        if (discoverySummary) discoverySummary.hidden = false;
                        if (startExtractBtn) startExtractBtn.hidden = false;
                        if (searchBtn) {
                            searchBtn.disabled = true;
                            searchBtn.textContent = "Unternehmen gefunden: " + job.total_businesses;
                        }
                    } else {
                        if (searchBtn) {
                            searchBtn.disabled = false;
                            searchBtn.textContent = "Unternehmen & Karrieren via Google Maps entdecken";
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
            startSearch();
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
            show() {
                loadClients();
            },
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

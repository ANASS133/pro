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
                all: "Alle Quellen inkl. Google Maps",
                job_portals: "Nur Jobbörsen",
                google_maps: "Nur Google Maps",
            };
            const dateLabels = {
                "30days": "30 Tage",
                "14days": "14 Tage",
                "7days": "7 Tage",
                all: "Alle Anzeigen",
            };
            const srcText = srcLabels[srcEl ? srcEl.value : "all"] || "Alle Quellen";
            const dateText = dateLabels[dateEl ? dateEl.value : "30days"] || "30 Tage";
            const radText = (radEl && radEl.value) ? ` • +${radEl.value} km` : "";
            badge.textContent = `${srcText} • ${dateText}${radText}`;
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

        function setSearchProgress(ui, progressData) {
            const pct = Math.max(0, Math.min(100, Math.round(progressData.percent || 0)));
            const stage = progressData.stage || "";
            const found = typeof progressData.found === "number" ? progressData.found : 0;
            const source = progressData.source || "";
            const finishedSource = progressData.finished_source || "";
            const sourceCount = progressData.source_count;

            if (ui.progressCard) {
                ui.progressCard.style.display = "block";
            }

            // 1. Update the Search Button progress bar & label
            if (ui.btnBar) {
                ui.btnBar.style.width = `${pct}%`;
            }
            if (ui.btnLabel) {
                if (pct >= 100) {
                    ui.btnLabel.textContent = `Fertig (${found} Stellen)`;
                } else if (found > 0) {
                    ui.btnLabel.textContent = `Suche läuft... ${pct}% (${found} Stellen)`;
                } else {
                    ui.btnLabel.textContent = `Suche läuft... ${pct}%`;
                }
            }

            // 2. Update the Search Progress Card
            if (ui.searchProgressFill) {
                ui.searchProgressFill.style.width = `${pct}%`;
            }
            if (ui.searchProgressPct) {
                ui.searchProgressPct.textContent = `${pct}%`;
            }
            if (ui.progressCounter) {
                if (progressData.raw_found && progressData.raw_found > found) {
                    ui.progressCounter.textContent = `${found} passende Stellen (${progressData.raw_found} geprüft)`;
                } else {
                    ui.progressCounter.textContent = `${found} Stellen gefunden`;
                }
            }
            if (ui.searchProgressStatus && stage) {
                ui.searchProgressStatus.textContent = stage;
            }

            // 3. Update Portal Badges
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

            // 4. Update Sidebar Live Job Widget
            const sidebarJob = document.getElementById("sidebar-live-job");
            const sidebarTitle = document.getElementById("sidebar-job-title");
            const sidebarPercent = document.getElementById("sidebar-job-percent");
            const sidebarFill = document.getElementById("sidebar-job-fill");
            const sidebarMeta = document.getElementById("sidebar-job-meta");
            if (sidebarJob && sidebarTitle && sidebarPercent && sidebarFill && sidebarMeta) {
                sidebarJob.hidden = false;
                sidebarTitle.textContent = "Jobsuche läuft";
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

                if (ui.loadingEl) {
                    ui.loadingEl.style.display = "none";
                }
                if (ui.progressCard) {
                    ui.progressCard.style.display = "block";
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
                setSearchProgress(ui, { percent: 5, stage: "Verbindung zu Portalen wird hergestellt...", found: 0 });
            } else {
                ui.searchBtn.disabled = false;
                ui.searchBtn.classList.remove("is-searching");
                if (ui.btnBar) {
                    ui.btnBar.style.width = "0%";
                }
                if (ui.btnLabel) {
                    ui.btnLabel.textContent = "Suche starten";
                }
                if (ui.loadingEl) {
                    ui.loadingEl.style.display = "none";
                }
                setTimeout(() => {
                    if (ui.progressCard) {
                        ui.progressCard.style.display = "none";
                    }
                }, 3500);

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
            let metaText = `${total} passende Stellen gefunden | Veröffentlicht seit: ${publishedSince}`;
            if (data.audit && data.audit.raw_total) {
                metaText = `${total} passende Stellen aus ${data.audit.raw_total} geprüften Angeboten | Veröffentlicht seit: ${publishedSince}`;
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
                        <span><strong>📊 Such-Audit:</strong> ${a.filtered_total} passende Stellen aus ${a.raw_total} Angeboten &bull; <span style="color:#64748b;">${a.exclusions_total} herausgefiltert</span></span>
                        <button type="button" style="background:none; border:none; color:#2563eb; cursor:pointer; font-size:12px; font-weight:600;">Details anzeigen ▾</button>
                    </div>
                    <div id="audit_details_${isUi1 ? '1' : '2'}" style="display:none; margin-top:8px; padding-top:8px; border-top:1px solid #e2e8f0;">
                        <div style="margin-bottom:6px; font-weight:600; color:#1e293b;">Aufteilung nach Portal & Filtergründen:</div>
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
                        if (btn) btn.textContent = isOpen ? "Details anzeigen ▾" : "Details verbergen ▴";
                    };
                }
            } else if (auditBanner) {
                auditBanner.remove();
            }

            if (!ui.lastJobs.length) {
                if (ui.filterBar) ui.filterBar.style.display = "none";
                ui.listEl.innerHTML = '<div class="job-item">Keine passenden Stellenangebote für diese Suchkriterien gefunden.</div>';
                ui.autoBtn.style.display = "none";
                if (exportBtn) exportBtn.style.display = "none";
                return;
            }

            ui.autoBtn.style.display = "inline-flex";

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
                    contactBadge = `<span class="job-contact-pill has-both" title="E-Mail & verifiziertes Online-Bewerbungsformular verfügbar">⚡ E-Mail + Online-Formular</span>`;
                } else if (hasVerifiedForm) {
                    contactBadge = `<span class="job-contact-pill has-verified-form" title="Verifiziertes Online-Bewerbungsformular">✅ Online-Bewerbungsformular</span>`;
                } else if (hasValidEmail) {
                    contactBadge = `<span class="job-contact-pill has-email" title="Bewerbungs-E-Mail vorhanden">✉️ ${escapeHtml(email)}</span>`;
                } else {
                    contactBadge = `<span class="job-contact-pill has-no-contact" title="Kein verifiziertes Bewerbungsformular und keine Direkt-Mail">⚠️ Kein Direktkontakt</span>`;
                }

                const aiButtonsHtml = `
                    <button type="button" class="job-link job-vibe-btn" data-company="${company}" data-title="${title}" title="Unternehmenskultur, Vibe & Du/Sie Formel prüfen (~$0.00001)">🧭 Vibe</button>
                    <button type="button" class="job-link job-heatmap-btn" data-company="${company}" data-title="${title}" title="Visual ATS Match & Skill Heatmap anzeigen (~$0.00002)">📊 Heatmap</button>
                `;

                // Distinct, verified action buttons
                let actionButtonsHtml = "";
                if (hasVerifiedForm && formUrl) {
                    actionButtonsHtml += `<a class="job-link job-verified-apply-btn" href="${formUrl}" target="_blank" rel="noopener noreferrer" title="Zum echten verifizierten Online-Bewerbungsformular">📝 Zum Bewerbungsformular ↗</a>`;
                    actionButtonsHtml += `<button type="button" class="job-link job-autofill-btn" data-job-url="${formUrl}" data-job-title="${title}" data-job-company="${company}" title="Mit verifiziertem Formular bewerben & Autofill nutzen">⚡ Mit Formular bewerben (Autofill)</button>`;
                } else {
                    if (originalUrl) {
                        actionButtonsHtml += `<a class="job-link job-listing-btn" href="${originalUrl}" target="_blank" rel="noopener noreferrer" title="Originale Stellenanzeige aufrufen">Stellenanzeige öffnen ↗</a>`;
                    }
                    if (bewerbungLink && bewerbungLink !== originalUrl) {
                        actionButtonsHtml += `<a class="job-link job-listing-btn" href="${bewerbungLink}" target="_blank" rel="noopener noreferrer" title="Karriereseite aufrufen">Karriereseite öffnen ↗</a>`;
                    }
                }

                if (hasValidEmail) {
                    actionButtonsHtml += `<a class="job-link job-mail-btn" href="mailto:${escapeHtml(email)}?subject=Bewerbung%20als%20${encodeURIComponent(job.title || '')}" title="Bewerbungs-E-Mail senden">✉️ E-Mail senden</a>`;
                }
                actionButtonsHtml += aiButtonsHtml;

                return `
                    <article class="job-item">
                        <div class="job-item-header">
                            <h4 class="job-title">${title}</h4>
                            <div class="job-badges-wrap">
                                ${sourceBadge}
                                ${contactBadge}
                            </div>
                        </div>
                        <div class="job-meta">
                            <strong>Unternehmen:</strong> ${company} &bull; 
                            <strong>Ort:</strong> ${location}<br>
                            <strong>Veröffentlicht:</strong> ${publishedDate} &bull; 
                            <strong>Erfasst:</strong> ${scrapedAt}
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
                    const filterParam = encodeURIComponent(ui.activeFilter || "all");
                    window.location.href = `/api/inline/auto-jobs/download/${encodeURIComponent(ui.autoJobId)}?filter=${filterParam}`;
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

            const params = new URLSearchParams({
                keyword,
                location,
                published_since: publishedSince,
                source,
                mode,
                radius,
            });

            let searchCompleted = false;

            // 1. Try real-time streaming search via Server-Sent Events (SSE)
            try {
                const streamUrl = `/api/search/stream?${params.toString()}`;
                const evtSource = new EventSource(streamUrl);
                ui.currentEventSource = evtSource;

                await new Promise((resolve, reject) => {
                    const timeoutTimer = setTimeout(() => {
                        evtSource.close();
                        if (ui.currentEventSource === evtSource) ui.currentEventSource = null;
                        if (!searchCompleted) {
                            reject(new Error("Stream timeout"));
                        }
                    }, 45000);

                    evtSource.addEventListener("progress", (e) => {
                        if (ui.searchGeneration !== currentGen) return;
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
                        if (!searchCompleted) {
                            reject(new Error("Stream connection failed"));
                        }
                    });
                });
            } catch (streamError) {
                if (ui.searchGeneration !== currentGen) return;
                if (!searchCompleted) {
                    console.warn("SSE stream failed or not supported, falling back to /api/search:", streamError);
                    let simPercent = 15;
                    const simInterval = setInterval(() => {
                        if (ui.searchGeneration !== currentGen) {
                            clearInterval(simInterval);
                            return;
                        }
                        if (simPercent < 88) {
                            simPercent += Math.floor(Math.random() * 8) + 4;
                            setSearchProgress(ui, {
                                percent: simPercent,
                                stage: "Portale werden durchsucht...",
                                found: Math.floor(simPercent / 4),
                            });
                        }
                    }, 400);

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

        // Mode Segmented Control dynamic placeholders & hints
        const modeRadios = document.querySelectorAll('input[name="mode"]');
        modeRadios.forEach((radio) => {
            radio.addEventListener("change", (e) => {
                const val = e.target.value;
                const kwInput = document.getElementById("keyword");
                const hint = document.getElementById("keyword_hint");
                if (val === "arbeit") {
                    if (kwInput) kwInput.placeholder = "z. B. Softwareentwickler, Projektmanager, Elektroniker";
                    if (hint) hint.textContent = "Geben Sie die Berufsbezeichnung ein — findet Arbeitgeber und direkte E-Mail-Kontakte.";
                } else {
                    if (kwInput) kwInput.placeholder = "z. B. Fachinformatiker, Koch, Softwareentwickler";
                    if (hint) hint.textContent = "Geben Sie einfach die Berufsbezeichnung ein — Suche passt sich automatisch an.";
                }
                saveIndexState();
            });
        });

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
        }

        bindAutofillHandler(searchUi1);
        if (searchUi2) bindAutofillHandler(searchUi2);

        restoreIndexState();
        bindIndexStatePersistence();

        return {
            show() {},
            hide() {},
        };
    };

    window.SPASections = sections;
})();

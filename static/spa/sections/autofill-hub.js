/**
 * Autofill Hub SPA Section Controller
 * Manages applicant profiles, document uploads, learned corrections,
 * and live test-form sandbox.
 */
(function () {
    const sections = window.SPASections || {};

    sections.createAutofillHubSection = function createAutofillHubSection() {
        const root = document.getElementById("autofill-section");
        if (!root) {
            return { show() {}, hide() {} };
        }

        const profileSelector = document.getElementById("autofill-profile-selector");
        const btnNewProfile = document.getElementById("autofill-btn-new-profile");
        const btnSaveProfile = document.getElementById("autofill-btn-save-profile");
        const btnImportCv = document.getElementById("autofill-btn-import-cv");
        const afCvFileInput = document.getElementById("af-cv-file-input");
        const btnSetActive = document.getElementById("autofill-btn-set-active");
        const statusBar = document.getElementById("autofill-status-bar");
        const unsavedBadge = document.getElementById("autofill-unsaved-badge");
        const avatarEl = document.getElementById("candidate-avatar");
        const displayNameEl = document.getElementById("candidate-display-name");
        const displayMetaEl = document.getElementById("candidate-display-meta");
        const docCountEl = document.getElementById("candidate-doc-count");
        const tabBtns = Array.from(root.querySelectorAll(".af-tab-btn, .hub-tab-btn"));
        const tabPanes = Array.from(root.querySelectorAll(".af-tab-pane, .hub-tab-pane"));

        // Form Fields
        const fProfileId = document.getElementById("af-profile-id");
        const fLanguage = document.getElementById("af-profile-language");
        const fFirstName = document.getElementById("af-first-name");
        const fLastName = document.getElementById("af-last-name");
        const fFullName = document.getElementById("af-full-name");
        const fDob = document.getElementById("af-dob");
        const fPob = document.getElementById("af-pob");
        const fNationality = document.getElementById("af-nationality");
        const fGender = document.getElementById("af-gender");

        const fEmail = document.getElementById("af-email");
        const fPhone = document.getElementById("af-phone");
        const fStreet = document.getElementById("af-street");
        const fHouseNo = document.getElementById("af-house-no");
        const fPostal = document.getElementById("af-postal");
        const fCity = document.getElementById("af-city");
        const fCountry = document.getElementById("af-country");
        const fCountryCode = document.getElementById("af-country-code");
        const fLinkedin = document.getElementById("af-linkedin");
        const fPortfolio = document.getElementById("af-portfolio");
        const fGithub = document.getElementById("af-github");

        const fCurrentTitle = document.getElementById("af-current-title");
        const fHeadline = document.getElementById("af-headline");
        const fSummary = document.getElementById("af-summary");
        const fPrimaryFields = document.getElementById("af-primary-fields");

        // Documents & Corrections
        const fileUploadInput = document.getElementById("af-file-upload-input");
        const documentListEl = document.getElementById("af-document-list");
        const correctionsListEl = document.getElementById("af-corrections-list");
        const btnClearCorrections = document.getElementById("af-btn-clear-corrections");
        const rawJsonEl = document.getElementById("af-raw-json");

        // Sandbox Elements
        const sandboxCard = document.getElementById("af-sandbox-card");
        const btnExpandSandbox = document.getElementById("btn-expand-sandbox");
        const btnLoadDeForm = document.getElementById("btn-load-de-form");
        const btnLoadFrForm = document.getElementById("btn-load-fr-form");
        const btnRefreshSandbox = document.getElementById("btn-refresh-sandbox");
        const linkOpenSandboxTab = document.getElementById("link-open-sandbox-tab");
        const sandboxIframe = document.getElementById("autofill-sandbox-iframe");
        const sandboxUrlPill = document.getElementById("af-current-sandbox-url");
        const browserAddressText = document.getElementById("af-browser-address-text");

        // History
        const btnRefreshHistory = document.getElementById("autofill-refresh-history");
        const historyBody = document.getElementById("autofill-history-body");

        let currentProfileId = "";
        let currentProfileData = null;
        let cachedProfiles = [];
        let isSaving = false;
        let isDirty = false;

        function markDirty(dirty) {
            isDirty = Boolean(dirty);
            if (unsavedBadge) {
                unsavedBadge.hidden = !isDirty;
            }
        }

        // Listen for input changes across all form fields
        const allFormInputs = [
            fLanguage, fFirstName, fLastName, fFullName, fDob, fPob, fNationality, fGender,
            fEmail, fPhone, fStreet, fHouseNo, fPostal, fCity, fCountry, fCountryCode,
            fLinkedin, fPortfolio, fGithub,
            fCurrentTitle, fHeadline, fSummary, fPrimaryFields, rawJsonEl
        ].filter(Boolean);

        allFormInputs.forEach(input => {
            input.addEventListener("input", () => markDirty(true));
            input.addEventListener("change", () => markDirty(true));
        });

        function setStatus(msg, isError) {
            if (!statusBar) return;
            if (!msg) {
                statusBar.hidden = true;
                statusBar.textContent = "";
                statusBar.classList.remove("is-error");
                return;
            }
            statusBar.hidden = false;
            statusBar.textContent = msg;
            statusBar.classList.toggle("is-error", Boolean(isError));
            if (!isError) {
                setTimeout(() => {
                    if (statusBar.textContent === msg) {
                        statusBar.hidden = true;
                    }
                }, 4000);
            }
        }

        function escapeHtml(str) {
            return String(str ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
        }

        function getInitials(name) {
            const parts = String(name || "").trim().split(/\s+/);
            if (!parts.length || !parts[0]) return "??";
            if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
            return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
        }

        // --- Tab Switching ---
        tabBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                const targetTab = btn.dataset.hubTab;
                tabBtns.forEach(b => b.classList.toggle("is-active", b === btn));
                tabPanes.forEach(p => p.classList.toggle("is-active", p.dataset.hubPane === targetTab));

                if (targetTab === "rawjson" && currentProfileData) {
                    syncFormToCurrentData();
                    rawJsonEl.value = JSON.stringify(currentProfileData, null, 2);
                }
            });
        });

        // --- Sandbox Expand / Fullscreen Toggle ---
        if (btnExpandSandbox && sandboxCard) {
            const expandIcon = btnExpandSandbox.querySelector(".expand-icon");
            const shrinkIcon = btnExpandSandbox.querySelector(".shrink-icon");

            btnExpandSandbox.addEventListener("click", () => {
                const isExpanded = sandboxCard.classList.toggle("is-expanded");
                if (expandIcon) expandIcon.hidden = isExpanded;
                if (shrinkIcon) shrinkIcon.hidden = !isExpanded;
            });

            document.addEventListener("keydown", (e) => {
                if (e.key === "Escape" && sandboxCard.classList.contains("is-expanded")) {
                    sandboxCard.classList.remove("is-expanded");
                    if (expandIcon) expandIcon.hidden = false;
                    if (shrinkIcon) shrinkIcon.hidden = true;
                }
            });
        }

        // --- Sandbox Handlers ---
        if (btnLoadDeForm && btnLoadFrForm && sandboxIframe) {
            btnLoadDeForm.addEventListener("click", () => {
                btnLoadDeForm.classList.add("is-active");
                btnLoadDeForm.setAttribute("aria-selected", "true");
                btnLoadFrForm.classList.remove("is-active");
                btnLoadFrForm.setAttribute("aria-selected", "false");
                sandboxIframe.src = "/test-form";
                if (sandboxUrlPill) sandboxUrlPill.textContent = "/test-form";
                if (browserAddressText) browserAddressText.textContent = "http://localhost:5000/test-form";
                if (linkOpenSandboxTab) linkOpenSandboxTab.href = "/test-form";
            });

            btnLoadFrForm.addEventListener("click", () => {
                btnLoadFrForm.classList.add("is-active");
                btnLoadFrForm.setAttribute("aria-selected", "true");
                btnLoadDeForm.classList.remove("is-active");
                btnLoadDeForm.setAttribute("aria-selected", "false");
                sandboxIframe.src = "/french-form";
                if (sandboxUrlPill) sandboxUrlPill.textContent = "/french-form";
                if (browserAddressText) browserAddressText.textContent = "http://localhost:5000/french-form";
                if (linkOpenSandboxTab) linkOpenSandboxTab.href = "/french-form";
            });

            btnRefreshSandbox?.addEventListener("click", () => {
                try {
                    sandboxIframe.contentWindow?.location.reload();
                } catch {
                    sandboxIframe.src = sandboxIframe.src;
                }
            });
        }

        // --- Load Profiles List ---
        async function loadProfilesList(preferredId) {
            try {
                const res = await fetch("/api/autofill/profiles");
                if (!res.ok) throw new Error("Fehler beim Abrufen der Profile");
                const data = await res.json();
                cachedProfiles = data.profiles || [];

                profileSelector.innerHTML = "";
                if (!cachedProfiles.length) {
                    profileSelector.innerHTML = '<option value="">Keine Profile vorhanden</option>';
                    return;
                }

                cachedProfiles.forEach(p => {
                    const opt = document.createElement("option");
                    opt.value = p.id;
                    opt.textContent = `${p.name} (${p.id})`;
                    profileSelector.appendChild(opt);
                });

                const targetId = preferredId || (cachedProfiles.some(p => p.id === currentProfileId) ? currentProfileId : cachedProfiles[0].id);
                profileSelector.value = targetId;
                await selectProfile(targetId);
            } catch (err) {
                setStatus("Profile konnten nicht geladen werden: " + err.message, true);
            }
        }

        // --- Select & Render Profile ---
        async function selectProfile(profileId) {
            if (!profileId) return;
            currentProfileId = profileId;
            try {
                setStatus("Lade Profil " + profileId + "...");
                const res = await fetch(`/api/autofill/profiles/${encodeURIComponent(profileId)}`);
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const data = await res.json();
                currentProfileData = data;
                renderProfileForm(data);
                markDirty(false);
                setStatus("");
                await Promise.all([
                    loadDocuments(profileId),
                    loadCorrections(),
                    loadApplicationHistory()
                ]);
            } catch (err) {
                setStatus("Fehler beim Laden des Profils: " + err.message, true);
            }
        }

        profileSelector?.addEventListener("change", (e) => {
            if (isDirty) {
                const proceed = confirm("Es gibt ungespeicherte Änderungen am aktuellen Profil. Möchten Sie wirklich wechseln und die Änderungen verwerfen?");
                if (!proceed) {
                    profileSelector.value = currentProfileId;
                    return;
                }
            }
            selectProfile(e.target.value);
        });

        // --- Populate Form Fields from Profile JSON ---
        function renderProfileForm(data) {
            const applicant = data.applicant || {};
            const personal = applicant.personal || {};
            const contact = applicant.contact || {};
            const address = contact.address || {};
            const prof = applicant.professional_profile || {};

            fProfileId.value = currentProfileId;
            fProfileId.readOnly = true;
            fLanguage.value = data.profile_language || "de";

            fFirstName.value = personal.first_name || "";
            fLastName.value = personal.last_name || "";
            fFullName.value = personal.full_name || `${personal.first_name || ""} ${personal.last_name || ""}`.trim();
            fDob.value = personal.date_of_birth || "";
            fPob.value = personal.place_of_birth || "";
            fNationality.value = personal.nationality || "";
            fGender.value = personal.gender || "male";

            fEmail.value = contact.email || "";
            fPhone.value = contact.phone_display || contact.phone || "";
            fStreet.value = address.street || "";
            fHouseNo.value = address.house_number || "";
            fPostal.value = address.postal_code || "";
            fCity.value = address.city || "";
            fCountry.value = address.country || "";
            fCountryCode.value = address.country_code || "";

            fLinkedin.value = contact.linkedin?.url || "";
            fPortfolio.value = contact.portfolio?.url || "";
            fGithub.value = contact.github?.url || "";

            fCurrentTitle.value = prof.current_title || "";
            fHeadline.value = prof.headline || "";
            fSummary.value = prof.summary_de || prof.summary_fr || prof.summary_en || "";
            fPrimaryFields.value = Array.isArray(prof.primary_fields) ? prof.primary_fields.join(", ") : "";

            // Update candidate badge
            const name = fFullName.value || currentProfileId;
            if (displayNameEl) displayNameEl.textContent = name;
            if (avatarEl) avatarEl.textContent = getInitials(name);
            if (displayMetaEl) {
                const parts = [prof.current_title, address.city, (data.profile_language || "de").toUpperCase()].filter(Boolean);
                displayMetaEl.textContent = parts.join(" • ") || "Kandidatenprofil";
            }

            rawJsonEl.value = JSON.stringify(data, null, 2);
        }

        // --- Sync Form Input to Data Object ---
        function syncFormToCurrentData() {
            if (!currentProfileData) {
                currentProfileData = { applicant: { personal: {}, contact: { address: {} }, professional_profile: {} } };
            }
            const data = currentProfileData;
            data.profile_language = fLanguage.value || "de";

            data.applicant = data.applicant || {};
            data.applicant.personal = data.applicant.personal || {};
            data.applicant.contact = data.applicant.contact || {};
            data.applicant.contact.address = data.applicant.contact.address || {};
            data.applicant.professional_profile = data.applicant.professional_profile || {};

            const p = data.applicant.personal;
            p.first_name = fFirstName.value.trim();
            p.last_name = fLastName.value.trim();
            p.full_name = fFullName.value.trim() || `${p.first_name} ${p.last_name}`.trim();
            p.date_of_birth = fDob.value.trim() || null;
            p.place_of_birth = fPob.value.trim() || null;
            p.nationality = fNationality.value.trim() || null;
            p.gender = fGender.value;

            const c = data.applicant.contact;
            c.email = fEmail.value.trim();
            c.phone = fPhone.value.trim();
            c.phone_display = fPhone.value.trim();
            c.address.street = fStreet.value.trim() || null;
            c.address.house_number = fHouseNo.value.trim() || null;
            c.address.postal_code = fPostal.value.trim() || null;
            c.address.city = fCity.value.trim() || null;
            c.address.country = fCountry.value.trim() || null;
            c.address.country_code = fCountryCode.value.trim() || null;

            c.linkedin = c.linkedin || {};
            c.linkedin.url = fLinkedin.value.trim() || null;

            c.portfolio = c.portfolio || {};
            c.portfolio.url = fPortfolio.value.trim() || null;

            c.github = c.github || {};
            c.github.url = fGithub.value.trim() || null;

            const prof = data.applicant.professional_profile;
            prof.current_title = fCurrentTitle.value.trim();
            prof.headline = fHeadline.value.trim();
            if (data.profile_language === "fr") {
                prof.summary_fr = fSummary.value.trim();
            } else {
                prof.summary_de = fSummary.value.trim();
            }
            prof.primary_fields = fPrimaryFields.value
                .split(",")
                .map(s => s.trim())
                .filter(Boolean);
        }

        // --- Save Profile ---
        btnSaveProfile?.addEventListener("click", async () => {
            if (isSaving) return;
            const targetPane = tabPanes.find(p => p.classList.contains("is-active"));
            if (targetPane?.dataset.hubPane === "rawjson") {
                try {
                    currentProfileData = JSON.parse(rawJsonEl.value);
                } catch (e) {
                    setStatus("Ungültiges JSON: " + e.message, true);
                    return;
                }
            } else {
                syncFormToCurrentData();
            }

            const profileId = (fProfileId.value || currentProfileId).trim();
            if (!profileId) {
                setStatus("Profil-ID darf nicht leer sein", true);
                return;
            }

            try {
                isSaving = true;
                btnSaveProfile.disabled = true;
                btnSaveProfile.textContent = "Speichere...";
                setStatus("Speichere Profil...");

                const payload = {
                    ...currentProfileData,
                    id: profileId,
                    profileId: profileId
                };

                const res = await fetch("/api/autofill/profiles", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });

                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const result = await res.json();
                markDirty(false);
                setStatus("✓ Profil erfolgreich gespeichert!");
                await loadProfilesList(result.profileId || profileId);
            } catch (err) {
                setStatus("Fehler beim Speichern: " + err.message, true);
            } finally {
                isSaving = false;
                btnSaveProfile.disabled = false;
                btnSaveProfile.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg> Profil speichern`;
            }
        });

        // --- New Profile ---
        btnNewProfile?.addEventListener("click", () => {
            if (isDirty) {
                const proceed = confirm("Es gibt ungespeicherte Änderungen. Möchten Sie wirklich ein neues Profil erstellen und die Änderungen verwerfen?");
                if (!proceed) return;
            }
            const newId = prompt("Bitte Profil-ID / Kürzel eingeben (z. B. max_mustermann):");
            if (!newId) return;
            const cleanId = newId.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "_");
            if (!cleanId) return;

            currentProfileId = cleanId;
            currentProfileData = {
                profile_version: "1.0",
                profile_language: "de",
                applicant: {
                    personal: { first_name: "", last_name: "", full_name: "", gender: "male" },
                    contact: { email: "", phone: "", address: { city: "Berlin", country: "Deutschland" } },
                    professional_profile: { current_title: "", primary_fields: [] }
                }
            };
            fProfileId.value = cleanId;
            fProfileId.readOnly = false;
            renderProfileForm(currentProfileData);
            markDirty(true);
            documentListEl.innerHTML = '<div class="doc-empty-state">Neues Profil. Bitte Unterlagen hochladen.</div>';
            setStatus(`Neues Profil "${cleanId}" vorbereitet. Daten ausfüllen und "Profil speichern" klicken.`);
        });

        // --- Document Management ---
        async function loadDocuments(profileId) {
            if (!documentListEl) return;
            try {
                const res = await fetch(`/api/autofill/profiles/${encodeURIComponent(profileId)}/documents`);
                if (!res.ok) throw new Error("HTTP " + res.status);
                const data = await res.json();
                const docs = data.documents || [];

                if (docCountEl) docCountEl.textContent = `${docs.length} Dokument${docs.length === 1 ? "" : "e"}`;

                if (!docs.length) {
                    documentListEl.innerHTML = '<div class="doc-empty-state">Keine Dokumente für dieses Profil hinterlegt. Laden Sie ein Dokument oben hoch.</div>';
                    return;
                }

                documentListEl.innerHTML = docs.map(doc => {
                    const ext = (doc.extension || "").toUpperCase();
                    const sizeKb = Math.round((doc.size || 0) / 1024);
                    return `
                        <div class="af-doc-row" data-filename="${escapeHtml(doc.fileName)}">
                            <div class="doc-info">
                                <span class="doc-ext-badge ${ext.toLowerCase()}">${escapeHtml(ext)}</span>
                                <div class="doc-text">
                                    <strong class="doc-name">${escapeHtml(doc.fileName)}</strong>
                                    <span class="doc-meta">${sizeKb} KB ${doc.isSensitive ? '• <span class="sensitive-pill">Sensibel</span>' : ''}</span>
                                </div>
                            </div>
                            <div class="doc-actions">
                                <a href="${doc.previewUrl}" target="_blank" rel="noopener noreferrer" class="doc-btn-preview" title="Vorschau im Tab">Vorschau</a>
                                <a href="${doc.downloadUrl}" download class="doc-btn-download" title="Herunterladen">Download</a>
                                <button type="button" class="doc-btn-delete" data-doc-delete="${escapeHtml(doc.fileName)}" title="Löschen">Löschen</button>
                            </div>
                        </div>
                    `;
                }).join("");

                // Bind delete buttons
                documentListEl.querySelectorAll("[data-doc-delete]").forEach(btn => {
                    btn.addEventListener("click", async () => {
                        const fname = btn.dataset.docDelete;
                        if (!confirm(`Dokument "${fname}" wirklich löschen?`)) return;
                        try {
                            const delRes = await fetch(`/api/autofill/profiles/${encodeURIComponent(profileId)}/documents/${encodeURIComponent(fname)}`, {
                                method: "DELETE"
                            });
                            if (!delRes.ok) throw new Error("Fehler beim Löschen");
                            setStatus(`✓ ${fname} gelöscht`);
                            await loadDocuments(profileId);
                        } catch (e) {
                            setStatus("Löschen fehlgeschlagen: " + e.message, true);
                        }
                    });
                });
            } catch (err) {
                documentListEl.innerHTML = `<div class="doc-empty-state">Dokumente konnten nicht geladen werden (${escapeHtml(err.message)})</div>`;
            }
        }

        // --- File Upload Handler ---
        fileUploadInput?.addEventListener("change", async (e) => {
            const file = e.target.files?.[0];
            if (!file || !currentProfileId) return;

            const formData = new FormData();
            formData.append("file", file);

            try {
                setStatus(`Lade ${file.name} hoch...`);
                const res = await fetch(`/api/autofill/profiles/${encodeURIComponent(currentProfileId)}/documents`, {
                    method: "POST",
                    body: formData
                });
                if (!res.ok) {
                    const errJson = await res.json().catch(() => ({}));
                    throw new Error(errJson.error || `HTTP ${res.status}`);
                }
                setStatus(`✓ Dokument "${file.name}" erfolgreich hochgeladen!`);
                await loadDocuments(currentProfileId);
            } catch (err) {
                setStatus("Upload fehlgeschlagen: " + err.message, true);
            } finally {
                fileUploadInput.value = "";
            }
        });

        // --- Import CV via PDF ---
        if (btnImportCv && afCvFileInput) {
            btnImportCv.addEventListener("click", () => afCvFileInput.click());
            afCvFileInput.addEventListener("change", async (e) => {
                const file = e.target.files && e.target.files[0];
                if (!file) return;

                const origHtml = btnImportCv.innerHTML;
                btnImportCv.innerHTML = "<span>Analysiere CV...</span>";
                btnImportCv.disabled = true;
                setStatus("Analysiere Lebenslauf-PDF und extrahiere Profildaten...");

                const formData = new FormData();
                formData.append("cv_file", file);

                try {
                    const res = await fetch("/api/clients/ingest-cv", {
                        method: "POST",
                        body: formData
                    });
                    const result = await res.json();
                    if (res.ok && result.success) {
                        setStatus(`✓ Bewerber "${result.client_name}" erfolgreich aus Lebenslauf importiert!`);
                        if (window.refreshGlobalClients) {
                            window.refreshGlobalClients(result.client_id);
                        }
                        await loadProfilesList(result.client_id);
                    } else {
                        setStatus("Import fehlgeschlagen: " + (result.error || "Unbekannter Fehler"), true);
                    }
                } catch (err) {
                    setStatus("Netzwerkfehler beim CV-Import: " + err.message, true);
                } finally {
                    btnImportCv.innerHTML = origHtml;
                    btnImportCv.disabled = false;
                    afCvFileInput.value = "";
                }
            });
        }

        // --- Set Active Client Button ---
        if (btnSetActive) {
            btnSetActive.addEventListener("click", async () => {
                if (!currentProfileId) return;
                try {
                    const res = await fetch("/api/clients/active", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ client_id: currentProfileId })
                    });
                    if (res.ok) {
                        setStatus(`⭐ Profil "${currentProfileId}" ist jetzt der aktive Bewerber!`);
                        if (window.refreshGlobalClients) {
                            window.refreshGlobalClients(currentProfileId);
                        }
                        await loadProfilesList(currentProfileId);
                    }
                } catch (err) {
                    setStatus("Konnte nicht als aktiv gesetzt werden: " + err.message, true);
                }
            });
        }

        // Listen for global client change from header
        window.addEventListener("activeClientChanged", (e) => {
            const newId = e.detail && e.detail.clientId;
            if (newId && newId !== currentProfileId) {
                loadProfilesList(newId);
            }
        });

        // --- Corrections Memory ---
        async function loadCorrections() {
            if (!correctionsListEl) return;
            try {
                const res = await fetch("/api/autofill/corrections");
                if (!res.ok) throw new Error("HTTP " + res.status);
                const data = await res.json();
                const list = data.corrections || [];

                if (!list.length) {
                    correctionsListEl.innerHTML = '<div class="doc-empty-state">Noch keine erlernten Feld-Korrekturen gespeichert. Wenn Sie in der Extension ein Feld anpassen, wird es hier erfasst.</div>';
                    return;
                }

                correctionsListEl.innerHTML = list.map(c => `
                    <div class="correction-item" data-corr-id="${escapeHtml(c.id || "")}">
                        <div class="corr-meta">
                            <span class="corr-domain">${escapeHtml(c.domain || "Global")}</span>
                            <span class="corr-field">Feld: <code>${escapeHtml(c.fieldSignature || c.fieldLabel || "Feld")}</code></span>
                        </div>
                        <div class="corr-val">
                            Wert: <strong>${escapeHtml(c.correctedValue || "")}</strong>
                        </div>
                        <button type="button" class="corr-del-btn" data-del-corr="${escapeHtml(c.id || "")}" title="Löschen">✕</button>
                    </div>
                `).join("");

                correctionsListEl.querySelectorAll("[data-del-corr]").forEach(b => {
                    b.addEventListener("click", async () => {
                        const id = b.dataset.delCorr;
                        try {
                            await fetch(`/api/autofill/corrections?id=${encodeURIComponent(id)}`, { method: "DELETE" });
                            await loadCorrections();
                        } catch {}
                    });
                });
            } catch (err) {
                correctionsListEl.innerHTML = '<div class="doc-empty-state">Korrekturen konnten nicht geladen werden.</div>';
            }
        }

        btnClearCorrections?.addEventListener("click", async () => {
            if (!confirm("Alle erlernten Korrekturen wirklich löschen?")) return;
            try {
                await fetch("/api/autofill/corrections?all=true", { method: "DELETE" });
                setStatus("✓ Alle Korrekturen gelöscht");
                await loadCorrections();
            } catch (e) {
                setStatus("Löschen fehlgeschlagen", true);
            }
        });

        // --- Application Tracking History ---
        async function loadApplicationHistory() {
            if (!historyBody) return;
            try {
                const res = await fetch("/api/autofill/applications");
                if (!res.ok) throw new Error("HTTP " + res.status);
                const data = await res.json();
                const apps = data.applications || [];

                if (!apps.length) {
                    historyBody.innerHTML = '<tr><td colspan="6" class="af-history-empty">Noch keine Bewerbungen über Autofill erfasst. Klicke bei einer Stelle auf "⚡ Open & Autofill", um direkt zu starten!</td></tr>';
                    return;
                }

                historyBody.innerHTML = apps.map(app => {
                    const title = escapeHtml(app.title || "Job Application");
                    const company = escapeHtml(app.company || app.domain || "k. A.");
                    const profile = escapeHtml(app.profileId || app.profile_id || "Standard");
                    const fields = Number(app.fieldsFilled || app.fields_filled || 0);
                    const date = escapeHtml(app.date || app.created_at || "k. A.");
                    const url = escapeHtml(app.url || (app.domain ? `https://${app.domain}` : "#"));

                    return `
                        <tr>
                            <td><strong>${title}</strong></td>
                            <td>${company}</td>
                            <td><span class="hub-pill af-history-pill">${profile}</span></td>
                            <td><span class="hub-pill af-history-pill pill-success">${fields} Felder</span></td>
                            <td><small>${date}</small></td>
                            <td style="text-align: right;">
                                <a href="${url}" target="_blank" rel="noopener noreferrer" class="history-action-btn">Öffnen ↗</a>
                            </td>
                        </tr>
                    `;
                }).join("");
            } catch (err) {
                historyBody.innerHTML = '<tr><td colspan="6" class="af-history-empty">Verlauf konnte nicht geladen werden.</td></tr>';
            }
        }

        btnRefreshHistory?.addEventListener("click", loadApplicationHistory);

        return {
            show() {
                loadProfilesList();
                loadCorrections();
                loadApplicationHistory();
            },
            hide() {}
        };
    };
})();

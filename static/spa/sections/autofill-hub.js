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

            const btnAutofillSandbox = document.getElementById("btn-autofill-sandbox-now");
            btnAutofillSandbox?.addEventListener("click", autofillSandboxForm);

            // Automatically populate sandbox form when iframe finishes loading
            sandboxIframe.addEventListener("load", () => {
                if (currentProfileData) {
                    setTimeout(() => {
                        try {
                            autofillSandboxForm();
                        } catch (err) {
                            console.warn("[Autofill Hub] Auto-fill on load error:", err);
                        }
                    }, 350);
                }
            });
        }

        // Attach global handler so inline onclick also invokes it directly
        window.autofillSandboxForm = autofillSandboxForm;

        function autofillSandboxForm() {
            console.log("[Autofill Hub] Triggering sandbox autofill...", { sandboxIframe, currentProfileData });
            if (!sandboxIframe) {
                console.warn("[Autofill Hub] sandboxIframe element not found");
                return;
            }

            let doc;
            try {
                doc = sandboxIframe.contentDocument || sandboxIframe.contentWindow?.document;
            } catch (err) {
                console.error("[Autofill Hub] Cannot access sandbox iframe document:", err);
            }

            if (!doc || !doc.body) {
                setStatus("Sandbox-Iframe lädt noch. Bitte kurz warten.", true);
                return;
            }

            // Gather candidate values from inputs with fallback to loaded profile data
            const applicant = currentProfileData?.applicant || {};
            const pPersonal = applicant.personal || {};
            const pContact = applicant.contact || {};
            const pAddr = pContact.address || {};
            const pProf = applicant.professional_profile || {};

            let first = (fFirstName?.value || pPersonal.first_name || "").trim();
            let last = (fLastName?.value || pPersonal.last_name || "").trim();
            const full = (fFullName?.value || pPersonal.full_name || `${first} ${last}`).trim();

            if (!first && full) {
                const parts = full.split(/\s+/);
                first = parts[0] || "";
                last = parts.slice(1).join(" ") || "";
            }

            const email = (fEmail?.value || pContact.email || "").trim();
            const phone = (fPhone?.value || pContact.phone_display || pContact.phone || "").trim();
            const street = (fStreet?.value || pAddr.street || "").trim();
            const houseNo = (fHouseNo?.value || pAddr.house_number || "").trim();
            const fullStreet = `${street} ${houseNo}`.trim();
            const postal = (fPostal?.value || pAddr.postal_code || "").trim();
            const city = (fCity?.value || pAddr.city || "").trim();
            const country = (fCountry?.value || pAddr.country || "Deutschland").trim();
            const nationality = (fNationality?.value || pPersonal.nationality || "Moroccan").trim();
            const dob = (fDob?.value || pPersonal.date_of_birth || "").trim();
            const gender = (fGender?.value || pPersonal.gender || "male").toLowerCase();
            const title = (fCurrentTitle?.value || pProf.current_title || "").trim();
            const summary = (fSummary?.value || pProf.summary_de || pProf.summary_fr || pProf.summary_en || "").trim();

            if (!first && !last && !email && !phone) {
                setStatus("⚠️ Das aktuelle Profil enthält noch keine Daten. Bitte links eingeben oder einen vollständigen Bewerber wählen.", true);
                return;
            }

            let filledCount = 0;

            function highlightEl(el) {
                if (!el) return;
                const origBg = el.style.backgroundColor;
                const origBorder = el.style.borderColor;
                const origShadow = el.style.boxShadow;
                el.style.transition = "all 0.3s ease";
                el.style.backgroundColor = "#dcfce7";
                el.style.borderColor = "#10b981";
                el.style.boxShadow = "0 0 0 3px rgba(16, 185, 129, 0.25)";
                setTimeout(() => {
                    el.style.backgroundColor = origBg;
                    el.style.borderColor = origBorder;
                    el.style.boxShadow = origShadow;
                }, 2500);
            }

            function setVal(selector, val) {
                if (!val) return;
                const els = doc.querySelectorAll(selector);
                els.forEach(el => {
                    if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
                        el.value = val;
                        el.setAttribute("value", val);
                    } else if (el.tagName === "SELECT") {
                        let matched = false;
                        const sVal = val.toLowerCase();
                        for (let i = 0; i < el.options.length; i++) {
                            const opt = el.options[i];
                            const oVal = (opt.value || "").toLowerCase();
                            const oText = (opt.text || "").toLowerCase();
                            if (oVal === sVal || oText === sVal || oText.includes(sVal) ||
                                ((sVal.startsWith("moh") || sVal.startsWith("mar") || sVal.startsWith("mor") || sVal.includes("marok") || sVal.includes("moroc")) && (oVal === "ma" || oVal === "moroccan" || oText.includes("maroc") || oText.includes("morocc"))) ||
                                ((sVal.startsWith("de") || sVal.includes("deutsch") || sVal.includes("germ")) && (oVal === "de" || oVal === "german" || oText.includes("allem"))) ||
                                ((sVal.startsWith("fr") || sVal.includes("fran")) && (oVal === "fr" || oVal === "french" || oText.includes("fran")))) {
                                el.selectedIndex = i;
                                matched = true;
                                break;
                            }
                        }
                        if (!matched && el.options.length > 1) {
                            el.selectedIndex = 1;
                        }
                    }

                    // Trigger input and change events
                    el.dispatchEvent(new Event("input", { bubbles: true }));
                    el.dispatchEvent(new Event("change", { bubbles: true }));
                    highlightEl(el);
                    filledCount++;
                });
            }

            // --- German / English fields in /test-form ---
            setVal("#vorname, input[name='first_name']", first);
            setVal("#nachname, input[name='last_name']", last);
            setVal("#email, input[name='email']", email);
            setVal("#telefon, input[name='phone']", phone);
            setVal("#strasse, input[name='street']", fullStreet || street);
            setVal("#plz, input[name='postal_code']", postal);
            setVal("#stadt, input[name='city']", city);
            setVal("#country, select[name='country']", country);
            setVal("#expTitle, input[name='job_title']", title);
            setVal("#motivation, textarea[name='motivation_letter']", summary);

            // Experience toggle in /test-form step 2
            if (title) {
                const expCheck = doc.querySelector("#toggleExperience");
                if (expCheck && !expCheck.checked) {
                    expCheck.checked = true;
                    expCheck.dispatchEvent(new Event("change", { bubbles: true }));
                    const expCont = doc.querySelector("#dynamicExpContainer");
                    if (expCont) expCont.style.display = "block";
                    setVal("#expTitle", title);
                }
            }

            // Gender radio
            const isFem = (gender === "female" || gender === "weiblich" || gender === "femme" || gender === "f");
            const isDiv = (gender === "other" || gender === "divers" || gender === "diverse" || gender === "d");
            const targetGender = isFem ? "weiblich" : (isDiv ? "divers" : "männlich");
            const targetGenderFr = isFem ? "femme" : "homme";

            const radios = doc.querySelectorAll("input[type='radio'][name='gender'], input[type='radio'][name='civilite']");
            radios.forEach(radio => {
                const rVal = (radio.value || "").toLowerCase();
                if (rVal === targetGender || rVal === targetGenderFr || (targetGender === "männlich" && (rVal === "male" || rVal === "homme" || rVal === "m"))) {
                    radio.checked = true;
                    radio.dispatchEvent(new Event("change", { bubbles: true }));
                    highlightEl(radio.parentElement || radio);
                    filledCount++;
                }
            });

            // --- French form fields (/french-form and /test-form step 4) ---
            setVal("#prenom, #fr_prenom", first);
            setVal("#nom, #fr_nom", last);
            setVal("#ville, #fr_ville", city);
            setVal("#nationalite, #fr_nationalite, select[name='nationality']", nationality);
            setVal("#fr_adresse", fullStreet || street);
            setVal("#fr_email", email);
            setVal("#fr_tel", phone);
            setVal("#fr_code_postal", postal);
            setVal("#fr_pays", country);
            setVal("#ai_extra_remarks, #ai_unlabeled_remarks", summary || title);

            // DOB Custom Date Picker handling
            if (dob) {
                let dobDisplay = dob;
                if (/^\d{4}-\d{2}-\d{2}$/.test(dob)) {
                    const [y, m, d] = dob.split("-");
                    dobDisplay = `${d}/${m}/${y}`;
                }
                const dateInputs = doc.querySelectorAll("#dobInput, #fr_dob, input.datepicker-input");
                dateInputs.forEach(inp => {
                    inp.value = dobDisplay;
                    inp.setAttribute("value", dobDisplay);
                    inp.dataset.acceptedDate = dobDisplay;
                    inp.dispatchEvent(new Event("input", { bubbles: true }));
                    inp.dispatchEvent(new Event("change", { bubbles: true }));
                    highlightEl(inp);
                    filledCount++;
                });
            }

            // Button feedback
            const btn = document.getElementById("btn-autofill-sandbox-now");
            if (btn) {
                const orig = btn.innerHTML;
                btn.innerHTML = `<span style="display:inline-flex;align-items:center;gap:4px;"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg> ${filledCount} Felder ausgefüllt!</span>`;
                btn.style.background = "#10b981";
                setTimeout(() => {
                    btn.innerHTML = orig;
                    btn.style.background = "#0284c7";
                }, 2500);
            }

            setStatus(`✓ Sandbox-Formular erfolgreich mit den Daten von "${full || first || 'Bewerber'}" ausgefüllt (${filledCount} Felder)!`, false);
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
                    profileSelector.innerHTML = '<option value="">No profiles available</option>';
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
                    setStatus("Invalid JSON: " + e.message, true);
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
                setStatus("✓ Profile saved successfully!");
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
            const newId = prompt("Enter candidate ID / slug (e.g. john_doe):");
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
            documentListEl.innerHTML = '<div class="doc-empty-state">New profile. Please upload documents.</div>';
            setStatus(`New profile "${cleanId}" created. Fill in details and click "Save Profile".`);
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
                                <button type="button" class="doc-btn-delete" data-doc-delete="${escapeHtml(doc.fileName)}" title="Delete">Löschen</button>
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
                        <button type="button" class="corr-del-btn" data-del-corr="${escapeHtml(c.id || "")}" title="Delete">✕</button>
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

        window.addEventListener("activeClientChanged", (e) => {
            if (e.detail?.clientId && root && !root.hidden) {
                loadProfilesList(e.detail.clientId);
            }
        });

        return {
            show() {
                const targetId = window.sessionStorage?.getItem("autofill:target-client-id");
                if (targetId) {
                    try { window.sessionStorage.removeItem("autofill:target-client-id"); } catch (_) {}
                    loadProfilesList(targetId);
                } else {
                    loadProfilesList();
                }
                loadCorrections();
                loadApplicationHistory();
            },
            hide() {}
        };
    };
})();

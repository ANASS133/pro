(function () {
    const root = document.querySelector(".spa-shell");
    if (!root) {
        return;
    }

    const routeToSection = {
        "/": "search",
        "/dashboard": "dashboard",
        "/firebase": "supabase",
        "/supabase": "supabase",
        "/money": "money",
        "/ausbildungen": "ausbildungen",
        "/create-anschreibens": "create-anschreibens",
        "/send-emails": "send-emails",
        "/google-maps": "google-maps",
        "/autofill": "autofill",
        "/autofill-hub": "autofill",
    };

    const sectionToRoute = {
        search: "/",
        dashboard: "/dashboard",
        supabase: "/supabase",
        money: "/money",
        ausbildungen: "/ausbildungen",
        "create-anschreibens": "/create-anschreibens",
        "send-emails": "/send-emails",
        "google-maps": "/google-maps",
        autofill: "/autofill",
    };

    const titleBySection = {
        search: "Arbeitsagentur Scraper | Suche",
        dashboard: "Arbeitsagentur Scraper | Dashboard",
        supabase: "Arbeitsagentur Scraper | Supabase",
        money: "Arbeitsagentur Scraper | Money",
        ausbildungen: "Arbeitsagentur Scraper | Ausbildungen",
        "create-anschreibens": "Arbeitsagentur Scraper | Anschreiben",
        "send-emails": "Arbeitsagentur Scraper | E-Mails senden",
        "google-maps": "Arbeitsagentur Scraper | Google Maps",
        autofill: "Arbeitsagentur Scraper | Autofill Hub",
    };

    const sections = Array.from(document.querySelectorAll("[data-section]"));
    const navLinks = Array.from(document.querySelectorAll("[data-section-link]"));
    const factories = window.SPASections || {};
    const controllers = {
        search: typeof factories.createSearchSection === "function"
            ? factories.createSearchSection()
            : { show() {}, hide() {} },
        dashboard: typeof factories.createDashboardSection === "function"
            ? factories.createDashboardSection()
            : { show() {}, hide() {} },
        supabase: typeof factories.createSupabaseSection === "function"
            ? factories.createSupabaseSection()
            : { show() {}, hide() {} },
        money: typeof factories.createMoneySection === "function"
            ? factories.createMoneySection()
            : { show() {}, hide() {} },
        ausbildungen: typeof factories.createAusbildungenSection === "function"
            ? factories.createAusbildungenSection()
            : { show() {}, hide() {} },
        "create-anschreibens": typeof factories.createCreateAnschreibensSection === "function"
            ? factories.createCreateAnschreibensSection()
            : { show() {}, hide() {} },
        "send-emails": typeof factories.createSendEmailsSection === "function"
            ? factories.createSendEmailsSection()
            : { show() {}, hide() {} },
        "google-maps": typeof factories.createGoogleMapsSection === "function"
            ? factories.createGoogleMapsSection()
            : { show() {}, hide() {} },
        autofill: typeof factories.createAutofillHubSection === "function"
            ? factories.createAutofillHubSection()
            : { show() {}, hide() {} },
    };

    let activeSection = "";

    function normalizePath(pathname) {
        const value = String(pathname || "/").trim() || "/";
        if (value.length > 1 && value.endsWith("/")) {
            return value.slice(0, -1);
        }
        return value;
    }

    function getSectionForPath(pathname) {
        return routeToSection[normalizePath(pathname)] || window.APP_INITIAL_SECTION || "search";
    }

    function setActiveNav(sectionKey) {
        navLinks.forEach((link) => {
            const isActive = String(link.dataset.sectionLink || "") === sectionKey;
            link.classList.toggle("is-active", isActive);
            if (isActive) {
                link.setAttribute("aria-current", "page");
            } else {
                link.removeAttribute("aria-current");
            }
        });
    }

    function showSection(sectionKey, pushState) {
        const normalizedSection = sectionToRoute[sectionKey] ? sectionKey : "search";

        if (normalizedSection === activeSection) {
            if (pushState && normalizePath(window.location.pathname) !== sectionToRoute[normalizedSection]) {
                window.history.pushState({}, "", sectionToRoute[normalizedSection]);
            }
            setActiveNav(normalizedSection);
            document.title = titleBySection[normalizedSection] || titleBySection.search;
            return;
        }

        if (activeSection && controllers[activeSection] && typeof controllers[activeSection].hide === "function") {
            controllers[activeSection].hide();
        }

        sections.forEach((section) => {
            section.hidden = String(section.dataset.section || "") !== normalizedSection;
        });

        activeSection = normalizedSection;
        setActiveNav(normalizedSection);
        document.title = titleBySection[normalizedSection] || titleBySection.search;

        if (pushState && normalizePath(window.location.pathname) !== sectionToRoute[normalizedSection]) {
            window.history.pushState({}, "", sectionToRoute[normalizedSection]);
        }

        if (controllers[normalizedSection] && typeof controllers[normalizedSection].show === "function") {
            controllers[normalizedSection].show();
        }
    }

    document.addEventListener("click", (event) => {
        const link = event.target.closest("[data-section-link]");
        if (!link) {
            return;
        }

        event.preventDefault();
        showSection(String(link.dataset.sectionLink || "search"), true);
    });

    window.addEventListener("popstate", () => {
        showSection(getSectionForPath(window.location.pathname), false);
    });

    showSection(getSectionForPath(window.location.pathname), false);

    // Sidebar Collapse Logic
    const sidebar = document.getElementById("shell-sidebar");
    const collapseBtn = document.getElementById("sidebar-collapse-btn");

    if (sidebar && collapseBtn) {
        const isCollapsed = localStorage.getItem("sidebar_collapsed") === "true";
        if (isCollapsed) {
            sidebar.classList.add("is-collapsed");
        }

        const toggleSidebar = () => {
            sidebar.classList.toggle("is-collapsed");
            const collapsedNow = sidebar.classList.contains("is-collapsed");
            localStorage.setItem("sidebar_collapsed", collapsedNow ? "true" : "false");
        };

        collapseBtn.addEventListener("click", toggleSidebar);

        const brandBadge = document.getElementById("sidebar-brand-badge");
        if (brandBadge) {
            brandBadge.addEventListener("click", () => {
                if (sidebar.classList.contains("is-collapsed")) {
                    toggleSidebar();
                }
            });
        }
    }

    // Health Status Check
    const statusIndicator = document.getElementById("system-status-indicator");
    if (statusIndicator) {
        fetch("/api/health")
            .then((res) => res.json())
            .then((data) => {
                const dot = statusIndicator.querySelector(".status-dot");
                const label = statusIndicator.querySelector(".status-label");
                if (data && data.status === "healthy") {
                    if (dot) dot.style.background = "#10b981";
                    if (label) label.textContent = "Online";
                } else {
                    if (dot) dot.style.background = "#f59e0b";
                    if (label) label.textContent = "Warnung";
                }
            })
            .catch(() => {
                const dot = statusIndicator.querySelector(".status-dot");
                const label = statusIndicator.querySelector(".status-label");
                if (dot) dot.style.background = "#ef4444";
                if (label) label.textContent = "Offline";
            });
    }

    // Live Task Monitoring via SQLite & SSE
    const liveJobWidget = document.getElementById("sidebar-live-job");
    const jobTitle = document.getElementById("sidebar-job-title");
    const jobPercent = document.getElementById("sidebar-job-percent");
    const jobFill = document.getElementById("sidebar-job-fill");
    const jobMeta = document.getElementById("sidebar-job-meta");

    function checkActiveJobs() {
        fetch("/api/jobs?limit=5")
            .then((res) => res.json())
            .then((data) => {
                const jobs = (data && data.jobs) || [];
                const runningJob = jobs.find((j) => j.is_running);
                if (runningJob && liveJobWidget) {
                    liveJobWidget.hidden = false;
                    const pct = runningJob.total > 0 ? Math.round((runningJob.progress / runningJob.total) * 100) : 0;
                    if (jobTitle) jobTitle.textContent = runningJob.job_type.replace(/_/g, " ");
                    if (jobPercent) jobPercent.textContent = pct + "%";
                    if (jobFill) jobFill.style.width = pct + "%";
                    if (jobMeta) jobMeta.textContent = `${runningJob.progress} / ${runningJob.total} (${runningJob.phase})`;

                    if (!window._activeJobEventSource && window.EventSource) {
                        const es = new EventSource(`/api/jobs/${runningJob.job_id}/stream`);
                        window._activeJobEventSource = es;
                        es.onmessage = (e) => {
                            try {
                                const update = JSON.parse(e.data);
                                const uPct = update.total > 0 ? Math.round((update.progress / update.total) * 100) : 0;
                                if (jobPercent) jobPercent.textContent = uPct + "%";
                                if (jobFill) jobFill.style.width = uPct + "%";
                                if (jobMeta) jobMeta.textContent = `${update.progress} / ${update.total} (${update.phase})`;
                            } catch (_) {}
                        };
                        es.addEventListener("close", () => {
                            es.close();
                            window._activeJobEventSource = null;
                            setTimeout(checkActiveJobs, 2000);
                        });
                        es.onerror = () => {
                            es.close();
                            window._activeJobEventSource = null;
                        };
                    }
                } else if (liveJobWidget) {
                    liveJobWidget.hidden = true;
                }
            })
            .catch(() => {});
    }

    checkActiveJobs();
    setInterval(checkActiveJobs, 15000);

    // ---------------------------------------------------------------------------
    // Candidate Profile & AI Memory Hub Controller
    // ---------------------------------------------------------------------------
    const profileBtn = document.getElementById("sidebar-profile-btn");
    const profileModal = document.getElementById("profileHubModal");
    const closeProfileBtn = document.getElementById("closeProfileModalBtn");
    const profileSummaryInput = document.getElementById("profileSummaryInput");
    const saveProfileBtn = document.getElementById("saveProfileBtn");
    const profileSaveStatus = document.getElementById("profileSaveStatus");
    const profileSkillsCloud = document.getElementById("profileSkillsCloud");

    function openProfileHub() {
        if (!profileModal) return;
        profileModal.hidden = false;
        fetchProfileData();
    }

    function closeProfileHub() {
        if (profileModal) profileModal.hidden = true;
    }

    async function fetchProfileData() {
        try {
            const resp = await fetch("/api/profile/anass_sibbi");
            if (!resp.ok) return;
            const data = await resp.json();
            const applicant = data.applicant || {};
            const personal = applicant.personal || {};
            const prof = applicant.professional_profile || {};
            const skills = applicant.skills || {};

            const profileNameEl = document.getElementById("profileName");
            const profileRoleEl = document.getElementById("profileRole");
            if (profileNameEl && personal.full_name) {
                profileNameEl.textContent = personal.full_name;
            }
            if (profileRoleEl && prof.current_title) {
                profileRoleEl.textContent = prof.alternative_title
                    ? `${prof.current_title} | ${prof.alternative_title}`
                    : prof.current_title;
            }

            if (profileSummaryInput) {
                profileSummaryInput.value = prof.summary_de || prof.summary_en || "";
            }

            if (profileSkillsCloud) {
                profileSkillsCloud.innerHTML = "";
                const categories = [
                    { label: "Sprachen", list: skills.programming_languages || [] },
                    { label: "Backend", list: skills.backend || [] },
                    { label: "Frontend", list: skills.frontend || [] },
                    { label: "Tools & Cloud", list: skills.tools || [] },
                ];
                categories.forEach((cat) => {
                    if (!cat.list.length) return;
                    cat.list.forEach((skill) => {
                        const pill = document.createElement("span");
                        pill.className = "profile-skill-tag";
                        pill.textContent = skill;
                        profileSkillsCloud.appendChild(pill);
                    });
                });
            }
        } catch (_) {}
    }

    async function saveProfileData() {
        if (!profileSummaryInput || !saveProfileBtn) return;
        saveProfileBtn.disabled = true;
        try {
            const updatedSummary = profileSummaryInput.value.trim();
            const resp = await fetch("/api/profile/anass_sibbi", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    professional_profile: {
                        summary_de: updatedSummary,
                    },
                }),
            });
            if (resp.ok) {
                if (profileSaveStatus) {
                    profileSaveStatus.hidden = false;
                    setTimeout(() => {
                        if (profileSaveStatus) profileSaveStatus.hidden = true;
                    }, 2500);
                }
            }
        } catch (_) {} finally {
            saveProfileBtn.disabled = false;
        }
    }

    if (profileBtn) {
        profileBtn.addEventListener("click", (e) => {
            e.preventDefault();
            openProfileHub();
        });
    }

    if (closeProfileBtn) {
        closeProfileBtn.addEventListener("click", closeProfileHub);
    }

    if (saveProfileBtn) {
        saveProfileBtn.addEventListener("click", saveProfileData);
    }

    if (profileModal) {
        profileModal.addEventListener("click", (e) => {
            if (e.target === profileModal) {
                closeProfileHub();
            }
        });
    }

    window.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && profileModal && !profileModal.hidden) {
            closeProfileHub();
        }
    });
})();


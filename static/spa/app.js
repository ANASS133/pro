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
        "/google-maps": "search",
        "/autofill": "autofill",
        "/autofill-hub": "autofill",
        "/ai-settings": "ai-settings",
        "/ki-einstellungen": "ai-settings",
        "/whatsapp": "whatsapp",
        "/conductor": "conductor",
        "/autopilot": "conductor",
    };

    const sectionToRoute = {
        search: "/",
        dashboard: "/dashboard",
        supabase: "/supabase",
        money: "/money",
        ausbildungen: "/ausbildungen",
        "create-anschreibens": "/create-anschreibens",
        "send-emails": "/send-emails",
        autofill: "/autofill",
        "ai-settings": "/ai-settings",
        whatsapp: "/whatsapp",
        conductor: "/conductor",
    };

    const titleBySection = {
        search: "JobScout | Search",
        dashboard: "JobScout | Dashboard",
        supabase: "JobScout | Applications",
        money: "JobScout | Revenue & Money",
        ausbildungen: "JobScout | Apprenticeships",
        "create-anschreibens": "JobScout | Cover Letters",
        "send-emails": "JobScout | Send Emails",
        autofill: "JobScout | Autofill Hub",
        "ai-settings": "JobScout | AI Settings",
        whatsapp: "JobScout | WhatsApp AI Center",
        conductor: "JobScout | Conductor Autopilot",
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
        autofill: typeof factories.createAutofillHubSection === "function"
            ? factories.createAutofillHubSection()
            : { show() {}, hide() {} },
        "ai-settings": typeof factories.createAISettingsSection === "function"
            ? factories.createAISettingsSection()
            : { show() {}, hide() {} },
        whatsapp: typeof factories.createWhatsAppSection === "function"
            ? factories.createWhatsAppSection()
            : { show() {}, hide() {} },
        conductor: typeof factories.createConductorSection === "function"
            ? factories.createConductorSection()
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
            if (normalizedSection === "search") controllers.search.show();
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

})();

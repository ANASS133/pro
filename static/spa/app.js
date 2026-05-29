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
})();

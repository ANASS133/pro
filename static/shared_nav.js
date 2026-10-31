(function () {
    if (document.querySelector(".spa-shell")) {
        return; // Handled directly by the SPA Workbench shell
    }

    const NAV_ITEMS = [
        { key: "search", href: "/", label: "E-Mails finden", icon: '<circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>' },
        { key: "ausbildungen", href: "/ausbildungen", label: "Ausbildungen", icon: '<path d="M22 10v6M2 10l10-5 10 5-10 5z"></path><path d="M6 12v5c3 3 9 3 12 0v-5"></path>' },
        { key: "google-maps", href: "/google-maps", label: "Google Maps", icon: '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle>' },
        { key: "anschreiben", href: "/create-anschreibens", label: "Anschreiben", icon: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line>' },
        { key: "send", href: "/send-emails", label: "E-Mails senden", icon: '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline>' },
        { key: "conductor", href: "/conductor", label: "Conductor", icon: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>' },
        { key: "dashboard", href: "/dashboard", label: "Dashboard", icon: '<rect x="3" y="3" width="7" height="9"></rect><rect x="14" y="3" width="7" height="5"></rect><rect x="14" y="12" width="7" height="9"></rect><rect x="3" y="16" width="7" height="5"></rect>' },
        { key: "supabase", href: "/supabase", label: "Supabase", icon: '<ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>' },
        { key: "money", href: "/money", label: "Money", icon: '<line x1="12" y1="1" x2="12" y2="23"></line><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path>' },
        { key: "whatsapp", href: "/whatsapp", label: "WhatsApp AI", icon: '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path>' },
    ];

    function getActiveKey(pathname) {
        const path = String(pathname || "/");
        if (path.startsWith("/ausbildungen")) return "ausbildungen";
        if (path.startsWith("/google-maps")) return "google-maps";
        if (path.startsWith("/money")) return "money";
        if (path.startsWith("/whatsapp")) return "whatsapp";
        if (path.startsWith("/conductor") || path.startsWith("/autopilot")) return "conductor";
        if (path.startsWith("/dashboard")) return "dashboard";
        if (path.startsWith("/supabase") || path.startsWith("/firebase")) return "supabase";
        if (path.startsWith("/send-emails")) return "send";
        if (path.startsWith("/create-anschreibens") || path.startsWith("/pdf")) return "anschreiben";
        return "search";
    }

    function mountSharedSidebar() {
        const activeKey = getActiveKey(window.location.pathname);
        let aside = document.getElementById("shared-sidebar");

        if (!aside) {
            aside = document.createElement("aside");
            aside.id = "shared-sidebar";
            document.body.prepend(aside);
        }

        aside.className = "shared-sidebar";
        aside.setAttribute("aria-label", "Hauptnavigation");

        const linksHtml = NAV_ITEMS.map((item) => {
            const isActive = item.key === activeKey;
            const className = `shared-nav-link${isActive ? " is-active" : ""}`;
            const currentAttr = isActive ? ' aria-current="page"' : "";
            return `
                <a href="${item.href}" class="${className}"${currentAttr} title="${item.label}">
                    <svg class="shared-nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${item.icon}</svg>
                    <span class="shared-nav-text">${item.label}</span>
                </a>
            `;
        }).join("");

        aside.innerHTML = `
            <div class="shared-sidebar-header">
                <div class="shared-brand-badge">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
                </div>
                <div class="shared-brand-meta">
                    <span class="shared-brand-title">JobScout</span>
                </div>
                <button type="button" class="shared-sidebar-toggle" id="shared-sidebar-toggle" title="Umschalten">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg>
                </button>
            </div>
            <nav class="shared-sidebar-nav">
                ${linksHtml}
            </nav>
        `;

        document.body.classList.add("has-shared-sidebar");

        const isCollapsed = localStorage.getItem("sidebar_collapsed") === "true";
        if (isCollapsed) {
            aside.classList.add("is-collapsed");
            document.body.classList.add("sidebar-collapsed");
        }

        const toggleSharedSidebar = () => {
            aside.classList.toggle("is-collapsed");
            const collapsedNow = aside.classList.contains("is-collapsed");
            document.body.classList.toggle("sidebar-collapsed", collapsedNow);
            localStorage.setItem("sidebar_collapsed", collapsedNow ? "true" : "false");
        };

        const toggleBtn = document.getElementById("shared-sidebar-toggle");
        if (toggleBtn) {
            toggleBtn.addEventListener("click", toggleSharedSidebar);
        }

        const brandBadge = aside.querySelector(".shared-brand-badge");
        if (brandBadge) {
            brandBadge.addEventListener("click", (e) => {
                if (aside.classList.contains("is-collapsed")) {
                    e.preventDefault();
                    toggleSharedSidebar();
                }
            });
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", mountSharedSidebar, { once: true });
    } else {
        mountSharedSidebar();
    }
})();

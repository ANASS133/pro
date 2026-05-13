(function () {
    const NAV_ITEMS = [
        { key: "search", href: "/", label: "E-Mails finden" },
        { key: "supabase", href: "/supabase", label: "Supabase" },
        { key: "anschreiben", href: "/create-anschreibens", label: "Anschreiben" },
        { key: "send", href: "/send-emails", label: "E-Mails senden" },
        { key: "dashboard", href: "/dashboard", label: "Dashboard" },
        { key: "add", href: "/add", label: "Add" },
        { key: "ausbildungen", href: "/ausbildungen", label: "Ausbildungen" },
    ];

    function getActiveKey(pathname) {
        const path = String(pathname || "/");

        if (path === "/add" || path.startsWith("/add/")) {
            return "add";
        }
        if (path === "/ausbildungen" || path.startsWith("/ausbildungen")) {
            return "ausbildungen";
        }
        if (path === "/dashboard" || path.startsWith("/dashboard/")) {
            return "dashboard";
        }
        if (path === "/supabase" || path === "/firebase" || path.startsWith("/supabase/") || path.startsWith("/firebase/")) {
            return "supabase";
        }
        if (path === "/send-emails" || path.startsWith("/send-emails")) {
            return "send";
        }
        if (
            path === "/create-anschreibens"
            || path.startsWith("/create-anschreibens")
            || path === "/pdf"
            || path.startsWith("/pdf/")
        ) {
            return "anschreiben";
        }

        return "search";
    }

    function renderNav(activeKey) {
        return NAV_ITEMS.map((item) => {
            const isActive = item.key === activeKey;
            const className = `shared-nav-link${isActive ? " active" : ""}`;
            const currentAttr = isActive ? ' aria-current="page"' : "";
            return `<a href="${item.href}" class="${className}"${currentAttr}>${item.label}</a>`;
        }).join("");
    }

    function mountSharedNavbar() {
        const activeKey = getActiveKey(window.location.pathname);
        let nav = document.querySelector("nav.navbar, nav.top-nav, #shared-navbar");

        if (!nav) {
            nav = document.createElement("nav");
            document.body.prepend(nav);
        }

        nav.classList.add("shared-navbar");
        nav.setAttribute("aria-label", "Hauptnavigation");
        nav.innerHTML = renderNav(activeKey);
        document.body.classList.add("has-shared-navbar");
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", mountSharedNavbar, { once: true });
    } else {
        mountSharedNavbar();
    }
})();

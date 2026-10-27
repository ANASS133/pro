/**
 * Supabase Online-Bewerbungen SPA Section Controller
 * Complete Modern SaaS Redesign with 3 Views (Cards, Compact, Table),
 * Density & Column Controls, Advanced Filtering, Pagination,
 * Clean Document Management, and Application Details Drawer.
 */
(function () {
    const sections = window.SPASections || {};

    sections.createSupabaseSection = function createSupabaseSection() {
        const root = document.getElementById("supabase-section");
        if (!root) {
            return { show() {}, hide() {} };
        }

        // Core DOM Elements
        const statusNode = document.getElementById("supabase-status");
        const emptyState = document.getElementById("supabase-empty");
        const skeletonWrap = document.getElementById("supabase-skeleton");
        const refreshBtn = document.getElementById("supabase-refresh");
        const searchInput = document.getElementById("supabase-search");
        const searchClearBtn = document.getElementById("sp-search-clear");

        // Metrics Elements
        const metricTotal = document.getElementById("sp-metric-total");
        const metricPaid = document.getElementById("sp-metric-paid");
        const metricPaidSum = document.getElementById("sp-metric-paid-sum");
        const metricOpen = document.getElementById("sp-metric-open");
        const metricOpenSum = document.getElementById("sp-metric-open-sum");
        const metricDocs = document.getElementById("sp-metric-docs");

        // View Mode Switcher
        const viewCardsBtn = document.getElementById("sp-view-cards-btn");
        const viewCompactBtn = document.getElementById("sp-view-compact-btn");
        const viewTableBtn = document.getElementById("sp-view-table-btn");
        const cardsView = document.getElementById("supabase-cards");
        const compactView = document.getElementById("sp-compact-view");
        const tableView = document.getElementById("sp-table-view");
        const tableBody = document.getElementById("sp-table-body");
        const tableSelectAll = document.getElementById("sp-table-select-all");

        // Customization Controls
        const sortSelect = document.getElementById("sp-sort-select");
        const columnsSelect = document.getElementById("sp-columns-select");
        const colsControlWrap = document.getElementById("sp-cols-control-wrap");
        const densitySelect = document.getElementById("sp-density-select");
        const colVisibilityBtn = document.getElementById("sp-col-visibility-btn");
        const colVisibilityMenu = document.getElementById("sp-col-visibility-menu");
        const resetPrefsBtn = document.getElementById("sp-reset-prefs-btn");

        // Filter Elements
        const filterToggleBtn = document.getElementById("sp-filter-toggle-btn");
        const filterDrawer = document.getElementById("sp-filter-drawer");
        const activeFilterCountBadge = document.getElementById("sp-active-filter-count");
        const activeFilterChips = document.getElementById("sp-active-filter-chips");
        const filterPack = document.getElementById("supabase-filter-pack");
        const filterLanguage = document.getElementById("supabase-filter-language");
        const filterPayment = document.getElementById("sp-filter-payment");
        const filterField = document.getElementById("sp-filter-field");
        const filterBank = document.getElementById("sp-filter-bank");
        const filterDateFrom = document.getElementById("sp-filter-date-from");
        const filterDateTo = document.getElementById("sp-filter-date-to");
        const filterClearAllBtn = document.getElementById("sp-filter-clear-all");
        const emptyResetBtn = document.getElementById("sp-empty-reset-btn");

        // Export Dropdown
        const exportBtn = document.getElementById("sp-export-btn");
        const exportMenu = document.getElementById("sp-export-menu");

        // Pagination Elements
        const paginationBar = document.getElementById("sp-pagination");
        const pageSizeSelect = document.getElementById("sp-page-size-select");
        const pageInfo = document.getElementById("sp-page-info");
        const pageFirstBtn = document.getElementById("sp-page-first");
        const pagePrevBtn = document.getElementById("sp-page-prev");
        const pageNextBtn = document.getElementById("sp-page-next");
        const pageLastBtn = document.getElementById("sp-page-last");
        const pageNumbers = document.getElementById("sp-page-numbers");

        // Details Drawer Elements
        const drawerBackdrop = document.getElementById("sp-drawer-backdrop");
        const detailsDrawer = document.getElementById("sp-details-drawer");
        const drawerCloseBtn = document.getElementById("sp-drawer-close");
        const dAvatar = document.getElementById("sp-drawer-avatar");
        const dName = document.getElementById("sp-drawer-name");
        const dStatusPill = document.getElementById("sp-drawer-status-pill");
        const dPackTag = document.getElementById("sp-drawer-pack-tag");
        const dFullName = document.getElementById("sp-d-fullname");
        const dId = document.getElementById("sp-d-id");
        const dEmail = document.getElementById("sp-d-email");
        const dWhatsapp = document.getElementById("sp-d-whatsapp");
        const dField = document.getElementById("sp-d-field");
        const dLanguage = document.getElementById("sp-d-language");
        const dPack = document.getElementById("sp-d-pack");
        const dPrice = document.getElementById("sp-d-price");
        const dBank = document.getElementById("sp-d-bank");
        const dPayToggleBtn = document.getElementById("sp-d-pay-toggle-btn");
        const dDocCount = document.getElementById("sp-d-doc-count");
        const dDocsContainer = document.getElementById("sp-d-docs-container");
        const dCreated = document.getElementById("sp-d-created");
        const dNextStepBtn = document.getElementById("sp-d-next-step-btn");
        const dEditBtn = document.getElementById("sp-d-edit-btn");
        const dDeleteBtn = document.getElementById("sp-d-delete-btn");
        const copyEmailBtn = document.getElementById("sp-copy-email");
        const copyWhatsappBtn = document.getElementById("sp-copy-whatsapp");
        const dOnboardContainer = document.getElementById("sp-d-onboard-container");
        const dOnboardBtn = document.getElementById("sp-d-onboard-btn");

        const APPLICATION_STORAGE_PREFIX = "create-anschreibens:application:";
        const LAST_APPLICATION_KEY = "create-anschreibens:last-application";
        const STORAGE_BUCKET = "applications";
        const SIGNED_URL_TTL_SECONDS = 60 * 60;
        const PREFS_STORAGE_KEY = "jobscout_supabase_view_prefs";

        // Application State
        let allApplications = [];
        let hasLoaded = false;
        let isLoading = false;
        const pendingDeletes = new Set();
        const signedDocumentCache = new Map();
        const selectedIds = new Set();
        let activeApplicant = null;
        let onboardingRecords = {};
        const importingIds = new Set();

        // User Preferences with Defaults
        const defaultPreferences = {
            viewMode: "cards",        // 'cards' | 'compact' | 'table'
            density: "comfortable",   // 'compact' | 'comfortable' | 'detailed'
            columns: "auto",          // 'auto' | '2' | '3' | '4' | '5'
            sortBy: "date-desc",      // 'date-desc' | 'date-asc' | 'name-asc' | 'name-desc' | 'paid-first' | 'open-first'
            pageSize: 25,             // 10, 25, 50, 100, 'all'
            currentPage: 1,
            visibleColumns: {
                field: true,
                language: true,
                pack: true,
                bank: true,
                documents: true,
                date: true,
                status: true
            }
        };

        let preferences = loadPreferences();

        function loadPreferences() {
            try {
                const saved = localStorage.getItem(PREFS_STORAGE_KEY);
                if (saved) {
                    const parsed = JSON.parse(saved);
                    return {
                        ...defaultPreferences,
                        ...parsed,
                        visibleColumns: { ...defaultPreferences.visibleColumns, ...(parsed.visibleColumns || {}) }
                    };
                }
            } catch (_) {}
            return { ...defaultPreferences };
        }

        function savePreferences() {
            try {
                localStorage.setItem(PREFS_STORAGE_KEY, JSON.stringify(preferences));
            } catch (_) {}
        }

        function getSupabaseClient() {
            if (!window.AppSupabase || typeof window.AppSupabase.getClient !== "function") {
                throw new Error("Supabase client helper is not available.");
            }
            return window.AppSupabase.getClient();
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

        function formatCreatedAt(value) {
            if (!value) return "k. A.";
            const date = new Date(value);
            if (Number.isNaN(date.getTime())) return "k. A.";
            return new Intl.DateTimeFormat("de-DE", {
                day: "2-digit",
                month: "2-digit",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit"
            }).format(date);
        }

        function getPriceForPack(pack) {
            const normalized = String(pack || "").toLowerCase();
            if (normalized.includes("1000")) return "400 DH";
            if (normalized.includes("500")) return "200 DH";
            return "k. A.";
        }

        function getNumericPrice(pack) {
            const normalized = String(pack || "").toLowerCase();
            if (normalized.includes("1000")) return 400;
            if (normalized.includes("500")) return 200;
            return 0;
        }

        /**
         * Clean Document Filename Mapper:
         * Replaces ugly UUID strings with clean, readable document labels.
         */
        function getHumanDocumentName(path) {
            const clean = String(path || "").split("?")[0].trim();
            const rawFilename = clean.split("/").pop() || clean || "Dokument.pdf";
            const lower = rawFilename.toLowerCase();

            if (lower.includes("cv") || lower.includes("lebenslauf") || lower.includes("resume")) {
                return "Lebenslauf.pdf";
            }
            if (lower.includes("sprache") || lower.includes("zertifikat") || lower.includes("goethe") || lower.includes("telc")) {
                if (lower.includes("b2")) return "Sprachzertifikat (B2).pdf";
                if (lower.includes("b1")) return "Sprachzertifikat (B1).pdf";
                if (lower.includes("c1")) return "Sprachzertifikat (C1).pdf";
                return "Sprachzertifikat.pdf";
            }
            if (lower.includes("motivation") || lower.includes("anschreiben") || lower.includes("cover")) {
                return "Motivationsschreiben.pdf";
            }
            if (lower.includes("zeugnis") || lower.includes("diplom") || lower.includes("abitur") || lower.includes("bachelor") || lower.includes("master")) {
                return "Abschlusszeugnis.pdf";
            }
            if (lower.includes("pass") || lower.includes("ausweis") || lower.includes("id")) {
                return "Ausweisdokument.pdf";
            }

            // Fallback: strip leading UUIDs/hashes (36 chars) or timestamps
            const stripped = rawFilename
                .replace(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}[_-]?/i, "")
                .replace(/^\d{10,14}[_-]?/, "");

            return stripped || "Dokument.pdf";
        }

        function renderOnboardingAction(app, isCompact = false) {
            if (importingIds.has(app.id)) {
                return `
                    <button type="button" class="sp-btn-action-onboard is-loading" disabled>
                        <span class="sp-spin-inline">&#9696;</span> <span>Importiere...</span>
                    </button>
                `;
            }
            if (!app.is_payed) {
                return `<button type="button" class="sp-onboard-pill is-pending" data-action="details" data-app-id="${escapeHtml(app.id)}" title="Zahlung muss vor dem Import verifiziert werden (Klicken für Details)" style="cursor: pointer; background: #f1f5f9; border: 1px dashed #cbd5e1;">Zahlung ausstehend</button>`;
            }

            const rec = onboardingRecords[app.id];
            if (rec && (rec.status === "READY" || rec.status === "PROFILE_REVIEW_REQUIRED" || rec.jobscout_client_id)) {
                const clientId = escapeHtml(rec.jobscout_client_id || "");
                return `
                    <span class="sp-onboard-badge is-imported" title="Bewerber-Profil existiert">&#10003; Bewerber importiert</span>
                    <button type="button" class="sp-btn-link-profile" data-action="open-candidate" data-client-id="${clientId}" title="In Autofill Hub öffnen">Profil öffnen &rarr;</button>
                `;
            }

            const label = (rec && rec.status === "IMPORT_FAILED") ? "Erneut importieren" : "Als Bewerber importieren";
            return `
                <button type="button" class="sp-btn-action-onboard" data-action="onboard" data-app-id="${escapeHtml(app.id)}" title="Automatisches Onboarding in JobScout starten">
                    <span>${label}</span>
                </button>
            `;
        }

        function normalizeDocumentPaths(value) {
            if (!Array.isArray(value)) return [];
            return value.map(entry => {
                if (typeof entry === "string") return entry.trim();
                if (entry && typeof entry === "object") return String(entry.path || entry.storagePath || entry.name || "").trim();
                return "";
            }).filter(Boolean);
        }

        function normalizeApplication(row) {
            const documents = normalizeDocumentPaths(row.documents);
            const createdAt = row.created_at || "";
            const fullName = String(row.full_name || "").trim() || "Unbenannter Bewerber";
            const field = String(row.field || "").trim() || "k. A.";
            const pack = String(row.pack || "").trim() || "k. A.";
            const languageLevel = String(row.language_level || "").trim() || "k. A.";

            return {
                id: String(row.id || "").trim(),
                source_label: "Supabase",
                full_name: fullName,
                fullName: fullName,
                email: String(row.email || "").trim() || "k. A.",
                whatsapp: String(row.whatsapp || "").trim() || "k. A.",
                bank: String(row.bank || "").trim() || "k. A.",
                language_level: languageLevel,
                languageLevel: languageLevel !== "k. A." ? languageLevel : "",
                field: field,
                bereich: field !== "k. A." ? field : "",
                pack: pack,
                bewerbungen: pack !== "k. A." ? pack : "",
                price: getPriceForPack(pack),
                numeric_price: getNumericPrice(pack),
                documents: documents,
                document_count: documents.length,
                created_at: createdAt,
                created_at_display: formatCreatedAt(createdAt),
                sort_time: createdAt ? new Date(createdAt).getTime() || 0 : 0,
                is_payed: Boolean(row.is_payed),
                raw: row,
            };
        }

        function setStatus(message, isError) {
            if (!statusNode) return;
            const value = String(message || "").trim();
            statusNode.hidden = !value;
            statusNode.textContent = value;
            statusNode.classList.toggle("is-error", Boolean(isError));
            if (!isError && value) {
                setTimeout(() => {
                    if (statusNode.textContent === value) statusNode.hidden = true;
                }, 3500);
            }
        }

        function setLoading(loading) {
            isLoading = Boolean(loading);
            if (skeletonWrap) skeletonWrap.hidden = !isLoading;
            if (emptyState) emptyState.hidden = true;
            if (refreshBtn) {
                refreshBtn.disabled = isLoading;
                refreshBtn.innerHTML = isLoading
                    ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="sp-spin"><path d="M23 4v6h-6"></path><path d="M1 20v-6h6"></path><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg> <span>Lade...</span>'
                    : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"></path><path d="M1 20v-6h6"></path><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg> <span>Aktualisieren</span>';
            }
        }

        // --- Lazy Signed Document Generator ---
        async function getSignedDocument(path) {
            const normalized = String(path || "").trim();
            if (!normalized) return null;

            if (signedDocumentCache.has(normalized)) {
                return signedDocumentCache.get(normalized);
            }

            const client = await getSupabaseClient();
            const response = await client.storage
                .from(STORAGE_BUCKET)
                .createSignedUrl(normalized, SIGNED_URL_TTL_SECONDS);

            if (response.error) throw response.error;

            const signedDoc = {
                path: normalized,
                name: getHumanDocumentName(normalized),
                rawName: normalized.split("/").pop() || normalized,
                url: response.data.signedUrl,
                downloadURL: response.data.signedUrl
            };

            signedDocumentCache.set(normalized, signedDoc);
            return signedDoc;
        }

        // --- Filter & Sort Logic ---
        function getFilteredAndSortedApplications() {
            const searchTerm = String(searchInput?.value || "").toLowerCase().trim();
            const packVal = String(filterPack?.value || "").trim();
            const langVal = String(filterLanguage?.value || "").trim();
            const payVal = String(filterPayment?.value || "").trim();
            const fieldVal = String(filterField?.value || "").trim();
            const bankVal = String(filterBank?.value || "").trim();
            const dateFrom = filterDateFrom?.value ? new Date(filterDateFrom.value).getTime() : 0;
            const dateTo = filterDateTo?.value ? new Date(filterDateTo.value + "T23:59:59").getTime() : 0;

            const filtered = allApplications.filter(app => {
                if (searchTerm) {
                    const matches = [
                        app.full_name,
                        app.email,
                        app.whatsapp,
                        app.field,
                        app.bank
                    ].some(val => String(val || "").toLowerCase().includes(searchTerm));
                    if (!matches) return false;
                }

                if (packVal && app.pack !== packVal) return false;
                if (langVal && app.language_level !== langVal) return false;
                if (payVal === "paid" && !app.is_payed) return false;
                if (payVal === "unpaid" && app.is_payed) return false;
                if (fieldVal && app.field !== fieldVal) return false;
                if (bankVal && app.bank !== bankVal) return false;
                if (dateFrom && app.sort_time < dateFrom) return false;
                if (dateTo && app.sort_time > dateTo) return false;

                return true;
            });

            // Sorting
            filtered.sort((a, b) => {
                switch (preferences.sortBy) {
                    case "date-asc":
                        return a.sort_time - b.sort_time;
                    case "name-asc":
                        return a.full_name.localeCompare(b.full_name, "de");
                    case "name-desc":
                        return b.full_name.localeCompare(a.full_name, "de");
                    case "paid-first":
                        return (b.is_payed ? 1 : 0) - (a.is_payed ? 1 : 0);
                    case "open-first":
                        return (a.is_payed ? 1 : 0) - (b.is_payed ? 1 : 0);
                    case "date-desc":
                    default:
                        return b.sort_time - a.sort_time;
                }
            });

            return filtered;
        }

        // --- Summary Metrics Updates ---
        function updateSummaryMetrics(items) {
            const list = items || allApplications;
            const total = list.length;
            let paidCount = 0;
            let paidSum = 0;
            let openCount = 0;
            let openSum = 0;
            let docsCount = 0;

            list.forEach(app => {
                const price = app.numeric_price;
                if (app.is_payed) {
                    paidCount++;
                    paidSum += price;
                } else {
                    openCount++;
                    openSum += price;
                }
                docsCount += app.document_count;
            });

            if (metricTotal) metricTotal.textContent = total;
            if (metricPaid) metricPaid.textContent = paidCount;
            if (metricPaidSum) metricPaidSum.textContent = paidSum.toLocaleString("de-DE") + " DH";
            if (metricOpen) metricOpen.textContent = openCount;
            if (metricOpenSum) metricOpenSum.textContent = openSum.toLocaleString("de-DE") + " DH";
            if (metricDocs) metricDocs.textContent = docsCount;
        }

        // --- Dynamic Filter Options ---
        function updateFilterDropdownOptions() {
            if (filterPack) {
                const current = filterPack.value;
                const packs = Array.from(new Set(allApplications.map(a => a.pack).filter(p => p && p !== "k. A."))).sort();
                filterPack.innerHTML = '<option value="">Alle Pakete</option>' + packs.map(p => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join("");
                if (packs.includes(current)) filterPack.value = current;
            }

            if (filterField) {
                const current = filterField.value;
                const fields = Array.from(new Set(allApplications.map(a => a.field).filter(f => f && f !== "k. A."))).sort();
                filterField.innerHTML = '<option value="">Alle Bereiche</option>' + fields.map(f => `<option value="${escapeHtml(f)}">${escapeHtml(f)}</option>`).join("");
                if (fields.includes(current)) filterField.value = current;
            }

            if (filterBank) {
                const current = filterBank.value;
                const banks = Array.from(new Set(allApplications.map(a => a.bank).filter(b => b && b !== "k. A."))).sort();
                filterBank.innerHTML = '<option value="">Alle Banken</option>' + banks.map(b => `<option value="${escapeHtml(b)}">${escapeHtml(b)}</option>`).join("");
                if (banks.includes(current)) filterBank.value = current;
            }
        }

        // --- Active Filter Chips Bar ---
        function updateActiveFilterChips() {
            if (!activeFilterChips) return;
            const chips = [];

            if (searchInput?.value.trim()) chips.push({ label: `Suche: "${searchInput.value.trim()}"`, clear: () => { searchInput.value = ""; searchClearBtn.hidden = true; } });
            if (filterPack?.value) chips.push({ label: `Paket: ${filterPack.value}`, clear: () => { filterPack.value = ""; } });
            if (filterLanguage?.value) chips.push({ label: `Sprache: ${filterLanguage.value}`, clear: () => { filterLanguage.value = ""; } });
            if (filterPayment?.value) chips.push({ label: `Status: ${filterPayment.value === "paid" ? "Bezahlt" : "Offen"}`, clear: () => { filterPayment.value = ""; } });
            if (filterField?.value) chips.push({ label: `Bereich: ${filterField.value}`, clear: () => { filterField.value = ""; } });
            if (filterBank?.value) chips.push({ label: `Bank: ${filterBank.value}`, clear: () => { filterBank.value = ""; } });
            if (filterDateFrom?.value) chips.push({ label: `Ab: ${filterDateFrom.value}`, clear: () => { filterDateFrom.value = ""; } });
            if (filterDateTo?.value) chips.push({ label: `Bis: ${filterDateTo.value}`, clear: () => { filterDateTo.value = ""; } });

            if (activeFilterCountBadge) {
                activeFilterCountBadge.hidden = chips.length === 0;
                activeFilterCountBadge.textContent = chips.length;
            }

            if (!chips.length) {
                activeFilterChips.hidden = true;
                activeFilterChips.innerHTML = "";
                return;
            }

            activeFilterChips.hidden = false;
            activeFilterChips.innerHTML = chips.map((c, i) => `
                <span class="sp-chip">
                    <span>${escapeHtml(c.label)}</span>
                    <button type="button" class="sp-chip-remove" data-chip-idx="${i}" title="Filter entfernen">&times;</button>
                </span>
            `).join("") + '<button type="button" id="sp-chip-clear-all" class="sp-btn-link-sm">Clear all filters</button>';

            activeFilterChips.querySelectorAll("[data-chip-idx]").forEach(btn => {
                btn.addEventListener("click", () => {
                    const idx = Number(btn.dataset.chipIdx);
                    if (chips[idx]) chips[idx].clear();
                    preferences.currentPage = 1;
                    renderView();
                });
            });

            document.getElementById("sp-chip-clear-all")?.addEventListener("click", clearAllFilters);
        }

        function clearAllFilters() {
            if (searchInput) searchInput.value = "";
            if (searchClearBtn) searchClearBtn.hidden = true;
            if (filterPack) filterPack.value = "";
            if (filterLanguage) filterLanguage.value = "";
            if (filterPayment) filterPayment.value = "";
            if (filterField) filterField.value = "";
            if (filterBank) filterBank.value = "";
            if (filterDateFrom) filterDateFrom.value = "";
            if (filterDateTo) filterDateTo.value = "";
            preferences.currentPage = 1;
            renderView();
        }

        // --- Render Main Views (Cards, Compact, Table) ---
        function renderView() {
            const filtered = getFilteredAndSortedApplications();
            updateSummaryMetrics(filtered);
            updateActiveFilterChips();

            if (!filtered.length) {
                if (cardsView) cardsView.innerHTML = "";
                if (compactView) compactView.innerHTML = "";
                if (tableBody) tableBody.innerHTML = "";
                if (emptyState) emptyState.hidden = false;
                if (paginationBar) paginationBar.hidden = true;
                return;
            }

            if (emptyState) emptyState.hidden = true;

            // Pagination calculation
            const totalItems = filtered.length;
            const pageSize = preferences.pageSize === "all" ? totalItems : Number(preferences.pageSize) || 25;
            const totalPages = Math.ceil(totalItems / pageSize) || 1;
            if (preferences.currentPage > totalPages) preferences.currentPage = totalPages;
            if (preferences.currentPage < 1) preferences.currentPage = 1;

            const startIdx = (preferences.currentPage - 1) * pageSize;
            const endIdx = preferences.pageSize === "all" ? totalItems : Math.min(startIdx + pageSize, totalItems);
            const pageItems = filtered.slice(startIdx, endIdx);

            renderPagination(totalItems, startIdx, endIdx, totalPages);

            // Apply view mode visibility
            if (cardsView) {
                cardsView.hidden = preferences.viewMode !== "cards";
                cardsView.dataset.cols = preferences.columns;
                cardsView.dataset.density = preferences.density;
            }
            if (compactView) {
                compactView.hidden = preferences.viewMode !== "compact";
                compactView.dataset.density = preferences.density;
            }
            if (tableView) {
                tableView.hidden = preferences.viewMode !== "table";
            }
            if (colsControlWrap) {
                colsControlWrap.hidden = preferences.viewMode !== "cards";
            }

            // Sync View Switcher Buttons
            if (viewCardsBtn) viewCardsBtn.classList.toggle("is-active", preferences.viewMode === "cards");
            if (viewCompactBtn) viewCompactBtn.classList.toggle("is-active", preferences.viewMode === "compact");
            if (viewTableBtn) viewTableBtn.classList.toggle("is-active", preferences.viewMode === "table");

            if (preferences.viewMode === "cards") {
                renderCards(pageItems);
            } else if (preferences.viewMode === "compact") {
                renderCompact(pageItems);
            } else {
                renderTable(pageItems);
            }
        }

        // 1. CARDS RENDERER
        function renderCards(items) {
            if (!cardsView) return;
            const vis = preferences.visibleColumns;

            cardsView.innerHTML = items.map(app => {
                const initials = getInitials(app.full_name);
                const statusBadge = app.is_payed
                    ? '<span class="sp-status-pill is-paid">&#10003; Bezahlt</span>'
                    : '<span class="sp-status-pill is-open">Offen</span>';

                return `
                    <article class="sp-card" data-app-id="${escapeHtml(app.id)}">
                        <div class="sp-card-head">
                            <div class="sp-card-user-info">
                                <div class="sp-avatar">${escapeHtml(initials)}</div>
                                <div class="sp-card-names">
                                    <h3 class="sp-card-name" title="${escapeHtml(app.full_name)}">${escapeHtml(app.full_name)}</h3>
                                    ${vis.field ? `<span class="sp-card-field">${escapeHtml(app.field)}</span>` : ""}
                                </div>
                            </div>
                            ${vis.status ? statusBadge : ""}
                        </div>

                        <div class="sp-card-badges-row">
                            ${vis.language ? `<span class="sp-tag-pill sp-pill-lang">${escapeHtml(app.language_level)}</span>` : ""}
                            ${vis.pack ? `<span class="sp-tag-pill">${escapeHtml(app.pack)}</span>` : ""}
                            ${vis.documents ? `<span class="sp-tag-pill sp-pill-doc">${app.document_count} Dok.</span>` : ""}
                        </div>

                        <div class="sp-card-meta">
                            ${vis.pack ? `
                                <div class="sp-meta-item">
                                    <span class="sp-meta-key">Preis:</span>
                                    <strong class="sp-meta-val sp-price-val">${escapeHtml(app.price)}</strong>
                                </div>
                            ` : ""}
                            ${vis.bank && app.bank !== "k. A." ? `
                                <div class="sp-meta-item">
                                    <span class="sp-meta-key">Bank:</span>
                                    <strong class="sp-meta-val">${escapeHtml(app.bank)}</strong>
                                </div>
                            ` : ""}
                            ${vis.date ? `
                                <div class="sp-meta-item">
                                    <span class="sp-meta-key">Eingereicht:</span>
                                    <span class="sp-meta-val">${escapeHtml(app.created_at_display)}</span>
                                </div>
                            ` : ""}
                        </div>

                        <div class="sp-card-actions">
                            <button type="button" class="sp-btn-action-ghost" data-action="details" data-app-id="${escapeHtml(app.id)}">Details</button>
                            <button type="button" class="sp-btn-action-primary" data-action="next-step" data-app-id="${escapeHtml(app.id)}">Next step</button>
                            ${renderOnboardingAction(app)}
                            ${!app.is_payed ? `
                                <button type="button" class="sp-btn-action-ghost" data-action="pay" data-app-id="${escapeHtml(app.id)}" title="Als bezahlt markieren">✓ Bezahlt</button>
                            ` : ""}
                        </div>
                    </article>
                `;
            }).join("");

            // Click card opens drawer (unless clicked on action buttons)
            cardsView.querySelectorAll(".sp-card").forEach(card => {
                card.addEventListener("click", (e) => {
                    if (e.target.closest("[data-action]") || e.target.closest(".sp-card-actions")) return;
                    const id = card.dataset.appId;
                    openDetailsDrawer(id);
                });
            });
        }

        // 2. COMPACT LIST RENDERER
        function renderCompact(items) {
            if (!compactView) return;
            const vis = preferences.visibleColumns;

            compactView.innerHTML = items.map(app => {
                const initials = getInitials(app.full_name);
                const statusBadge = app.is_payed
                    ? '<span class="sp-status-pill is-paid">&#10003; Bezahlt</span>'
                    : '<span class="sp-status-pill is-open">Offen</span>';

                return `
                    <div class="sp-compact-row" data-app-id="${escapeHtml(app.id)}">
                        <div class="sp-compact-left">
                            <div class="sp-avatar sp-avatar-sm">${escapeHtml(initials)}</div>
                            <div class="sp-compact-user-meta">
                                <strong class="sp-compact-name">${escapeHtml(app.full_name)}</strong>
                                <span class="sp-compact-sub">${escapeHtml(app.email !== "k. A." ? app.email : app.whatsapp)}</span>
                            </div>
                        </div>

                        <div class="sp-compact-mid">
                            ${vis.field ? `<span class="sp-tag-pill">${escapeHtml(app.field)}</span>` : ""}
                            ${vis.language ? `<span class="sp-tag-pill sp-pill-lang">${escapeHtml(app.language_level)}</span>` : ""}
                            ${vis.pack ? `<strong class="sp-price-val">${escapeHtml(app.price)}</strong>` : ""}
                            ${vis.documents ? `<span class="sp-tag-pill sp-pill-doc">${app.document_count} Dok.</span>` : ""}
                            ${vis.date ? `<span class="sp-compact-sub">${escapeHtml(app.created_at_display)}</span>` : ""}
                        </div>

                        <div class="sp-compact-right">
                            ${vis.status ? statusBadge : ""}
                            ${renderOnboardingAction(app, true)}
                            ${!app.is_payed ? `
                                <button type="button" class="sp-btn-action-ghost" data-action="pay" data-app-id="${escapeHtml(app.id)}" title="Als bezahlt markieren">✓ Bezahlt</button>
                            ` : ""}
                            <button type="button" class="sp-btn-action-ghost" data-action="details" data-app-id="${escapeHtml(app.id)}">Details</button>
                            <button type="button" class="sp-btn-action-primary" data-action="next-step" data-app-id="${escapeHtml(app.id)}">Next step</button>
                        </div>
                    </div>
                `;
            }).join("");

            compactView.querySelectorAll(".sp-compact-row").forEach(row => {
                row.addEventListener("click", (e) => {
                    if (e.target.closest("[data-action]") || e.target.closest(".sp-compact-right")) return;
                    const id = row.dataset.appId;
                    openDetailsDrawer(id);
                });
            });
        }

        // 3. TABLE RENDERER
        function renderTable(items) {
            if (!tableBody) return;
            const vis = preferences.visibleColumns;

            // Update th visibility
            if (tableView) {
                tableView.querySelectorAll("th[data-col], td[data-col]").forEach(cell => {
                    const col = cell.dataset.col;
                    if (col in vis) cell.hidden = !vis[col];
                });
            }

            tableBody.innerHTML = items.map(app => {
                const isSelected = selectedIds.has(app.id);
                const statusBadge = app.is_payed
                    ? '<span class="sp-status-pill is-paid">&#10003; Bezahlt</span>'
                    : '<span class="sp-status-pill is-open">Offen</span>';

                return `
                    <tr class="${isSelected ? "is-selected" : ""}" data-app-id="${escapeHtml(app.id)}">
                        <td class="td-checkbox">
                            <input type="checkbox" class="sp-row-checkbox" data-app-id="${escapeHtml(app.id)}" ${isSelected ? "checked" : ""}>
                        </td>
                        <td>
                            <div class="sp-card-user-info">
                                <div class="sp-avatar sp-avatar-sm">${escapeHtml(getInitials(app.full_name))}</div>
                                <strong class="sp-compact-name">${escapeHtml(app.full_name)}</strong>
                            </div>
                        </td>
                        <td data-col="email">${escapeHtml(app.email)}</td>
                        <td data-col="whatsapp">${escapeHtml(app.whatsapp)}</td>
                        <td data-col="field"><span class="sp-tag-pill">${escapeHtml(app.field)}</span></td>
                        <td data-col="language"><span class="sp-tag-pill sp-pill-lang">${escapeHtml(app.language_level)}</span></td>
                        <td data-col="pack">
                            <strong>${escapeHtml(app.pack)}</strong>
                            <small class="sp-price-val" style="display:block;">${escapeHtml(app.price)}</small>
                        </td>
                        <td data-col="bank">${escapeHtml(app.bank)}</td>
                        <td data-col="status">${statusBadge}</td>
                        <td data-col="documents"><span class="sp-tag-pill sp-pill-doc">${app.document_count} Dok.</span></td>
                        <td data-col="date"><small>${escapeHtml(app.created_at_display)}</small></td>
                        <td class="td-actions">
                            <div style="display: flex; gap: 6px; justify-content: flex-end; align-items: center;">
                                ${renderOnboardingAction(app, true)}
                                ${!app.is_payed ? `
                                    <button type="button" class="sp-btn-action-ghost" data-action="pay" data-app-id="${escapeHtml(app.id)}" title="Als bezahlt markieren">✓ Bezahlt</button>
                                ` : ""}
                                <button type="button" class="sp-btn-action-ghost" data-action="details" data-app-id="${escapeHtml(app.id)}">Details</button>
                                <button type="button" class="sp-btn-action-primary" data-action="next-step" data-app-id="${escapeHtml(app.id)}">Next</button>
                            </div>
                        </td>
                    </tr>
                `;
            }).join("");

            // Re-apply column visibility to td elements
            tableView.querySelectorAll("td[data-col]").forEach(td => {
                const col = td.dataset.col;
                if (col in vis) td.hidden = !vis[col];
            });

            // Row click opens drawer (unless clicked on action buttons or checkboxes)
            tableBody.querySelectorAll("tr").forEach(tr => {
                tr.addEventListener("click", (e) => {
                    if (e.target.closest("[data-action]") || e.target.closest(".td-actions") || e.target.closest(".td-checkbox") || e.target.closest("input")) return;
                    const id = tr.dataset.appId;
                    openDetailsDrawer(id);
                });
            });

            // Checkbox handling
            tableBody.querySelectorAll(".sp-row-checkbox").forEach(cb => {
                cb.addEventListener("change", () => {
                    const id = cb.dataset.appId;
                    if (cb.checked) selectedIds.add(id);
                    else selectedIds.delete(id);
                    cb.closest("tr").classList.toggle("is-selected", cb.checked);
                    syncSelectAllState(items);
                });
            });

            syncSelectAllState(items);
        }

        function syncSelectAllState(pageItems) {
            if (!tableSelectAll) return;
            const allChecked = pageItems.length > 0 && pageItems.every(app => selectedIds.has(app.id));
            tableSelectAll.checked = allChecked;
        }

        tableSelectAll?.addEventListener("change", () => {
            const filtered = getFilteredAndSortedApplications();
            const pageSize = preferences.pageSize === "all" ? filtered.length : Number(preferences.pageSize) || 25;
            const startIdx = (preferences.currentPage - 1) * pageSize;
            const pageItems = filtered.slice(startIdx, startIdx + pageSize);

            pageItems.forEach(app => {
                if (tableSelectAll.checked) selectedIds.add(app.id);
                else selectedIds.delete(app.id);
            });
            renderView();
        });

        // --- Pagination Navigation ---
        function renderPagination(totalItems, startIdx, endIdx, totalPages) {
            if (!paginationBar) return;
            paginationBar.hidden = false;

            if (pageInfo) pageInfo.textContent = `Zeige ${totalItems > 0 ? startIdx + 1 : 0}–${endIdx} von ${totalItems}`;

            if (pageFirstBtn) pageFirstBtn.disabled = preferences.currentPage <= 1;
            if (pagePrevBtn) pagePrevBtn.disabled = preferences.currentPage <= 1;
            if (pageNextBtn) pageNextBtn.disabled = preferences.currentPage >= totalPages;
            if (pageLastBtn) pageLastBtn.disabled = preferences.currentPage >= totalPages;

            if (pageNumbers) {
                let html = "";
                const maxButtons = 5;
                let startPage = Math.max(1, preferences.currentPage - 2);
                let endPage = Math.min(totalPages, startPage + maxButtons - 1);
                if (endPage - startPage < maxButtons - 1) {
                    startPage = Math.max(1, endPage - maxButtons + 1);
                }

                for (let p = startPage; p <= endPage; p++) {
                    html += `<button type="button" class="sp-page-btn ${p === preferences.currentPage ? "is-active" : ""}" data-page="${p}">${p}</button>`;
                }
                pageNumbers.innerHTML = html;

                pageNumbers.querySelectorAll("[data-page]").forEach(btn => {
                    btn.addEventListener("click", () => {
                        preferences.currentPage = Number(btn.dataset.page);
                        renderView();
                    });
                });
            }
        }

        pageFirstBtn?.addEventListener("click", () => { preferences.currentPage = 1; renderView(); });
        pagePrevBtn?.addEventListener("click", () => { if (preferences.currentPage > 1) { preferences.currentPage--; renderView(); } });
        pageNextBtn?.addEventListener("click", () => { preferences.currentPage++; renderView(); });
        pageLastBtn?.addEventListener("click", () => {
            const filtered = getFilteredAndSortedApplications();
            const pageSize = preferences.pageSize === "all" ? filtered.length : Number(preferences.pageSize) || 25;
            preferences.currentPage = Math.ceil(filtered.length / pageSize) || 1;
            renderView();
        });

        pageSizeSelect?.addEventListener("change", () => {
            preferences.pageSize = pageSizeSelect.value;
            preferences.currentPage = 1;
            savePreferences();
            renderView();
        });

        // --- Details Drawer Logic ---
        async function openDetailsDrawer(applicationId) {
            const app = allApplications.find(a => a.id === applicationId);
            if (!app) return;
            activeApplicant = app;

            if (dAvatar) dAvatar.textContent = getInitials(app.full_name);
            if (dName) dName.textContent = app.full_name;
            if (dStatusPill) {
                dStatusPill.className = `sp-status-pill ${app.is_payed ? "is-paid" : "is-open"}`;
                dStatusPill.innerHTML = app.is_payed ? "&#10003; Bezahlt" : "Offen";
            }
            if (dPackTag) dPackTag.textContent = app.pack;

            if (dFullName) dFullName.textContent = app.full_name;
            if (dId) dId.textContent = app.id;

            if (dEmail) {
                dEmail.textContent = app.email;
                dEmail.href = app.email !== "k. A." ? `mailto:${app.email}` : "#";
            }
            if (dWhatsapp) {
                dWhatsapp.textContent = app.whatsapp;
                const cleanPhone = app.whatsapp.replace(/[^0-9]/g, "");
                dWhatsapp.href = cleanPhone ? `https://wa.me/${cleanPhone}` : "#";
            }

            if (dField) dField.textContent = app.field;
            if (dLanguage) dLanguage.textContent = app.language_level;
            if (dPack) dPack.textContent = app.pack;
            if (dPrice) dPrice.textContent = app.price;
            if (dBank) dBank.textContent = app.bank;

            if (dPayToggleBtn) {
                dPayToggleBtn.className = `sp-btn-pay-status ${app.is_payed ? "is-paid" : ""}`;
                dPayToggleBtn.textContent = app.is_payed ? "✓ Als bezahlt markiert" : "Als bezahlt markieren";
                dPayToggleBtn.disabled = app.is_payed;
            }

            if (dCreated) dCreated.textContent = app.created_at_display;
            if (dDocCount) dDocCount.textContent = `${app.document_count} Dokument${app.document_count === 1 ? "" : "e"}`;

            // Lazy generate signed URLs for documents in drawer
            renderDrawerDocuments(app.documents);

            // Render Onboarding Dossier Section in Drawer
            renderDrawerOnboarding(app);

            if (drawerBackdrop) drawerBackdrop.hidden = false;
            if (detailsDrawer) detailsDrawer.hidden = false;
        }

        async function renderDrawerDocuments(paths) {
            if (!dDocsContainer) return;
            if (!paths.length) {
                dDocsContainer.innerHTML = '<div class="sp-doc-empty">No documents uploaded for this application.</div>';
                return;
            }

            dDocsContainer.innerHTML = '<div class="sp-doc-empty">Lade Dokumenten-Links...</div>';

            try {
                const signedDocs = await Promise.all(paths.map(async path => {
                    try {
                        return await getSignedDocument(path);
                    } catch (e) {
                        return { path, name: getHumanDocumentName(path), error: true };
                    }
                }));

                dDocsContainer.innerHTML = signedDocs.map(doc => {
                    if (doc.error || !doc.url) {
                        return `
                            <div class="sp-doc-item">
                                <div class="sp-doc-info">
                                    <span class="sp-doc-badge">DOC</span>
                                    <span class="sp-doc-name">${escapeHtml(doc.name)} (unavailable)</span>
                                </div>
                            </div>
                        `;
                    }

                    const ext = doc.name.split(".").pop().toUpperCase();
                    return `
                        <div class="sp-doc-item">
                            <div class="sp-doc-info">
                                <span class="sp-doc-badge ${ext.toLowerCase()}">${escapeHtml(ext)}</span>
                                <div class="sp-doc-meta">
                                    <strong class="sp-doc-name">${escapeHtml(doc.name)}</strong>
                                    <span class="sp-doc-sub">${escapeHtml(doc.rawName)}</span>
                                </div>
                            </div>
                            <div class="sp-doc-actions">
                                <a href="${escapeHtml(doc.url)}" target="_blank" rel="noopener noreferrer" class="sp-doc-btn" title="Im Browser öffnen">Vorschau</a>
                                <a href="${escapeHtml(doc.url)}" download="${escapeHtml(doc.name)}" class="sp-doc-btn" title="Herunterladen">Download</a>
                                <button type="button" class="sp-doc-btn" data-copy-link="${escapeHtml(doc.url)}" title="Link kopieren">Kopieren</button>
                            </div>
                        </div>
                    `;
                }).join("");

                dDocsContainer.querySelectorAll("[data-copy-link]").forEach(btn => {
                    btn.addEventListener("click", () => {
                        const url = btn.dataset.copyLink;
                        navigator.clipboard?.writeText(url).then(() => {
                            btn.textContent = "Kopiert!";
                            setTimeout(() => { btn.textContent = "Kopieren"; }, 2000);
                        });
                    });
                });
            } catch (err) {
                dDocsContainer.innerHTML = '<div class="sp-doc-empty">Fehler beim Laden der Dokumente.</div>';
            }
        }

        function closeDetailsDrawer() {
            if (drawerBackdrop) drawerBackdrop.hidden = true;
            if (detailsDrawer) detailsDrawer.hidden = true;
            activeApplicant = null;
        }

        drawerCloseBtn?.addEventListener("click", closeDetailsDrawer);
        drawerBackdrop?.addEventListener("click", closeDetailsDrawer);
        document.addEventListener("keydown", e => {
            if (e.key === "Escape" && detailsDrawer && !detailsDrawer.hidden) {
                closeDetailsDrawer();
            }
        });

        // Copy buttons in drawer
        copyEmailBtn?.addEventListener("click", () => {
            if (activeApplicant?.email) {
                navigator.clipboard?.writeText(activeApplicant.email);
                setStatus("E-Mail in Zwischenablage kopiert!");
            }
        });
        copyWhatsappBtn?.addEventListener("click", () => {
            if (activeApplicant?.whatsapp) {
                navigator.clipboard?.writeText(activeApplicant.whatsapp);
                setStatus("WhatsApp-Nummer kopiert!");
            }
        });

        // Pay Toggle in drawer
        dPayToggleBtn?.addEventListener("click", async () => {
            if (!activeApplicant || activeApplicant.is_payed) return;
            dPayToggleBtn.disabled = true;
            dPayToggleBtn.textContent = "Saving...";
            try {
                await markAsPayed(activeApplicant.id);
                openDetailsDrawer(activeApplicant.id);
            } catch (err) {
                dPayToggleBtn.disabled = false;
                dPayToggleBtn.textContent = "Als bezahlt markieren";
            }
        });

        // Drawer Action Buttons
        dNextStepBtn?.addEventListener("click", () => {
            if (activeApplicant) nextStep(activeApplicant.id);
        });
        dEditBtn?.addEventListener("click", () => {
            if (activeApplicant) editApplication(activeApplicant.id);
        });
        dDeleteBtn?.addEventListener("click", () => {
            if (activeApplicant) deleteApplication(activeApplicant.id);
        });
        dOnboardBtn?.addEventListener("click", () => {
            const action = dOnboardBtn.dataset.action;
            if (action === "onboard" && activeApplicant) {
                handleOnboardCandidate(activeApplicant.id);
            } else if (action === "open-candidate") {
                handleOpenCandidate(dOnboardBtn.dataset.clientId);
            }
        });

        function renderDrawerOnboarding(app) {
            if (!dOnboardContainer) return;
            const rec = onboardingRecords[app.id];
            const isImporting = importingIds.has(app.id);

            let statusLabel = "Noch nicht importiert";
            let statusPillClass = "sp-onboard-pill is-pending";

            if (isImporting) {
                statusLabel = "Import läuft...";
                statusPillClass = "sp-btn-action-onboard is-loading";
            } else if (!app.is_payed) {
                statusLabel = "Zahlung ausstehend";
                statusPillClass = "sp-onboard-pill is-pending";
            } else if (rec) {
                switch (rec.status) {
                    case "READY":
                        statusLabel = "Bereit (Profil angelegt)";
                        statusPillClass = "sp-onboard-badge is-imported";
                        break;
                    case "PROFILE_REVIEW_REQUIRED":
                        statusLabel = "Überprüfung empfohlen";
                        statusPillClass = "sp-onboard-badge is-imported";
                        break;
                    case "IMPORT_FAILED":
                        statusLabel = "Import fehlgeschlagen";
                        statusPillClass = "sp-onboard-pill is-pending";
                        break;
                    case "IMPORTING":
                        statusLabel = "Import läuft...";
                        statusPillClass = "sp-btn-action-onboard is-loading";
                        break;
                    default:
                        statusLabel = rec.status || "Bereit für Import";
                        statusPillClass = "sp-onboard-badge";
                }
            }

            const clientId = rec?.jobscout_client_id || "—";
            const docCount = rec ? `${rec.document_count ?? 0} Dokument(e)` : "—";
            const cvStatus = rec ? (rec.cv_parsed ? "Erfolgreich extrahiert" : "Keine CV-Extraktion") : "—";
            const missing = (rec?.missing_fields && rec.missing_fields.length) ? rec.missing_fields.join(", ") : "Keine";
            const importedAt = rec?.imported_at ? formatCreatedAt(rec.imported_at) : "—";

            dOnboardContainer.innerHTML = `
                <div class="sp-onboard-card-header">
                    <span class="sp-onboard-card-title">Dossier-Status</span>
                    <span class="${statusPillClass}">${escapeHtml(statusLabel)}</span>
                </div>
                <div class="sp-onboard-kv-grid">
                    <div class="sp-onboard-kv-item">
                        <span class="sp-onboard-kv-label">Client ID</span>
                        <code class="sp-onboard-kv-value">${escapeHtml(clientId)}</code>
                    </div>
                    <div class="sp-onboard-kv-item">
                        <span class="sp-onboard-kv-label">Importiert am</span>
                        <span class="sp-onboard-kv-value">${escapeHtml(importedAt)}</span>
                    </div>
                    <div class="sp-onboard-kv-item">
                        <span class="sp-onboard-kv-label">Dokumente</span>
                        <span class="sp-onboard-kv-value">${escapeHtml(docCount)}</span>
                    </div>
                    <div class="sp-onboard-kv-item">
                        <span class="sp-onboard-kv-label">CV Analyse</span>
                        <span class="sp-onboard-kv-value">${escapeHtml(cvStatus)}</span>
                    </div>
                    <div class="sp-onboard-kv-item" style="grid-column: span 2;">
                        <span class="sp-onboard-kv-label">Fehlende Angaben</span>
                        <span class="sp-onboard-kv-value">${escapeHtml(missing)}</span>
                    </div>
                </div>
                ${rec?.last_error ? `
                    <div class="sp-onboard-error-note">
                        <strong>Fehler:</strong> ${escapeHtml(rec.last_error)}
                    </div>
                ` : ""}
            `;

            if (dOnboardBtn) {
                if (isImporting) {
                    dOnboardBtn.disabled = true;
                    dOnboardBtn.className = "sp-btn-action-onboard is-loading";
                    dOnboardBtn.innerHTML = '<span class="sp-spin-inline">&#9696;</span> <span>Importiere...</span>';
                    dOnboardBtn.dataset.action = "";
                } else if (!app.is_payed) {
                    dOnboardBtn.disabled = true;
                    dOnboardBtn.className = "sp-btn-action-onboard";
                    dOnboardBtn.textContent = "Zahlung ausstehend";
                    dOnboardBtn.dataset.action = "";
                } else if (rec && (rec.status === "READY" || rec.status === "PROFILE_REVIEW_REQUIRED" || rec.jobscout_client_id)) {
                    dOnboardBtn.disabled = false;
                    dOnboardBtn.className = "sp-btn-link-profile";
                    dOnboardBtn.style.padding = "9px 14px";
                    dOnboardBtn.style.fontSize = "12.5px";
                    dOnboardBtn.innerHTML = '<span>✓ Profil in Autofill Hub öffnen &rarr;</span>';
                    dOnboardBtn.dataset.action = "open-candidate";
                    dOnboardBtn.dataset.clientId = rec.jobscout_client_id || "";
                } else {
                    dOnboardBtn.disabled = false;
                    dOnboardBtn.className = "sp-btn-action-onboard";
                    dOnboardBtn.style.padding = "9px 14px";
                    dOnboardBtn.style.fontSize = "12.5px";
                    dOnboardBtn.textContent = (rec && rec.status === "IMPORT_FAILED") ? "Erneut importieren" : "Als Bewerber importieren";
                    dOnboardBtn.dataset.action = "onboard";
                    dOnboardBtn.dataset.appId = app.id;
                }
            }
        }

        async function handleOnboardCandidate(applicationId) {
            if (!applicationId || importingIds.has(applicationId)) return;

            const app = allApplications.find(a => a.id === applicationId);
            if (!app) return;

            if (!app.is_payed) {
                setStatus("Bewerber kann nicht importiert werden: Zahlung ist noch ausstehend.", true);
                return;
            }

            try {
                importingIds.add(applicationId);
                renderView();
                if (activeApplicant && activeApplicant.id === applicationId) {
                    renderDrawerOnboarding(activeApplicant);
                }

                setStatus(`Starte Onboarding für "${app.full_name}"...`, false);

                const response = await fetch("/api/supabase/onboard-candidate", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ application_id: applicationId })
                });

                const data = await response.json();

                if (!response.ok || !data.success) {
                    throw new Error(data.error || data.message || `HTTP ${response.status}`);
                }

                // Update local onboarding records cache
                const docCount = typeof data.documents_imported === "number"
                    ? data.documents_imported
                    : (Array.isArray(data.documents_imported) ? data.documents_imported.length : 0);

                onboardingRecords[applicationId] = {
                    supabase_application_id: applicationId,
                    jobscout_client_id: data.client_id,
                    status: data.onboarding_status,
                    payment_verified: true,
                    imported_at: new Date().toISOString(),
                    document_count: docCount,
                    cv_parsed: Boolean(data.cv_parsed),
                    missing_fields: data.missing_fields || [],
                    last_error: null
                };

                setStatus(`✓ Bewerber "${data.client_id}" erfolgreich importiert!`, false);

                // Notify global client selector and SPA sections
                window.dispatchEvent(new CustomEvent("activeClientChanged", {
                    detail: { clientId: data.client_id }
                }));

            } catch (err) {
                console.error("Onboarding failed:", err);
                setStatus(`Import fehlgeschlagen: ${err.message}`, true);

                onboardingRecords[applicationId] = {
                    ...(onboardingRecords[applicationId] || {}),
                    status: "IMPORT_FAILED",
                    last_error: err.message
                };
            } finally {
                importingIds.delete(applicationId);
                renderView();
                if (activeApplicant && activeApplicant.id === applicationId) {
                    renderDrawerOnboarding(activeApplicant);
                }
            }
        }

        async function handleOpenCandidate(clientId) {
            if (!clientId) return;

            try {
                sessionStorage.setItem("autofill:target-client-id", clientId);

                // Make background call to set active client
                fetch("/api/clients/active", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ client_id: clientId })
                }).catch(() => {});

                window.dispatchEvent(new CustomEvent("activeClientChanged", {
                    detail: { clientId: clientId }
                }));

                closeDetailsDrawer();

                const autofillNavLink = document.querySelector('[data-section-link="autofill"]');
                if (autofillNavLink) {
                    autofillNavLink.click();
                } else {
                    window.location.href = "/autofill";
                }
            } catch (err) {
                console.error("Could not switch to Autofill Hub:", err);
            }
        }

        // --- Core Supabase Actions (Preserved) ---
        async function markAsPayed(applicationId) {
            try {
                setStatus("Markiere als bezahlt...", false);
                const client = await getSupabaseClient();
                const response = await client
                    .from("applications")
                    .update({ is_payed: true })
                    .eq("id", applicationId);

                if (response.error) throw response.error;

                const app = allApplications.find(a => a.id === applicationId);
                if (app) app.is_payed = true;

                if (activeApplicant && activeApplicant.id === applicationId) {
                    activeApplicant.is_payed = true;
                    if (dPayToggleBtn) {
                        dPayToggleBtn.className = "sp-btn-pay-status is-paid";
                        dPayToggleBtn.textContent = "✓ Als bezahlt markiert";
                        dPayToggleBtn.disabled = true;
                    }
                    if (dStatusPill) {
                        dStatusPill.className = "sp-status-pill is-paid";
                        dStatusPill.innerHTML = "&#10003; Bezahlt";
                    }
                    renderDrawerOnboarding(activeApplicant);
                }

                setStatus("✓ Als bezahlt markiert.", false);
                renderView();
            } catch (err) {
                console.error("Mark as paid failed:", err);
                setStatus(`Fehler beim Aktualisieren des Zahlungsstatus: ${err.message}`, true);
            }
        }

        async function nextStep(applicationId) {
            const application = allApplications.find(a => a.id === applicationId);
            if (!application) return;

            setStatus("Bereite Next Step vor...");
            const signedDocuments = await Promise.all(application.documents.map(p => getSignedDocument(p).catch(() => null)));
            const validDocs = signedDocuments.filter(Boolean);

            const prepared = {
                ...application,
                source_label: "Supabase",
                documents: validDocs,
                document_count: validDocs.length
            };

            const serialized = JSON.stringify(prepared);
            window.sessionStorage.setItem(APPLICATION_STORAGE_PREFIX + application.id, serialized);
            window.sessionStorage.setItem(LAST_APPLICATION_KEY, application.id);

            window.location.href = `/create-anschreibens?application_id=${encodeURIComponent(application.id)}&source=supabase`;
        }

        async function editApplication(applicationId) {
            const application = allApplications.find(a => a.id === applicationId);
            if (!application) return;

            const signedDocuments = await Promise.all(application.documents.map(p => getSignedDocument(p).catch(() => null)));
            const validDocs = signedDocuments.filter(Boolean);

            const prepared = {
                ...application,
                source_label: "Supabase",
                documents: validDocs,
                document_count: validDocs.length
            };

            window.sessionStorage.setItem(APPLICATION_STORAGE_PREFIX + application.id, JSON.stringify(prepared));
            window.sessionStorage.setItem(LAST_APPLICATION_KEY, application.id);

            window.location.href = `/create-anschreibens?application_id=${encodeURIComponent(application.id)}&source=supabase&mode=edit`;
        }

        async function deleteApplication(applicationId) {
            const application = allApplications.find(a => a.id === applicationId);
            if (!application) return;

            if (!confirm(`Delete application for "${application.full_name}"? This cannot be undone.`)) {
                return;
            }

            try {
                pendingDeletes.add(applicationId);
                closeDetailsDrawer();
                setStatus("Deleting application...", false);

                const client = await getSupabaseClient();
                if (application.documents.length) {
                    await client.storage.from(STORAGE_BUCKET).remove(application.documents).catch(() => {});
                }

                const res = await client.from("applications").delete().eq("id", applicationId);
                if (res.error) throw res.error;

                allApplications = allApplications.filter(a => a.id !== applicationId);
                selectedIds.delete(applicationId);
                updateFilterDropdownOptions();
                setStatus("✓ Application deleted successfully.", false);
                renderView();
            } catch (err) {
                setStatus("Delete failed: " + err.message, true);
            } finally {
                pendingDeletes.delete(applicationId);
            }
        }

        // --- Export to CSV / JSON ---
        function exportApplications(format) {
            const filtered = getFilteredAndSortedApplications();
            const exportData = selectedIds.size > 0
                ? filtered.filter(a => selectedIds.has(a.id))
                : filtered;

            if (!exportData.length) {
                setStatus("No data available to export.", true);
                return;
            }

            const timestamp = new Date().toISOString().slice(0, 10);

            if (format === "json") {
                const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `bewerbungen_${timestamp}.json`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                setStatus(`✓ ${exportData.length} Bewerbungen als JSON exportiert.`);
            } else {
                const headers = ["Name", "E-Mail", "WhatsApp", "Bereich", "Sprachniveau", "Paket", "Preis", "Bank", "Status", "Dokumente", "Eingereicht"];
                const rows = exportData.map(a => [
                    `"${a.full_name.replace(/"/g, '""')}"`,
                    `"${a.email}"`,
                    `"${a.whatsapp}"`,
                    `"${a.field}"`,
                    `"${a.language_level}"`,
                    `"${a.pack}"`,
                    `"${a.price}"`,
                    `"${a.bank}"`,
                    `"${a.is_payed ? 'Bezahlt' : 'Offen'}"`,
                    a.document_count,
                    `"${a.created_at_display}"`
                ]);
                const csv = [headers.join(","), ...rows.map(r => r.join(","))].join("\n");
                const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `bewerbungen_${timestamp}.csv`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                setStatus(`✓ ${exportData.length} Bewerbungen als CSV exportiert.`);
            }
            if (exportMenu) exportMenu.hidden = true;
        }

        // Export dropdown toggle
        exportBtn?.addEventListener("click", e => {
            e.stopPropagation();
            if (exportMenu) exportMenu.hidden = !exportMenu.hidden;
        });

        document.querySelectorAll("[data-export-format]").forEach(btn => {
            btn.addEventListener("click", () => exportApplications(btn.dataset.exportFormat));
        });

        document.addEventListener("click", () => {
            if (exportMenu) exportMenu.hidden = true;
            if (colVisibilityMenu) colVisibilityMenu.hidden = true;
        });

        // Action delegation across views
        root.addEventListener("click", e => {
            const btn = e.target.closest("[data-action]");
            if (!btn) return;
            e.preventDefault();
            e.stopPropagation();
            const action = btn.dataset.action;
            const id = btn.dataset.appId;

            if (action === "open-candidate") {
                handleOpenCandidate(btn.dataset.clientId);
                return;
            }

            if (!id) return;

            if (action === "details") openDetailsDrawer(id);
            if (action === "next-step") nextStep(id);
            if (action === "pay") markAsPayed(id);
            if (action === "onboard") handleOnboardCandidate(id);
        });

        // --- Event Listeners for Toolbar & Customization ---
        viewCardsBtn?.addEventListener("click", () => {
            preferences.viewMode = "cards";
            savePreferences();
            renderView();
        });
        viewCompactBtn?.addEventListener("click", () => {
            preferences.viewMode = "compact";
            savePreferences();
            renderView();
        });
        viewTableBtn?.addEventListener("click", () => {
            preferences.viewMode = "table";
            savePreferences();
            renderView();
        });

        columnsSelect?.addEventListener("change", () => {
            preferences.columns = columnsSelect.value;
            savePreferences();
            renderView();
        });

        densitySelect?.addEventListener("change", () => {
            preferences.density = densitySelect.value;
            savePreferences();
            renderView();
        });

        sortSelect?.addEventListener("change", () => {
            preferences.sortBy = sortSelect.value;
            savePreferences();
            renderView();
        });

        // Column Visibility Dropdown
        colVisibilityBtn?.addEventListener("click", e => {
            e.stopPropagation();
            if (colVisibilityMenu) colVisibilityMenu.hidden = !colVisibilityMenu.hidden;
        });
        colVisibilityMenu?.addEventListener("click", e => e.stopPropagation());

        colVisibilityMenu?.querySelectorAll("input[data-col]").forEach(cb => {
            const col = cb.dataset.col;
            cb.checked = preferences.visibleColumns[col] !== false;
            cb.addEventListener("change", () => {
                preferences.visibleColumns[col] = cb.checked;
                savePreferences();
                renderView();
            });
        });

        resetPrefsBtn?.addEventListener("click", () => {
            preferences = { ...defaultPreferences, visibleColumns: { ...defaultPreferences.visibleColumns } };
            savePreferences();
            syncControlsToPreferences();
            renderView();
            setStatus("Ansichtseinstellungen zurückgesetzt.");
        });

        function syncControlsToPreferences() {
            if (columnsSelect) columnsSelect.value = preferences.columns;
            if (densitySelect) densitySelect.value = preferences.density;
            if (sortSelect) sortSelect.value = preferences.sortBy;
            if (pageSizeSelect) pageSizeSelect.value = preferences.pageSize;
            if (colVisibilityMenu) {
                colVisibilityMenu.querySelectorAll("input[data-col]").forEach(cb => {
                    cb.checked = preferences.visibleColumns[cb.dataset.col] !== false;
                });
            }
        }

        // Filter Toggle & Clear
        filterToggleBtn?.addEventListener("click", () => {
            if (filterDrawer) filterDrawer.hidden = !filterDrawer.hidden;
        });

        filterClearAllBtn?.addEventListener("click", clearAllFilters);
        emptyResetBtn?.addEventListener("click", clearAllFilters);

        // Search Input & Debouncing
        let searchTimer = null;
        searchInput?.addEventListener("input", () => {
            if (searchClearBtn) searchClearBtn.hidden = !searchInput.value;
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => {
                preferences.currentPage = 1;
                renderView();
            }, 200);
        });

        searchClearBtn?.addEventListener("click", () => {
            if (searchInput) searchInput.value = "";
            searchClearBtn.hidden = true;
            preferences.currentPage = 1;
            renderView();
        });

        // Filter Inputs Event Listeners
        [filterPack, filterLanguage, filterPayment, filterField, filterBank, filterDateFrom, filterDateTo].forEach(el => {
            el?.addEventListener("change", () => {
                preferences.currentPage = 1;
                renderView();
            });
        });

        // --- Data Fetching from Supabase ---
        async function loadApplications(force) {
            if ((hasLoaded && !force) || isLoading) return;

            setLoading(true);
            setStatus("Lade Bewerbungen aus Supabase...", false);
            if (emptyState) emptyState.hidden = true;

            try {
                const client = await getSupabaseClient();
                const [response, statusRes] = await Promise.all([
                    client
                        .from("applications")
                        .select("id,created_at,pack,full_name,email,whatsapp,bank,language_level,field,documents,is_payed")
                        .order("created_at", { ascending: false }),
                    fetch("/api/supabase/onboarding-status").then(r => r.ok ? r.json() : null).catch(() => null)
                ]);

                if (response.error) throw response.error;

                if (statusRes && statusRes.records) {
                    onboardingRecords = statusRes.records;
                }

                allApplications = (response.data || []).map(normalizeApplication);
                updateFilterDropdownOptions();
                syncControlsToPreferences();
                renderView();
                setStatus("", false);
                hasLoaded = true;
            } catch (error) {
                console.error("Supabase load failed.", error);
                if (emptyState) emptyState.hidden = true;
                setStatus(error.message || "Supabase-Daten konnten nicht geladen werden.", true);
            } finally {
                setLoading(false);
            }
        }

        refreshBtn?.addEventListener("click", () => {
            signedDocumentCache.clear();
            hasLoaded = false;
            loadApplications(true);
        });

        return {
            show() {
                loadApplications(false);
            },
            hide() {
                closeDetailsDrawer();
            }
        };
    };
})();

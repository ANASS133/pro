(function () {
    const sections = window.SPASections || {};

    sections.createSupabaseSection = function createSupabaseSection() {
        const cardsRoot = document.getElementById("supabase-cards");
        const emptyState = document.getElementById("supabase-empty");
        const statusNode = document.getElementById("supabase-status");
        const searchInput = document.getElementById("supabase-search");
        const filterPack = document.getElementById("supabase-filter-pack");
        const filterLanguage = document.getElementById("supabase-filter-language");
        const refreshBtn = document.getElementById("supabase-refresh");

        if (!cardsRoot || !emptyState || !statusNode) {
            return { show() {}, hide() {} };
        }

        const escapeHtml = (window.SPAUtils && window.SPAUtils.escapeHtml) || function fallbackEscapeHtml(value) {
            return String(value ?? "")
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#39;");
        };

        const APPLICATION_STORAGE_PREFIX = "create-anschreibens:application:";
        const LAST_APPLICATION_KEY = "create-anschreibens:last-application";
        const LEGACY_APPLICATION_STORAGE_PREFIX = "create-anschreibens:firebase-application:";
        const LEGACY_LAST_APPLICATION_KEY = "create-anschreibens:last-firebase-application";
        const STORAGE_BUCKET = "applications";
        const SIGNED_URL_TTL_SECONDS = 60 * 60;

        let allApplications = [];
        let hasLoaded = false;
        let isLoading = false;
        const pendingDeletes = new Set();
        const signedDocumentCache = new Map();

        function getSupabaseClient() {
            if (!window.AppSupabase || typeof window.AppSupabase.getClient !== "function") {
                throw new Error("Supabase client helper is not available.");
            }
            return window.AppSupabase.getClient();
        }

        function setStatus(message, isError) {
            const value = String(message || "").trim();
            statusNode.hidden = !value;
            statusNode.textContent = value;
            statusNode.classList.toggle("is-error", Boolean(isError));
        }

        function setLoading(loading) {
            isLoading = Boolean(loading);
            if (refreshBtn) {
                refreshBtn.disabled = isLoading;
                refreshBtn.textContent = isLoading ? "Lade..." : "Refresh";
            }
        }

        function formatCreatedAt(value) {
            if (!value) {
                return "k. A.";
            }

            const date = new Date(value);
            if (Number.isNaN(date.getTime())) {
                return "k. A.";
            }

            return new Intl.DateTimeFormat("de-DE", {
                day: "2-digit",
                month: "2-digit",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit",
            }).format(date);
        }

        function fileName(filePath) {
            const cleanPath = String(filePath || "").split("?")[0];
            const parts = cleanPath.split("/");
            return parts[parts.length - 1] || cleanPath || "Dokument";
        }

        function normalizeDocumentPaths(value) {
            if (!Array.isArray(value)) {
                return [];
            }

            return value
                .map(function (entry) {
                    if (typeof entry === "string") {
                        return entry.trim();
                    }
                    if (entry && typeof entry === "object") {
                        return String(entry.path || entry.storagePath || entry.name || "").trim();
                    }
                    return "";
                })
                .filter(Boolean);
        }

        function normalizeApplication(row) {
            const documents = normalizeDocumentPaths(row.documents);
            const createdAt = row.created_at || "";
            const fullName = String(row.full_name || "").trim();
            const field = String(row.field || "").trim();
            const pack = String(row.pack || "").trim();
            const languageLevel = String(row.language_level || "").trim();

            return {
                id: String(row.id || "").trim(),
                source_label: "Supabase",
                full_name: fullName || "Unnamed applicant",
                fullName: fullName || "Unnamed applicant",
                email: String(row.email || "").trim() || "k. A.",
                whatsapp: String(row.whatsapp || "").trim() || "k. A.",
                bank: String(row.bank || "").trim() || "k. A.",
                language_level: languageLevel || "k. A.",
                languageLevel: languageLevel || "",
                field: field || "k. A.",
                bereich: field || "",
                pack: pack || "k. A.",
                bewerbungen: pack || "",
                documents,
                document_count: documents.length,
                created_at: createdAt,
                created_at_display: formatCreatedAt(createdAt),
                sort_time: createdAt ? new Date(createdAt).getTime() || 0 : 0,
                raw: row,
            };
        }

        function getFilteredApplications() {
            const searchTerm = String(searchInput ? searchInput.value : "").toLowerCase().trim();
            const packValue = String(filterPack ? filterPack.value : "").trim();
            const languageValue = String(filterLanguage ? filterLanguage.value : "").trim();

            return allApplications.filter(function (application) {
                if (searchTerm) {
                    const matchesSearch = [
                        application.full_name,
                        application.email,
                        application.whatsapp,
                    ].some(function (value) {
                        return String(value || "").toLowerCase().includes(searchTerm);
                    });

                    if (!matchesSearch) {
                        return false;
                    }
                }

                if (packValue && application.pack !== packValue) {
                    return false;
                }

                if (languageValue && application.language_level !== languageValue) {
                    return false;
                }

                return true;
            });
        }

        async function getSignedDocument(path) {
            const normalizedPath = String(path || "").trim();
            if (!normalizedPath) {
                return null;
            }

            if (signedDocumentCache.has(normalizedPath)) {
                return signedDocumentCache.get(normalizedPath);
            }

            const client = await getSupabaseClient();
            const response = await client.storage
                .from(STORAGE_BUCKET)
                .createSignedUrl(normalizedPath, SIGNED_URL_TTL_SECONDS);

            if (response.error) {
                throw response.error;
            }

            const signedDocument = {
                path: normalizedPath,
                name: fileName(normalizedPath),
                url: response.data.signedUrl,
                downloadURL: response.data.signedUrl,
            };

            signedDocumentCache.set(normalizedPath, signedDocument);
            return signedDocument;
        }

        async function getSignedDocuments(paths) {
            const items = await Promise.all(paths.map(async function (path) {
                try {
                    return await getSignedDocument(path);
                } catch (error) {
                    console.error("Could not create signed URL for Supabase document.", path, error);
                    return {
                        path,
                        name: fileName(path),
                        url: "",
                        downloadURL: "",
                        error: true,
                    };
                }
            }));

            return items.filter(Boolean);
        }

        function renderDocumentList(documents) {
            if (!documents.length) {
                return '<li class="supabase-doc-item supabase-doc-empty">Keine Dokumente</li>';
            }

            return documents.map(function (documentItem) {
                if (documentItem.error || !documentItem.url) {
                    return (
                        '<li class="supabase-doc-item supabase-doc-error" title="' +
                        escapeHtml(documentItem.path) +
                        '">' +
                        escapeHtml(documentItem.name) +
                        " nicht verfügbar</li>"
                    );
                }

                return (
                    '<li class="supabase-doc-item">' +
                    '<a class="supabase-doc-link" href="' +
                    escapeHtml(documentItem.url) +
                    '" target="_blank" rel="noopener noreferrer" download>' +
                    escapeHtml(documentItem.name) +
                    "</a>" +
                    "</li>"
                );
            }).join("");
        }

        function getPriceForPack(pack) {
            const normalizedPack = String(pack || "").toLowerCase();
            if (normalizedPack.includes("1000")) {
                return "400 dh";
            }
            if (normalizedPack.includes("500")) {
                return "200 dh";
            }
            return "k. A.";
        }

        function renderCard(application, signedDocuments) {
            const isPending = pendingDeletes.has(application.id);
            const documentList = renderDocumentList(signedDocuments);
            const price = getPriceForPack(application.pack);

            return (
                '<article class="card supabase-card' +
                (isPending ? " supabase-card--deleting" : "") +
                '" data-supabase-id="' +
                escapeHtml(application.id) +
                '">' +
                '<div class="supabase-card-head">' +
                "<h3>" +
                escapeHtml(application.full_name) +
                "</h3>" +
                '<span class="supabase-badge">Supabase</span>' +
                "</div>" +
                '<div class="meta supabase-meta">' +
                '<div><span>Full name</span><strong>' + escapeHtml(application.full_name) + "</strong></div>" +
                '<div><span>E-Mail</span><strong>' + escapeHtml(application.email) + "</strong></div>" +
                '<div><span>WhatsApp</span><strong>' + escapeHtml(application.whatsapp) + "</strong></div>" +
                '<div><span>Paket</span><strong>' + escapeHtml(application.pack) + "</strong></div>" +
                '<div><span>Price</span><strong>' + escapeHtml(price) + "</strong></div>" +
                '<div><span>Bank</span><strong>' + escapeHtml(application.bank) + "</strong></div>" +
                '<div><span>Sprachniveau</span><strong>' + escapeHtml(application.language_level) + "</strong></div>" +
                '<div><span>Bereich</span><strong>' + escapeHtml(application.field) + "</strong></div>" +
                '<div><span>Eingereicht</span><strong>' + escapeHtml(application.created_at_display) + "</strong></div>" +
                "</div>" +
                '<div class="supabase-documents">' +
                "<h4>Dokumente (" + escapeHtml(application.document_count) + ")</h4>" +
                '<ul class="supabase-document-list">' +
                documentList +
                "</ul>" +
                "</div>" +
                '<div class="supabase-actions">' +
                '<div class="supabase-actions-menu">' +
                '<button type="button" class="supabase-dots-btn" data-supabase-id="' +
                escapeHtml(application.id) +
                '" aria-label="Aktionen" aria-expanded="false">' +
                '<span class="supabase-dots-icon">&#8942;</span>' +
                '</button>' +
                '<div class="supabase-actions-dropdown" hidden>' +
                '<button type="button" class="supabase-next-step-btn" data-supabase-id="' +
                escapeHtml(application.id) +
                '"' +
                (isPending ? " disabled" : "") +
                '>Next step</button>' +
                '<button type="button" class="supabase-edit-btn" data-supabase-id="' +
                escapeHtml(application.id) +
                '"' +
                (isPending ? " disabled" : "") +
                '>Bearbeiten</button>' +
                '<button type="button" class="supabase-delete-btn" data-supabase-id="' +
                escapeHtml(application.id) +
                '"' +
                (isPending ? " disabled" : "") +
                '>' +
                (isPending ? "Lösche..." : "Löschen") +
                '</button>' +
                '</div>' +
                '</div>' +
                "</div>" +
                "</article>"
            );
        }

        function updatePackFilterOptions() {
            if (!filterPack) {
                return;
            }

            const currentValue = filterPack.value;
            const packs = Array.from(new Set(
                allApplications
                    .map(function (application) { return application.pack; })
                    .filter(function (pack) { return pack && pack !== "k. A."; })
            )).sort(function (left, right) {
                return left.localeCompare(right, "de");
            });

            filterPack.innerHTML =
                '<option value="">Alle Pakete</option>' +
                packs.map(function (pack) {
                    return '<option value="' + escapeHtml(pack) + '">' + escapeHtml(pack) + "</option>";
                }).join("");

            if (packs.includes(currentValue)) {
                filterPack.value = currentValue;
            }
        }

        async function renderApplications(applications) {
            if (!applications.length) {
                cardsRoot.innerHTML = "";
                emptyState.hidden = false;
                return;
            }

            emptyState.hidden = true;
            cardsRoot.innerHTML =
                '<div class="supabase-loading"><span class="supabase-spinner"></span>Dokumente werden geladen...</div>';

            const cardHtml = await Promise.all(applications.map(async function (application) {
                const signedDocuments = await getSignedDocuments(application.documents);
                return renderCard(application, signedDocuments);
            }));

            cardsRoot.innerHTML = cardHtml.join("");
        }

        async function renderFilteredApplications() {
            await renderApplications(getFilteredApplications());
        }

        async function loadApplications(force) {
            if ((hasLoaded && !force) || isLoading) {
                return;
            }

            setLoading(true);
            setStatus("Lade Bewerbungen aus Supabase...", false);
            emptyState.hidden = true;
            cardsRoot.innerHTML =
                '<div class="supabase-loading"><span class="supabase-spinner"></span>Bewerbungen werden geladen...</div>';

            try {
                const client = await getSupabaseClient();
                const response = await client
                    .from("applications")
                    .select("id,created_at,pack,full_name,email,whatsapp,bank,language_level,field,documents")
                    .order("created_at", { ascending: false });

                if (response.error) {
                    throw response.error;
                }

                allApplications = (response.data || []).map(normalizeApplication);
                updatePackFilterOptions();
                await renderFilteredApplications();
                setStatus("", false);
                hasLoaded = true;
            } catch (error) {
                console.error("Supabase application load failed.", error);
                cardsRoot.innerHTML = "";
                emptyState.hidden = true;
                setStatus(error.message || "Supabase-Daten konnten nicht geladen werden.", true);
            } finally {
                setLoading(false);
            }
        }

        function getApplicationById(applicationId) {
            return allApplications.find(function (application) {
                return application.id === applicationId;
            }) || null;
        }

        async function buildApplicationForNextStep(application) {
            const signedDocuments = await getSignedDocuments(application.documents);
            return {
                ...application,
                source_label: "Supabase",
                documents: signedDocuments,
                document_count: signedDocuments.length,
            };
        }

        function persistApplicationForNextStep(application) {
            const serialized = JSON.stringify(application);
            window.sessionStorage.setItem(APPLICATION_STORAGE_PREFIX + application.id, serialized);
            window.sessionStorage.setItem(LAST_APPLICATION_KEY, application.id);

            window.sessionStorage.setItem(LEGACY_APPLICATION_STORAGE_PREFIX + application.id, serialized);
            window.sessionStorage.setItem(LEGACY_LAST_APPLICATION_KEY, application.id);
        }

        async function nextStep(applicationId) {
            const application = getApplicationById(applicationId);
            if (!application) {
                return;
            }

            const preparedApplication = await buildApplicationForNextStep(application);
            try {
                persistApplicationForNextStep(preparedApplication);
            } catch (error) {
                console.warn("Could not cache Supabase application for the next step.", error);
            }

            window.location.href =
                "/create-anschreibens?application_id=" +
                encodeURIComponent(application.id) +
                "&source=supabase";
        }

        async function deleteApplication(applicationId) {
            const application = getApplicationById(applicationId);
            if (!application) {
                return;
            }

            const confirmed = window.confirm(
                "Diese Bewerbung löschen? Das kann nicht rückgängig gemacht werden."
            );
            if (!confirmed) {
                return;
            }

            pendingDeletes.add(applicationId);
            await renderFilteredApplications();

            try {
                const client = await getSupabaseClient();

                if (application.documents.length) {
                    const storageResponse = await client.storage
                        .from(STORAGE_BUCKET)
                        .remove(application.documents);

                    if (storageResponse.error) {
                        console.error("Supabase storage delete failed.", storageResponse.error);
                    }
                }

                const deleteResponse = await client
                    .from("applications")
                    .delete()
                    .eq("id", applicationId);

                if (deleteResponse.error) {
                    throw deleteResponse.error;
                }

                allApplications = allApplications.filter(function (item) {
                    return item.id !== applicationId;
                });
                updatePackFilterOptions();
                setStatus("Bewerbung gelöscht.", false);
            } catch (error) {
                console.error("Supabase application delete failed.", error);
                setStatus(error.message || "Bewerbung konnte nicht gelöscht werden.", true);
            } finally {
                pendingDeletes.delete(applicationId);
                await renderFilteredApplications();
            }
        }

        async function editApplication(applicationId) {
            const application = getApplicationById(applicationId);
            if (!application) {
                return;
            }

            closeActionMenus();

            const signedDocuments = await getSignedDocuments(application.documents);
            const prepared = {
                ...application,
                source_label: "Supabase",
                documents: signedDocuments,
                document_count: signedDocuments.length,
            };

            persistApplicationForNextStep(prepared);
            window.location.href = "/create-anschreibens?application_id=" + encodeURIComponent(applicationId) + "&source=supabase&mode=edit";
        }

        function debounce(callback, delay) {
            let timer = null;
            return function debouncedCallback() {
                const context = this;
                const args = arguments;
                window.clearTimeout(timer);
                timer = window.setTimeout(function () {
                    callback.apply(context, args);
                }, delay);
            };
        }

        function closeActionMenus() {
            cardsRoot.querySelectorAll(".supabase-actions-menu").forEach(function (menu) {
                const dropdown = menu.querySelector(".supabase-actions-dropdown");
                const button = menu.querySelector(".supabase-dots-btn");
                if (dropdown) {
                    dropdown.hidden = true;
                }
                if (button) {
                    button.setAttribute("aria-expanded", "false");
                }
            });
        }

        cardsRoot.addEventListener("click", function (event) {
            const dotsButton = event.target.closest(".supabase-dots-btn");
            if (dotsButton) {
                event.stopPropagation();
                const card = dotsButton.closest(".supabase-card");
                if (!card) {
                    return;
                }
                const dropdown = card.querySelector(".supabase-actions-dropdown");
                if (!dropdown) {
                    return;
                }
                const isOpen = !dropdown.hidden;
                closeActionMenus();
                if (!isOpen) {
                    dropdown.hidden = false;
                    dotsButton.setAttribute("aria-expanded", "true");
                }
                return;
            }

            const editButton = event.target.closest(".supabase-edit-btn");
            if (editButton && !editButton.disabled) {
                const applicationId = String(editButton.dataset.supabaseId || "").trim();
                if (applicationId) {
                    editApplication(applicationId).catch(function (error) {
                        console.error("Supabase edit failed.", error);
                        setStatus(error.message || "Bearbeiten konnte nicht gestartet werden.", true);
                    });
                }
                return;
            }

            const nextButton = event.target.closest(".supabase-next-step-btn");
            if (nextButton && !nextButton.disabled) {
                const applicationId = String(nextButton.dataset.supabaseId || "").trim();
                if (applicationId) {
                    nextStep(applicationId).catch(function (error) {
                        console.error("Supabase next step failed.", error);
                        setStatus(error.message || "Next step konnte nicht gestartet werden.", true);
                    });
                }
                return;
            }

            const deleteButton = event.target.closest(".supabase-delete-btn");
            if (deleteButton && !deleteButton.disabled) {
                const applicationId = String(deleteButton.dataset.supabaseId || "").trim();
                if (applicationId) {
                    deleteApplication(applicationId).catch(function (error) {
                        console.error("Supabase delete failed.", error);
                        setStatus(error.message || "Bewerbung konnte nicht gelöscht werden.", true);
                    });
                }
            }
        });

        document.addEventListener("click", function (event) {
            if (!event.target.closest(".supabase-actions-menu")) {
                closeActionMenus();
            }
        });

        if (searchInput) {
            searchInput.addEventListener("input", debounce(function () {
                renderFilteredApplications().catch(function (error) {
                    console.error("Supabase search render failed.", error);
                });
            }, 250));
        }

        if (filterPack) {
            filterPack.addEventListener("change", function () {
                renderFilteredApplications().catch(function (error) {
                    console.error("Supabase pack filter render failed.", error);
                });
            });
        }

        if (filterLanguage) {
            filterLanguage.addEventListener("change", function () {
                renderFilteredApplications().catch(function (error) {
                    console.error("Supabase language filter render failed.", error);
                });
            });
        }

        if (refreshBtn) {
            refreshBtn.addEventListener("click", function () {
                signedDocumentCache.clear();
                hasLoaded = false;
                loadApplications(true).catch(function (error) {
                    console.error("Supabase refresh failed.", error);
                });
            });
        }

        return {
            show() {
                loadApplications(false).catch(function (error) {
                    console.error("Supabase section show failed.", error);
                });
            },
            hide() {},
        };
    };

    window.SPASections = sections;
})();

(function () {
    const sections = window.SPASections || {};

    sections.createFirebaseSection = function createFirebaseSection() {
        const cardsRoot = document.getElementById("firebase-cards");
        const emptyState = document.getElementById("firebase-empty");
        const statusNode = document.getElementById("firebase-status");

        if (!cardsRoot || !emptyState || !statusNode) {
            return {
                show() {},
                hide() {},
            };
        }

        const escapeHtml = window.SPAUtils.escapeHtml;
        const fetchJson = window.SPAUtils.fetchJson;
        const pendingDeletes = new Set();
        const APPLICATION_STORAGE_PREFIX = "create-anschreibens:firebase-application:";
        const LAST_APPLICATION_KEY = "create-anschreibens:last-firebase-application";
        const firebaseConfig = {
            apiKey: "AIzaSyD3xQalpdCJZK2GNCYRP8noiY5ei6oOtFw",
            authDomain: "clients-9d7fe.firebaseapp.com",
            projectId: "clients-9d7fe",
            storageBucket: "clients-9d7fe.firebasestorage.app",
            messagingSenderId: "489647859812",
            appId: "1:489647859812:web:6f0f06a20beef2ea6a9771",
        };

        let hasLoaded = false;
        let lastApplications = [];
        let firebaseClientRequest = null;

        function setStatus(message, isError) {
            if (!message) {
                statusNode.hidden = true;
                statusNode.textContent = "";
                statusNode.classList.remove("is-error");
                return;
            }

            statusNode.hidden = false;
            statusNode.textContent = message;
            statusNode.classList.toggle("is-error", Boolean(isError));
        }

        function toMillis(value) {
            if (!value) {
                return 0;
            }

            if (typeof value.toMillis === "function") {
                try {
                    return value.toMillis();
                } catch (_error) {
                    return 0;
                }
            }

            if (typeof value.toDate === "function") {
                try {
                    return value.toDate().getTime();
                } catch (_error) {
                    return 0;
                }
            }

            if (typeof value.seconds === "number") {
                const nanos = typeof value.nanoseconds === "number" ? value.nanoseconds : 0;
                return (value.seconds * 1000) + Math.round(nanos / 1000000);
            }

            if (typeof value === "string") {
                const parsed = Date.parse(value);
                return Number.isFinite(parsed) ? parsed : 0;
            }

            return 0;
        }

        function formatCreatedAt(value) {
            const millis = toMillis(value);
            if (!millis) {
                return "k. A.";
            }

            return new Intl.DateTimeFormat("de-DE", {
                day: "2-digit",
                month: "2-digit",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit",
            }).format(new Date(millis));
        }

        function normalizeFirebaseApplication(snapshot) {
            const data = snapshot.data() || {};
            const documents = Array.isArray(data.documents) ? data.documents : [];

            return {
                id: snapshot.id,
                source_label: "Firebase",
                fullName: String(data.fullName || "").trim() || "Unnamed applicant",
                email: String(data.email || "").trim() || "k. A.",
                whatsapp: String(data.whatsapp || "").trim() || "k. A.",
                bewerbungen: String(data.bewerbungen || "").trim() || "k. A.",
                bereich: String(data.bereich || "").trim() || "k. A.",
                bank: String(data.bank || "").trim() || "",
                languageLevel: String(data.languageLevel || "").trim() || "",
                documents,
                document_count: documents.length,
                created_at_display: formatCreatedAt(data.createdAt),
                sort_time: toMillis(data.createdAt),
            };
        }

        function storeApplicationForNextStep(application) {
            const applicationId = String(application?.id || "").trim();
            if (!applicationId) {
                return;
            }

            try {
                window.sessionStorage.setItem(
                    `${APPLICATION_STORAGE_PREFIX}${applicationId}`,
                    JSON.stringify(application),
                );
                window.sessionStorage.setItem(LAST_APPLICATION_KEY, applicationId);
            } catch (_error) {
                // Best effort cache only.
            }
        }

        function renderApplication(application) {
            const applicationId = String(application.id || "");
            let documentsHtml = `<span>0</span>`;
            if (application.documents && application.documents.length > 0) {
                documentsHtml = application.documents.map((doc, i) => {
                    const docName = doc.name ? escapeHtml(doc.name) : `Dokument ${i + 1}`;
                    const docUrl = doc.downloadURL || doc.url || "";
                    if (!docUrl) {
                        return `<span>${docName}</span>`;
                    }
                    return `<a href="${escapeHtml(docUrl)}" target="_blank" rel="noopener noreferrer" style="color: var(--primary); text-decoration: underline; cursor: pointer;">${docName}</a>`;
                }).join(", ");
            }

            return `
                <article class="firebase-card" data-firebase-id="${escapeHtml(applicationId)}">
                    <h3>
                        ${escapeHtml(application.fullName || "Unnamed applicant")}
                        <span class="firebase-badge">${escapeHtml(application.source_label || "Firebase")}</span>
                    </h3>
                    <div class="firebase-meta">
                        Quelle: <strong>${escapeHtml(application.source_label || "Firebase")}</strong><br>
                        E-Mail: <strong>${escapeHtml(application.email || "k. A.")}</strong><br>
                        WhatsApp: <span>${escapeHtml(application.whatsapp || "k. A.")}</span><br>
                        Paket: <span>${escapeHtml(application.bewerbungen || "k. A.")}</span><br>
                        Bereich: <span>${escapeHtml(application.bereich || "k. A.")}</span><br>
                        Bank: <span>${escapeHtml(application.bank || "k. A.")}</span><br>
                        Dokumente: ${documentsHtml}<br>
                        Eingereicht: <span>${escapeHtml(application.created_at_display || "k. A.")}</span>
                    </div>
                    <div class="campaign-actions">
                        <button
                            type="button"
                            class="action-btn primary firebase-next-step-btn"
                            data-firebase-id="${escapeHtml(applicationId)}"
                        >
                            Next step
                        </button>
                        <button
                            type="button"
                            class="action-btn danger firebase-delete-btn"
                            data-firebase-id="${escapeHtml(applicationId)}"
                            ${pendingDeletes.has(applicationId) ? "disabled" : ""}
                        >
                            ${pendingDeletes.has(applicationId) ? "Lösche..." : "Löschen"}
                        </button>
                    </div>
                </article>
            `;
        }

        function renderApplications(applications) {
            const items = Array.isArray(applications) ? applications : [];
            lastApplications = items;
            emptyState.hidden = items.length > 0;
            cardsRoot.innerHTML = items.map(renderApplication).join("");
        }

        async function getFirebaseClient() {
            if (firebaseClientRequest) {
                return firebaseClientRequest;
            }

            firebaseClientRequest = Promise.all([
                import("https://www.gstatic.com/firebasejs/12.7.0/firebase-app.js"),
                import("https://www.gstatic.com/firebasejs/12.7.0/firebase-firestore.js"),
            ]).then(([firebaseApp, firestore]) => {
                const firebaseAppName = "spa-firebase-section";
                const app = firebaseApp.getApps().some((entry) => entry.name === firebaseAppName)
                    ? firebaseApp.getApp(firebaseAppName)
                    : firebaseApp.initializeApp(firebaseConfig, firebaseAppName);

                return {
                    db: firestore.getFirestore(app),
                    collection: firestore.collection,
                    deleteDoc: firestore.deleteDoc,
                    doc: firestore.doc,
                    getDocs: firestore.getDocs,
                };
            });

            return firebaseClientRequest;
        }

        async function loadApplicationsViaClient() {
            const firebaseClient = await getFirebaseClient();
            const snapshot = await firebaseClient.getDocs(
                firebaseClient.collection(firebaseClient.db, "applications"),
            );

            return snapshot.docs
                .map(normalizeFirebaseApplication)
                .sort((left, right) => (right.sort_time || 0) - (left.sort_time || 0));
        }

        async function loadApplicationsViaApi() {
            const payload = await fetchJson("/api/firebase/applications");
            if (!payload.success || !Array.isArray(payload.applications)) {
                throw new Error(payload.message || "Firebase-Daten konnten nicht geladen werden");
            }
            return payload.applications;
        }

        async function loadApplications(force) {
            if (hasLoaded && !force) {
                return;
            }

            try {
                const applications = await loadApplicationsViaClient();
                renderApplications(applications);
                setStatus("", false);
                hasLoaded = true;
                return;
            } catch (clientError) {
                try {
                    const applications = await loadApplicationsViaApi();
                    renderApplications(applications);
                    setStatus("", false);
                    hasLoaded = true;
                    return;
                } catch (apiError) {
                    setStatus(
                        apiError.message
                        || clientError.message
                        || "Firebase-Daten konnten nicht geladen werden.",
                        true,
                    );
                }
            }
        }

        async function deleteApplicationViaClient(applicationId) {
            const firebaseClient = await getFirebaseClient();
            await firebaseClient.deleteDoc(
                firebaseClient.doc(firebaseClient.db, "applications", applicationId),
            );
        }

        async function deleteApplication(button) {
            const applicationId = String(button.dataset.firebaseId || "").trim();
            if (!applicationId) {
                return;
            }

            const confirmed = window.confirm(
                "Diese Firebase-Bewerbung löschen? Das kann nicht rückgängig gemacht werden.",
            );
            if (!confirmed) {
                return;
            }

            pendingDeletes.add(applicationId);
            renderApplications(lastApplications);

            try {
                await deleteApplicationViaClient(applicationId);
                setStatus("Firebase-Bewerbung gelöscht.", false);
            } catch (clientError) {
                try {
                    const payload = await fetchJson(`/api/firebase/delete/${encodeURIComponent(applicationId)}`, {
                        method: "POST",
                    });
                    if (!payload.success) {
                        throw new Error(payload.message || "Firebase-Bewerbung konnte nicht gelöscht werden");
                    }
                    setStatus("Firebase-Bewerbung gelöscht.", false);
                } catch (apiError) {
                    setStatus(
                        apiError.message
                        || clientError.message
                        || "Firebase-Bewerbung konnte nicht gelöscht werden.",
                        true,
                    );
                }
            } finally {
                pendingDeletes.delete(applicationId);
                await loadApplications(true);
            }
        }

        cardsRoot.addEventListener("click", (event) => {
            const nextStepButton = event.target.closest(".firebase-next-step-btn");
            if (nextStepButton) {
                const applicationId = String(nextStepButton.dataset.firebaseId || "").trim();
                const application = lastApplications.find((item) => String(item.id || "").trim() === applicationId);
                if (application) {
                    storeApplicationForNextStep(application);
                }
                window.location.href = `/create-anschreibens?application_id=${encodeURIComponent(applicationId)}`;
                return;
            }

            const deleteButton = event.target.closest(".firebase-delete-btn");
            if (!deleteButton) {
                return;
            }
            deleteApplication(deleteButton).catch(() => {});
        });

        return {
            show() {
                loadApplications(true).catch(() => {});
            },
            hide() {},
        };
    };

    window.SPASections = sections;
})();

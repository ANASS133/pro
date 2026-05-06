(function () {
    const sections = window.SPASections || {};

    sections.createAddSection = function createAddSection() {
        const form = document.getElementById("add-candidate-form");
        const bereichSelect = document.getElementById("add-bereich");
        const fileInput = document.getElementById("add-documents");
        const fileMeta = document.getElementById("add-file-meta");
        const statusMessage = document.getElementById("add-status-message");
        const submitButton = document.getElementById("add-submit-button");

        if (!form || !bereichSelect || !fileInput || !fileMeta || !statusMessage || !submitButton) {
            return {
                show() {},
                hide() {},
            };
        }

        const utils = window.SPAUtils || {};
        const fetchJson = typeof utils.fetchJson === "function"
            ? utils.fetchJson
            : async function fallbackFetchJson(url, options) {
                const response = await fetch(url, options);
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(payload.error || payload.message || `Request failed (${response.status})`);
                }
                return payload;
            };

        const firebaseConfig = {
            apiKey: "AIzaSyD3xQalpdCJZK2GNCYRP8noiY5ei6oOtFw",
            authDomain: "clients-9d7fe.firebaseapp.com",
            projectId: "clients-9d7fe",
            storageBucket: "clients-9d7fe.firebasestorage.app",
            messagingSenderId: "489647859812",
            appId: "1:489647859812:web:6f0f06a20beef2ea6a9771",
        };

        const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;
        const MAX_TOTAL_SIZE_BYTES = 25 * 1024 * 1024;
        const STORAGE_UPLOAD_TIMEOUT_MS = 120000;
        const STORAGE_DOWNLOAD_URL_TIMEOUT_MS = 30000;

        let initialized = false;
        let domainsLoaded = false;
        let domainsRequest = null;
        let firebaseClientRequest = null;

        function showStatus(message, type) {
            statusMessage.textContent = String(message || "");
            statusMessage.className = `add-status-message ${type || ""}`.trim();
        }

        function clearStatus() {
            statusMessage.textContent = "";
            statusMessage.className = "add-status-message";
        }

        function setSubmitting(isSubmitting) {
            submitButton.disabled = isSubmitting;
            submitButton.textContent = isSubmitting ? "Saving to Firebase..." : "Save to Firebase";
        }

        function getSelectedLanguageLevel() {
            const selected = form.querySelector('input[name="languageLevel"]:checked');
            return selected ? selected.value : "";
        }

        function getBereichValue() {
            return String(bereichSelect.value || "").trim();
        }

        function formatFileSize(size) {
            if (size < 1024) {
                return `${size} B`;
            }
            if (size < 1024 * 1024) {
                return `${(size / 1024).toFixed(1)} KB`;
            }
            return `${(size / (1024 * 1024)).toFixed(1)} MB`;
        }

        function formatFilesSummary(files) {
            const totalSize = files.reduce((sum, file) => sum + file.size, 0);
            return `${files.length} file(s), ${formatFileSize(totalSize)} total`;
        }

        function validateFiles(files) {
            const oversizedFile = files.find((file) => file.size > MAX_FILE_SIZE_BYTES);
            if (oversizedFile) {
                return `${oversizedFile.name} is too large. Max ${formatFileSize(MAX_FILE_SIZE_BYTES)} per file.`;
            }

            const totalSize = files.reduce((sum, file) => sum + file.size, 0);
            if (totalSize > MAX_TOTAL_SIZE_BYTES) {
                return `Selected files are too large. Max ${formatFileSize(MAX_TOTAL_SIZE_BYTES)} total.`;
            }

            return "";
        }

        function createSubmissionId() {
            if (window.crypto && typeof window.crypto.randomUUID === "function") {
                return window.crypto.randomUUID();
            }
            return `submission-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        }

        function sanitizeFileName(fileName) {
            return String(fileName || "").replace(/[^a-zA-Z0-9._-]+/g, "-");
        }

        function withTimeout(promise, timeoutMs, message) {
            return new Promise((resolve, reject) => {
                const timer = window.setTimeout(() => {
                    const error = new Error(message);
                    error.code = "upload-timeout";
                    reject(error);
                }, timeoutMs);

                promise
                    .then((value) => {
                        window.clearTimeout(timer);
                        resolve(value);
                    })
                    .catch((error) => {
                        window.clearTimeout(timer);
                        reject(error);
                    });
            });
        }

        function humanizeFirebaseError(error) {
            switch (error?.code) {
                case "permission-denied":
                case "storage/unauthorized":
                    return "Firebase permissions are blocking the request.";
                case "storage/canceled":
                    return "The file upload was canceled.";
                case "storage/retry-limit-exceeded":
                    return "Firebase Storage stopped retrying.";
                case "storage/quota-exceeded":
                    return "The Firebase Storage quota has been exceeded.";
                case "unavailable":
                    return "Firebase is temporarily unavailable.";
                case "upload-timeout":
                    return "The upload took too long and timed out.";
                default:
                    return error?.message || "An unexpected Firebase error occurred.";
            }
        }

        function getStorageBucketCandidates(bucketName) {
            const normalized = String(bucketName || "").trim();
            const candidates = [];

            if (normalized) {
                candidates.push(normalized);
            }

            if (normalized.endsWith(".firebasestorage.app")) {
                candidates.push(normalized.replace(/\.firebasestorage\.app$/i, ".appspot.com"));
            }

            return Array.from(new Set(candidates.filter(Boolean)));
        }

        function refreshFileMeta() {
            const files = Array.from(fileInput.files || []);
            if (!files.length) {
                fileMeta.textContent = "Keine Datei ausgewaehlt";
                clearStatus();
                return;
            }

            const validationError = validateFiles(files);
            if (validationError) {
                fileMeta.textContent = validationError;
                showStatus(validationError, "error");
                return;
            }

            fileMeta.textContent = formatFilesSummary(files);
        }

        function renderBereichOptions(domains) {
            const normalizedDomains = Array.isArray(domains) ? domains : [];
            bereichSelect.innerHTML = "";

            const placeholder = document.createElement("option");
            placeholder.value = "";
            placeholder.textContent = normalizedDomains.length ? "Choose domain" : "No domains available";
            bereichSelect.appendChild(placeholder);

            normalizedDomains.forEach((domain) => {
                const option = document.createElement("option");
                option.value = String(domain || "");
                option.textContent = String(domain || "");
                bereichSelect.appendChild(option);
            });

            bereichSelect.disabled = !normalizedDomains.length;
        }

        async function ensureDomainsLoaded() {
            if (domainsLoaded) {
                return;
            }
            if (domainsRequest) {
                return domainsRequest;
            }

            showStatus("Loading domains from Ausbildungen...", "loading");
            bereichSelect.disabled = true;

            domainsRequest = fetchJson("/api/add/options")
                .then((payload) => {
                    const domains = Array.isArray(payload.ausbildung_domains)
                        ? payload.ausbildung_domains
                        : [];
                    renderBereichOptions(domains);
                    domainsLoaded = true;
                    if (domains.length) {
                        clearStatus();
                    } else {
                        showStatus("No domains found in Ausbildungen yet.", "error");
                    }
                })
                .catch((error) => {
                    renderBereichOptions([]);
                    showStatus(error.message || "Domain list could not be loaded.", "error");
                    throw error;
                })
                .finally(() => {
                    domainsRequest = null;
                });

            return domainsRequest;
        }

        async function getFirebaseClient() {
            if (firebaseClientRequest) {
                return firebaseClientRequest;
            }

            firebaseClientRequest = Promise.all([
                import("https://www.gstatic.com/firebasejs/12.7.0/firebase-app.js"),
                import("https://www.gstatic.com/firebasejs/12.7.0/firebase-firestore.js"),
                import("https://www.gstatic.com/firebasejs/12.7.0/firebase-storage.js"),
            ]).then(([firebaseApp, firestore, storageModule]) => {
                const app = firebaseApp.getApps().length
                    ? firebaseApp.getApp()
                    : firebaseApp.initializeApp(firebaseConfig);
                const db = firestore.getFirestore(app);
                const storageServices = getStorageBucketCandidates(firebaseConfig.storageBucket).map((bucketName) =>
                    storageModule.getStorage(app, `gs://${bucketName}`),
                );
                if (!storageServices.length) {
                    storageServices.push(storageModule.getStorage(app));
                }
                storageServices.forEach((storageService) => {
                    storageService.maxUploadRetryTime = 120000;
                    storageService.maxOperationRetryTime = 30000;
                });

                return {
                    db,
                    storageServices,
                    addDoc: firestore.addDoc,
                    collection: firestore.collection,
                    serverTimestamp: firestore.serverTimestamp,
                    ref: storageModule.ref,
                    uploadBytes: storageModule.uploadBytes,
                    getDownloadURL: storageModule.getDownloadURL,
                };
            });

            return firebaseClientRequest;
        }

        async function uploadFileToFirebase(file, submissionId, firebaseClient) {
            const safeName = sanitizeFileName(file.name);
            const storagePath = `applications/${submissionId}/${Date.now()}-${safeName}`;
            const metadata = file.type ? { contentType: file.type } : undefined;
            let lastError = null;

            for (const storageService of firebaseClient.storageServices || []) {
                try {
                    const storageRef = firebaseClient.ref(storageService, storagePath);

                    await withTimeout(
                        firebaseClient.uploadBytes(storageRef, file, metadata),
                        STORAGE_UPLOAD_TIMEOUT_MS,
                        "The file upload stayed pending for too long.",
                    );

                    const downloadURL = await withTimeout(
                        firebaseClient.getDownloadURL(storageRef),
                        STORAGE_DOWNLOAD_URL_TIMEOUT_MS,
                        "The file was uploaded, but no download URL was returned in time.",
                    );

                    return {
                        name: file.name,
                        size: file.size,
                        contentType: file.type || "",
                        storagePath,
                        downloadURL,
                    };
                } catch (error) {
                    lastError = error;
                }
            }

            throw lastError || new Error("The file upload failed.");
        }

        async function handleSubmission() {
            await ensureDomainsLoaded().catch(() => {});

            if (!form.reportValidity()) {
                showStatus("Please complete all required fields before submitting.", "error");
                return;
            }

            const languageLevel = getSelectedLanguageLevel();
            if (!languageLevel) {
                showStatus("Please select B1 or B2.", "error");
                return;
            }

            const bereich = getBereichValue();
            if (!bereich) {
                showStatus("Please choose a domain.", "error");
                return;
            }

            const files = Array.from(fileInput.files || []);
            const validationError = validateFiles(files);
            if (validationError) {
                showStatus(validationError, "error");
                return;
            }

            const firebaseClient = await getFirebaseClient();
            const submissionId = createSubmissionId();
            const payload = {
                submissionId,
                fullName: document.getElementById("add-fullName")?.value.trim() || "",
                email: document.getElementById("add-email")?.value.trim() || "",
                whatsapp: document.getElementById("add-whatsapp")?.value.trim() || "",
                bank: document.getElementById("add-bank")?.value.trim() || "",
                languageLevel,
                bereich,
                bewerbungen: document.getElementById("add-bewerbungen")?.value.trim() || "",
            };

            setSubmitting(true);

            try {
                const uploadedDocuments = [];
                let uploadError = null;

                for (let index = 0; index < files.length; index += 1) {
                    showStatus(`Uploading file ${index + 1} of ${files.length}...`, "loading");
                    try {
                        uploadedDocuments.push(
                            await uploadFileToFirebase(files[index], submissionId, firebaseClient),
                        );
                    } catch (error) {
                        uploadError = {
                            code: error?.code || "unknown",
                            message: error?.message || "Unknown Firebase upload error",
                        };
                        break;
                    }
                }

                showStatus("Saving...", "loading");

                const docRef = await firebaseClient.addDoc(
                    firebaseClient.collection(firebaseClient.db, "applications"),
                    {
                        ...payload,
                        documents: uploadedDocuments,
                        createdAt: firebaseClient.serverTimestamp(),
                        uploadStatus: uploadError ? "files-failed" : "completed",
                        uploadError,
                    },
                );

                form.reset();
                refreshFileMeta();

                if (uploadError) {
                    showStatus(
                        `Saved form data to Firebase. File upload failed: ${humanizeFirebaseError(uploadError)} Record ID: ${docRef.id}`,
                        "error",
                    );
                    return;
                }

                showStatus("Saved to Firebase successfully.", "success");
            } catch (error) {
                console.error("Firebase save failed", error);
                showStatus(`Firebase save failed. ${humanizeFirebaseError(error)}`, "error");
            } finally {
                setSubmitting(false);
            }
        }

        function bindEvents() {
            fileInput.addEventListener("change", refreshFileMeta);
            form.addEventListener("submit", async (event) => {
                event.preventDefault();
                await handleSubmission();
            });
        }

        return {
            show() {
                if (!initialized) {
                    initialized = true;
                    bindEvents();
                    refreshFileMeta();
                }
                ensureDomainsLoaded().catch(() => {});
            },
            hide() {},
        };
    };

    window.SPASections = sections;
})();

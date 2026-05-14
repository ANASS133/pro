(function () {
    const sections = window.SPASections || {};

    function createAnschreibenSection(config) {
        const prefix = String(config?.prefix || "").trim();
        const root = document.getElementById(`${prefix}-section`);
        if (!root || !prefix) {
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
        const escapeHtml = typeof utils.escapeHtml === "function"
            ? utils.escapeHtml
            : function fallbackEscapeHtml(value) {
                return String(value ?? "")
                    .replace(/&/g, "&amp;")
                    .replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;")
                    .replace(/"/g, "&quot;")
                    .replace(/'/g, "&#39;");
            };

        const API_BASE = "/api";
        const defaultTemplate = "";
        const defaultFilenameFormatLabel = String(config?.defaultFilenameFormatLabel || "Automatisch aus Firma");
        const dataSourceMode = String(config?.dataSourceMode || "export-selector");
        const transferEnabled = Boolean(config?.transferEnabled);
        const defaultLayout = {
            font_size: 11,
            line_height: 5,
            margin_top: 20,
            margin_left: 20,
            margin_right: 20,
            margin_bottom: 20,
            text_width: 170,
            text_height: 257,
        };

        const state = {
            sessionId: null,
            editCampaignId: null,
            columns: [],
            previewRows: [],
            designPdfName: null,
            transferReadyCount: 0,
            templates: [defaultTemplate],
            activeTemplateIndex: 0,
            filenameFormat: "{{Unternehmen}}",
        };

        function byId(name) {
            return document.getElementById(`${prefix}-${name}`);
        }

        const els = {
            error: byId("error"),
            exportSelect: byId("exportSelect"),
            loadExportBtn: byId("loadExportBtn"),
            sourcePrompt: byId("sourcePrompt"),
            fileInfo: byId("fileInfo"),
            fileName: byId("fileName"),
            rowCount: byId("rowCount"),
            applicationSummary: byId("applicationSummary"),
            summaryName: byId("summaryName"),
            summaryEmail: byId("summaryEmail"),
            summaryWhatsapp: byId("summaryWhatsapp"),
            summaryBereich: byId("summaryBereich"),
            summaryBewerbungen: byId("summaryBewerbungen"),
            summaryDocuments: byId("summaryDocuments"),
            columnList: byId("columnList"),
            dataPreview: byId("dataPreview"),
            previewTable: byId("previewTable"),
            designDropZone: byId("designDropZone"),
            designFileInput: byId("designFileInput"),
            designFileInfo: byId("designFileInfo"),
            designFileName: byId("designFileName"),
            placeholderTags: byId("placeholderTags"),
            templateList: byId("templateList"),
            addTemplateBtn: byId("addTemplateBtn"),
            deleteTemplateBtn: byId("deleteTemplateBtn"),
            formatToolbar: byId("formatToolbar"),
            templateEditor: byId("templateEditor"),
            saveTemplateBtn: byId("saveTemplateBtn"),
            resetTemplateBtn: byId("resetTemplateBtn"),
            validationResult: byId("validationResult"),
            filenameFormat: byId("filenameFormat"),
            fontSizeInput: byId("fontSizeInput"),
            lineHeightInput: byId("lineHeightInput"),
            marginTopInput: byId("marginTopInput"),
            marginLeftInput: byId("marginLeftInput"),
            marginRightInput: byId("marginRightInput"),
            marginBottomInput: byId("marginBottomInput"),
            textWidthInput: byId("textWidthInput"),
            textHeightInput: byId("textHeightInput"),
            resetLayoutBtn: byId("resetLayoutBtn"),
            previewBtn: byId("previewBtn"),
            generateBtn: byId("generateBtn"),
            toEmailBtn: byId("toEmailBtn"),
            progressArea: byId("progressArea"),
            progressFill: byId("progressFill"),
            progressText: byId("progressText"),
            previewModal: byId("previewModal"),
            pdfPreview: byId("pdfPreview"),
            closeModalBtn: byId("closeModalBtn"),
            closeFooterBtn: byId("closeFooterBtn"),
            toast: byId("toast"),
            pdfContainer: byId("pdfContainer"),
            pdfIframe: byId("pdfIframe"),
            extractPageInput: byId("extractPageInput"),
            extractBtn: byId("extractBtn"),
            extractStatus: byId("extractStatus"),
            aiTemplatizeBtn: byId("aiTemplatizeBtn"),
            aiTemplatizeStatus: byId("aiTemplatizeStatus"),
            documentList: byId("documentList"),
            documentViewerTitle: byId("documentViewerTitle"),
            documentOpenLink: byId("documentOpenLink"),
        };

        const requiredKeys = [
            "templateEditor",
            "previewBtn",
            "generateBtn",
            "progressArea",
            "previewModal",
            "pdfPreview",
            "designDropZone",
            "designFileInput",
            "designFileInfo",
            "designFileName",
            "placeholderTags",
            "templateList",
            "addTemplateBtn",
            "deleteTemplateBtn",
            "formatToolbar",
            "saveTemplateBtn",
            "resetTemplateBtn",
            "validationResult",
            "filenameFormat",
            "fontSizeInput",
            "lineHeightInput",
            "marginTopInput",
            "marginLeftInput",
            "marginRightInput",
            "marginBottomInput",
            "textWidthInput",
            "textHeightInput",
            "resetLayoutBtn",
            "progressFill",
            "progressText",
            "closeModalBtn",
            "closeFooterBtn",
            "toast",
            "columnList",
        ];

        if (requiredKeys.some((key) => !els[key])) {
            return {
                show() {},
                hide() {},
            };
        }

        if (!els.exportSelect || !els.loadExportBtn) {
            return {
                show() {},
                hide() {},
            };
        }

        if (dataSourceMode === "firebase-application" && !els.sourcePrompt) {
            return {
                show() {},
                hide() {},
            };
        }

        const applicationStoragePrefix = "create-anschreibens:application:";
        const lastApplicationKey = "create-anschreibens:last-application";
        const firebaseApplicationStoragePrefix = "create-anschreibens:firebase-application:";
        const firebaseLastApplicationKey = "create-anschreibens:last-firebase-application";
        const noDataMessage = dataSourceMode === "firebase-application"
            ? "Bitte zuerst eine Bewerbung laden"
            : "Bitte zuerst Exportdaten laden";

        let initialized = false;
        let toastTimer = null;
        let previewObjectUrl = "";
        let lastBootstrapKey = "";
        let exportOptionsLoaded = false;
        let exportOptionsRequest = null;
        let firebaseBereich = "";

        function ensureTemplateState() {
            if (!Array.isArray(state.templates) || !state.templates.length) {
                state.templates = [defaultTemplate];
            }
            if (
                state.activeTemplateIndex < 0
                || state.activeTemplateIndex >= state.templates.length
            ) {
                state.activeTemplateIndex = 0;
            }
        }

        function toNumber(value, fallback) {
            const n = Number.parseFloat(value);
            return Number.isFinite(n) ? n : fallback;
        }

        function clampPercent(value) {
            const parsed = Number(value || 0);
            if (!Number.isFinite(parsed)) {
                return 0;
            }
            return Math.max(0, Math.min(100, parsed));
        }

        function clearInlineError() {
            if (!els.error) {
                return;
            }
            els.error.hidden = true;
            els.error.textContent = "";
        }

        function showInlineError(message) {
            if (!els.error) {
                return;
            }
            els.error.textContent = String(message || "").trim() || "Unbekannter Fehler.";
            els.error.hidden = false;
        }

        function showToast(message, timeout) {
            const duration = Number(timeout || 2600);
            if (toastTimer) {
                window.clearTimeout(toastTimer);
            }
            els.toast.textContent = String(message || "").trim();
            els.toast.hidden = false;
            toastTimer = window.setTimeout(() => {
                els.toast.hidden = true;
            }, duration);
        }

        function showProgress(message, percent) {
            els.progressArea.hidden = false;
            els.progressText.textContent = String(message || "");
            els.progressFill.style.width = `${clampPercent(percent)}%`;
        }

        function hideProgress() {
            els.progressArea.hidden = true;
            els.progressText.textContent = "Generiere PDFs...";
            els.progressFill.style.width = "0%";
        }

        function setValidation(type, message) {
            els.validationResult.className = "anschreiben-validation-result";
            if (type === "ok") {
                els.validationResult.classList.add("is-ok");
            } else if (type === "warn") {
                els.validationResult.classList.add("is-warn");
            }
            els.validationResult.textContent = String(message || "");
            els.validationResult.hidden = false;
        }

        function clearValidation() {
            els.validationResult.className = "anschreiben-validation-result";
            els.validationResult.textContent = "";
            els.validationResult.hidden = true;
        }

        function syncFilenameFormatDisplay(filenameFormat) {
            const raw = String(filenameFormat || "{{Unternehmen}}").trim() || "{{Unternehmen}}";
            state.filenameFormat = raw;
            els.filenameFormat.value = raw === "{{Unternehmen}}" ? defaultFilenameFormatLabel : raw;
        }

        function setLayoutInputs(layout) {
            const normalizedLayout = layout || {};
            els.fontSizeInput.value = normalizedLayout.font_size ?? defaultLayout.font_size;
            els.lineHeightInput.value = normalizedLayout.line_height ?? defaultLayout.line_height;
            els.marginTopInput.value = normalizedLayout.margin_top ?? defaultLayout.margin_top;
            els.marginLeftInput.value = normalizedLayout.margin_left ?? defaultLayout.margin_left;
            els.marginRightInput.value = normalizedLayout.margin_right ?? defaultLayout.margin_right;
            els.marginBottomInput.value = normalizedLayout.margin_bottom ?? defaultLayout.margin_bottom;
            els.textWidthInput.value = normalizedLayout.text_width ?? defaultLayout.text_width;
            els.textHeightInput.value = normalizedLayout.text_height ?? defaultLayout.text_height;
        }

        function getLayoutOptions() {
            return {
                font_size: toNumber(els.fontSizeInput.value, defaultLayout.font_size),
                line_height: toNumber(els.lineHeightInput.value, defaultLayout.line_height),
                margin_top: toNumber(els.marginTopInput.value, defaultLayout.margin_top),
                margin_left: toNumber(els.marginLeftInput.value, defaultLayout.margin_left),
                margin_right: toNumber(els.marginRightInput.value, defaultLayout.margin_right),
                margin_bottom: toNumber(els.marginBottomInput.value, defaultLayout.margin_bottom),
                text_width: toNumber(els.textWidthInput.value, defaultLayout.text_width),
                text_height: toNumber(els.textHeightInput.value, defaultLayout.text_height),
            };
        }

        function persistActiveTemplateValue() {
            ensureTemplateState();
            state.templates[state.activeTemplateIndex] = els.templateEditor.value || "";
        }

        function renderTemplateList() {
            ensureTemplateState();
            els.templateList.innerHTML = "";

            state.templates.forEach((template, index) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = `anschreiben-template-chip${index === state.activeTemplateIndex ? " is-active" : ""}${template.trim() ? "" : " is-empty"}`;
                button.textContent = `Variante ${index + 1}${template.trim() ? "" : " (leer)"}`;
                button.addEventListener("click", () => switchTemplate(index));
                els.templateList.appendChild(button);
            });

            els.deleteTemplateBtn.disabled = state.templates.length <= 1;
        }

        function loadActiveTemplateIntoEditor() {
            ensureTemplateState();
            els.templateEditor.value = state.templates[state.activeTemplateIndex] || "";
            renderTemplateList();
        }

        function switchTemplate(index) {
            persistActiveTemplateValue();
            state.activeTemplateIndex = index;
            loadActiveTemplateIntoEditor();
        }

        function addTemplate() {
            persistActiveTemplateValue();
            state.templates.push("");
            state.activeTemplateIndex = state.templates.length - 1;
            loadActiveTemplateIntoEditor();
        }

        function deleteActiveTemplate() {
            ensureTemplateState();
            if (state.templates.length <= 1) {
                state.templates[0] = "";
                state.activeTemplateIndex = 0;
            } else {
                state.templates.splice(state.activeTemplateIndex, 1);
                state.activeTemplateIndex = Math.max(0, state.activeTemplateIndex - 1);
            }
            loadActiveTemplateIntoEditor();
        }

        function renderColumns(columns) {
            els.columnList.innerHTML = "";
            columns.forEach((column) => {
                const tag = document.createElement("span");
                tag.className = "anschreiben-column-tag";
                tag.textContent = column;
                els.columnList.appendChild(tag);
            });

            const dynamicPlaceholders = columns.map((column) => `{{${column}}}`);
            const builtinPlaceholders = ["{{heutigenDatum}}"];
            els.placeholderTags.textContent = [...dynamicPlaceholders, ...builtinPlaceholders].join(" ");
        }

        function renderPreview(rows) {
            if (!els.previewTable || !els.dataPreview) return;
            
            if (!Array.isArray(rows) || !rows.length) {
                els.previewTable.innerHTML = "";
                els.dataPreview.hidden = true;
                return;
            }

            const headers = Object.keys(rows[0] || {});
            const thead = `<thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead>`;
            const tbody = `<tbody>${rows
                .map((row) => {
                    const cells = headers.map((header) => `<td>${escapeHtml(row?.[header] ?? "")}</td>`).join("");
                    return `<tr>${cells}</tr>`;
                })
                .join("")}</tbody>`;

            els.previewTable.innerHTML = `<table>${thead}${tbody}</table>`;
            els.dataPreview.hidden = false;
        }

        function setDesignFileState(filename) {
            state.designPdfName = filename ? String(filename).trim() : "";
            if (state.designPdfName) {
                els.designFileName.textContent = state.designPdfName;
                els.designFileInfo.hidden = false;
            } else {
                els.designFileName.textContent = "";
                els.designFileInfo.hidden = true;
            }
        }

        function setSourcePrompt(message) {
            if (!els.sourcePrompt) {
                return;
            }
            els.sourcePrompt.textContent = String(message || "");
            els.sourcePrompt.hidden = !String(message || "").trim();
        }

        function getApplicationIdFromUrl() {
            const params = new URLSearchParams(window.location.search);
            return params.get("application_id") || "";
        }

        function normalizeDocumentItem(doc) {
            if (!doc) return null;
            const url = doc.downloadURL || doc.url || doc.href || "";
            if (!url) return null;
            const name = doc.name || doc.filename || doc.fileName || "Unbenanntes Dokument";
            const type = doc.contentType || doc.type || "";
            return { url, name, type };
        }

        function getPreviewUrlForDocument(url, type, name) {
            const t = String(type || "").toLowerCase();
            const n = String(name || "").toLowerCase();
            if (t.includes("pdf") || n.endsWith(".pdf") || t.includes("image") || n.match(/\.(jpg|jpeg|png|gif)$/i)) {
                return url;
            }
            return `https://docs.google.com/viewer?url=${encodeURIComponent(url)}&embedded=true`;
        }

        let activeDocumentIndex = 0;
        let currentDocuments = [];

        function renderApplicationDocuments(documents) {
            currentDocuments = [];
            if (Array.isArray(documents)) {
                currentDocuments = documents.map(normalizeDocumentItem).filter(Boolean);
            }
            if (!els.pdfContainer || !els.pdfIframe) return;

            if (currentDocuments.length === 0) {
                els.pdfContainer.hidden = true;
                if (els.sourcePrompt) els.sourcePrompt.hidden = false;
                return;
            }

            if (els.sourcePrompt) els.sourcePrompt.hidden = true;
            els.pdfContainer.hidden = false;
            
            // Set first doc URL for the extraction script logic
            els.pdfContainer.dataset.pdfUrl = currentDocuments[0].url;

            if (els.documentList) {
                els.documentList.innerHTML = "";
                currentDocuments.forEach((doc, idx) => {
                    const btn = document.createElement("button");
                    btn.type = "button";
                    btn.className = `anschreiben-document-pill ${idx === activeDocumentIndex ? "is-active" : ""}`;
                    btn.textContent = doc.name;
                    btn.title = doc.name;
                    btn.addEventListener("click", () => selectDocumentForViewer(idx));
                    els.documentList.appendChild(btn);
                });
            }
            
            if (activeDocumentIndex >= currentDocuments.length) {
                activeDocumentIndex = 0;
            }
            
            selectDocumentForViewer(activeDocumentIndex);
        }

        function selectDocumentForViewer(index) {
            if (!currentDocuments[index]) return;
            activeDocumentIndex = index;
            const doc = currentDocuments[index];
            
            if (els.documentViewerTitle) {
                els.documentViewerTitle.textContent = doc.name;
            }
            
            if (els.documentOpenLink) {
                els.documentOpenLink.href = doc.url;
            }
            
            if (els.pdfIframe) {
                els.pdfIframe.src = getPreviewUrlForDocument(doc.url, doc.type, doc.name);
                els.pdfContainer.dataset.pdfUrl = doc.url; // Update for extraction
            }
            
            if (els.documentList) {
                Array.from(els.documentList.children).forEach((btn, i) => {
                    btn.classList.toggle("is-active", i === index);
                });
            }
        }

        function renderCachedApplicationDocuments() {
            const urlAppId = getApplicationIdFromUrl();
            let appData = null;

            if (urlAppId) {
                const stored = window.sessionStorage.getItem(applicationStoragePrefix + urlAppId)
                    || window.sessionStorage.getItem(firebaseApplicationStoragePrefix + urlAppId);
                if (stored) {
                    try {
                        appData = JSON.parse(stored);
                    } catch (e) {}
                }
            }
            
            if (!appData) {
                const lastSelectedId = window.sessionStorage.getItem(lastApplicationKey)
                    || window.sessionStorage.getItem(firebaseLastApplicationKey);
                if (lastSelectedId) {
                    const stored = window.sessionStorage.getItem(applicationStoragePrefix + lastSelectedId)
                        || window.sessionStorage.getItem(firebaseApplicationStoragePrefix + lastSelectedId);
                    if (stored) {
                        try {
                            appData = JSON.parse(stored);
                            const url = new URL(window.location);
                            url.searchParams.set("application_id", lastSelectedId);
                            window.history.replaceState({}, "", url);
                        } catch (e) {}
                    }
                }
            }

            if (appData) {
                const docs = appData.documents || (appData.application_data && appData.application_data.documents) || [];
                if (docs.length > 0) {
                    renderApplicationDocuments(docs);
                }
            }
        }

        function renderApplicationSummary(summary) {
            if (!els.applicationSummary) {
                return;
            }

            const normalized = summary || {};
            const hasSummary = Boolean(
                normalized.full_name
                || normalized.email
                || normalized.whatsapp
                || normalized.bereich
                || normalized.bewerbungen
                || normalized.document_count,
            );

            els.applicationSummary.hidden = !hasSummary;
            if (!hasSummary) {
                return;
            }

            if (els.summaryName) {
                els.summaryName.textContent = String(normalized.full_name || "k. A.");
            }
            if (els.summaryEmail) {
                els.summaryEmail.textContent = String(normalized.email || "k. A.");
            }
            if (els.summaryWhatsapp) {
                els.summaryWhatsapp.textContent = String(normalized.whatsapp || "k. A.");
            }
            if (els.summaryBereich) {
                els.summaryBereich.textContent = String(normalized.bereich || "k. A.");
            }
            if (els.summaryBewerbungen) {
                els.summaryBewerbungen.textContent = String(normalized.bewerbungen || "k. A.");
            }
            if (els.summaryDocuments) {
                els.summaryDocuments.textContent = String(normalized.document_count ?? 0);
            }
        }

        async function clearPdfSession(sessionId, keepalive) {
            const normalizedSessionId = String(sessionId || "").trim();
            if (!normalizedSessionId) {
                return;
            }
            const options = { method: "DELETE" };
            if (keepalive) {
                options.keepalive = true;
            }
            try {
                await fetch(`${API_BASE}/clear-session/${encodeURIComponent(normalizedSessionId)}`, options);
            } catch (_error) {
                // Best effort cleanup only.
            }
        }

        function adoptSession(newSessionId) {
            const previousSessionId = String(state.sessionId || "").trim();
            const normalizedNewSessionId = String(newSessionId || "").trim();
            if (previousSessionId && normalizedNewSessionId && previousSessionId !== normalizedNewSessionId) {
                clearPdfSession(previousSessionId, false).catch(() => {});
            }
            state.sessionId = normalizedNewSessionId || null;
        }

        function applyLoadedSession(data, displayName) {
            adoptSession(data.session_id);
            state.editCampaignId = data.edit_campaign_id || null;
            state.columns = Array.isArray(data.columns) ? data.columns : [];
            state.previewRows = Array.isArray(data.preview) ? data.preview : [];
            state.transferReadyCount = 0;
            state.templates = Array.isArray(data.templates) && data.templates.length
                ? data.templates.map((template) => String(template || ""))
                : [defaultTemplate];
            state.activeTemplateIndex = Number(data.active_template_index || 0);

            syncFilenameFormatDisplay(data.filename_format || "{{Unternehmen}}");
            setLayoutInputs(data.layout_options || defaultLayout);
            setDesignFileState(data.design_pdf_name || "");

            if (els.fileName) {
                els.fileName.textContent = String(displayName || "");
            }
            if (els.rowCount) {
                els.rowCount.textContent = data.row_count || state.previewRows.length || 0;
            }
            if (els.fileInfo) {
                els.fileInfo.hidden = false;
            }
            if (els.toEmailBtn) {
                els.toEmailBtn.hidden = true;
            }

            if (data.application_summary) {
                renderApplicationSummary(data.application_summary);
                setSourcePrompt("");
            } else if (dataSourceMode === "firebase-application") {
                renderApplicationSummary({});
                setSourcePrompt("");
            }
                
            let docs = [];
            if (data.application_data && Array.isArray(data.application_data.documents)) {
                docs = data.application_data.documents;
            } else if (data.application_summary && Array.isArray(data.application_summary.documents)) {
                docs = data.application_summary.documents;
            }
            
            if (docs.length > 0) {
                renderApplicationDocuments(docs);
            } else {
                renderCachedApplicationDocuments();
            }

            renderColumns(state.columns);
            renderPreview(state.previewRows);
            loadActiveTemplateIntoEditor();
            clearValidation();
            clearInlineError();
        }

        function buildAutoloadDisplayName(source) {
            if (source === "manual") {
                return "Gesammelte Jobs (manuelle Extraktion)";
            }
            if (source === "auto") {
                return "Gesammelte Jobs (Auto-Extraktion)";
            }
            return "Gesammelte Jobs";
        }

        async function uploadDesignPdf(file) {
            if (!state.sessionId) {
                showToast(noDataMessage);
                return;
            }

            const formData = new FormData();
            formData.append("file", file);
            formData.append("session_id", state.sessionId);

            clearInlineError();
            showProgress("Design-PDF wird hochgeladen...", 30);

            const data = await fetchJson(`${API_BASE}/upload-design-pdf`, {
                method: "POST",
                body: formData,
            });

            setDesignFileState(file.name || data.filename || "");
            showProgress("Design-PDF gespeichert", 100);
            window.setTimeout(hideProgress, 500);
            showToast("Design-PDF erfolgreich hochgeladen");
        }

        async function saveTemplate(options) {
            const configOptions = options || {};
            if (!state.sessionId) {
                if (!configOptions.silent) {
                    showToast(noDataMessage);
                }
                return;
            }

            persistActiveTemplateValue();
            clearInlineError();

            const data = await fetchJson(`${API_BASE}/save-template`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    session_id: state.sessionId,
                    templates: state.templates,
                    active_template_index: state.activeTemplateIndex,
                }),
            });

            if (Array.isArray(data.missing_placeholders) && data.missing_placeholders.length) {
                setValidation("warn", `Unbekannte Platzhalter: ${data.missing_placeholders.join(", ")}`);
            } else {
                setValidation("ok", "Vorlage gespeichert. Alle Platzhalter sind gültig.");
            }

            if (!configOptions.silent) {
                showToast(`Vorlagen gespeichert (${data.template_count || state.templates.length})`);
            }
        }

        async function previewPdf() {
            if (!state.sessionId) {
                showToast(noDataMessage);
                return;
            }

            await saveTemplate({ silent: true });

            clearInlineError();
            showProgress("Vorschau wird erstellt...", 45);

            const response = await fetch(`${API_BASE}/preview-pdf`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    session_id: state.sessionId,
                    row_index: 0,
                    layout_options: getLayoutOptions(),
                }),
            });

            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(payload.error || "Vorschau fehlgeschlagen");
            }

            if (previewObjectUrl) {
                URL.revokeObjectURL(previewObjectUrl);
                previewObjectUrl = "";
            }

            const blob = await response.blob();
            previewObjectUrl = URL.createObjectURL(blob);
            els.pdfPreview.src = previewObjectUrl;
            els.previewModal.hidden = false;

            showProgress("Vorschau bereit", 100);
            window.setTimeout(hideProgress, 500);
        }

        async function generatePdfs() {
            if (!state.sessionId) {
                showToast(noDataMessage);
                return;
            }

            await saveTemplate({ silent: true });

            clearInlineError();
            showProgress("PDFs werden generiert...", 35);

            const data = await fetchJson(`${API_BASE}/generate-pdfs`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    session_id: state.sessionId,
                    layout_options: getLayoutOptions(),
                }),
            });

            showProgress("PDFs gespeichert", 100);
            window.setTimeout(hideProgress, 500);

            const skipped = Number(data.skipped || 0);
            if (state.editCampaignId) {
                showToast(
                    skipped > 0
                        ? `Kampagne aktualisiert: ${data.count || 0} PDFs, ${skipped} Zeilen übersprungen`
                        : "Anschreiben für offene Empfänger aktualisiert",
                );
            } else if (skipped > 0) {
                showToast(`Fertig: ${data.count || 0} PDFs, ${skipped} Zeilen übersprungen`);
            } else {
                showToast(`Fertig: ${data.count || 0} PDFs in ${data.output_folder || "Projektordner"}`);
            }

            state.transferReadyCount = Number(data.transfer_ready || 0);
            if (
                transferEnabled
                && !state.editCampaignId
                && state.transferReadyCount > 0
                && els.toEmailBtn
            ) {
                els.toEmailBtn.hidden = false;
            }
        }

        async function transferToEmailSender() {
            if (!state.sessionId) {
                showToast(noDataMessage);
                return;
            }

            clearInlineError();
            showProgress("Transfer zu Email Sender wird vorbereitet...", 40);

            const data = await fetchJson(`${API_BASE}/prepare-email-transfer`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: state.sessionId }),
            });

            showProgress("Transfer bereit", 100);
            window.setTimeout(hideProgress, 300);
            window.location.href = data.redirect_url || "/send-emails";
        }

        function closePreview() {
            els.previewModal.hidden = true;
            els.pdfPreview.src = "";
            if (previewObjectUrl) {
                URL.revokeObjectURL(previewObjectUrl);
                previewObjectUrl = "";
            }
        }

        async function aiTemplatize() {
            const text = (els.templateEditor.value || "").trim();
            if (!text) {
                showToast("Kein Text zum Verarbeiten vorhanden.");
                return;
            }

            const placeholders = [...state.columns];
            if (!placeholders.includes("heutigenDatum")) {
                placeholders.push("heutigenDatum");
            }
            if (!placeholders.length) {
                showToast("Keine Platzhalter verfügbar. Bitte zuerst Daten laden.");
                return;
            }

            if (els.aiTemplatizeBtn) {
                els.aiTemplatizeBtn.disabled = true;
            }
            if (els.aiTemplatizeStatus) {
                els.aiTemplatizeStatus.hidden = false;
                els.aiTemplatizeStatus.textContent = "KI verarbeitet den Text...";
            }
            clearInlineError();
            showProgress("KI analysiert den Text und fuegt Platzhalter ein...", 50);

            try {
                const data = await fetchJson(`${API_BASE}/ai-templatize`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ text, placeholders }),
                });

                if (data.text) {
                    els.templateEditor.value = data.text;
                    persistActiveTemplateValue();
                    renderTemplateList();
                    showProgress("KI-Vorlage erstellt", 100);
                    window.setTimeout(hideProgress, 600);
                    showToast("KI-Vorlage erfolgreich erstellt");
                } else {
                    hideProgress();
                    showToast("KI hat keinen Text zurueckgegeben.");
                }
            } catch (error) {
                hideProgress();
                showInlineError(error.message || "KI-Verarbeitung fehlgeschlagen.");
                showToast(error.message || "KI-Verarbeitung fehlgeschlagen.");
            } finally {
                if (els.aiTemplatizeBtn) {
                    els.aiTemplatizeBtn.disabled = false;
                }
                if (els.aiTemplatizeStatus) {
                    els.aiTemplatizeStatus.hidden = true;
                }
            }
        }

        function wrapSelection(prefixValue, suffixValue) {
            const textarea = els.templateEditor;
            const start = textarea.selectionStart ?? 0;
            const end = textarea.selectionEnd ?? 0;
            const selectedText = textarea.value.slice(start, end);
            const replacement = `${prefixValue}${selectedText}${suffixValue}`;

            textarea.setRangeText(replacement, start, end, "end");
            textarea.focus();

            const selectionStart = start + prefixValue.length;
            const selectionEnd = selectionStart + selectedText.length;
            textarea.setSelectionRange(selectionStart, selectionEnd);
        }

        function handleDesignFiles(fileList) {
            const file = fileList?.[0];
            if (!file) {
                return;
            }

            if (!/\.pdf$/i.test(file.name)) {
                showToast("Bitte eine PDF-Datei auswaehlen (.pdf)");
                return;
            }

            uploadDesignPdf(file).catch((error) => {
                hideProgress();
                showInlineError(error.message || "Design-PDF Upload fehlgeschlagen");
                showToast(error.message || "Design-PDF Upload fehlgeschlagen");
            });
        }

        function bindDropZone(dropZone, fileInput, handler) {
            dropZone.addEventListener("click", () => fileInput.click());
            fileInput.addEventListener("change", (event) => handler(event.target.files));

            ["dragenter", "dragover"].forEach((eventName) => {
                dropZone.addEventListener(eventName, (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    dropZone.classList.add("is-dragover");
                });
            });

            ["dragleave", "drop"].forEach((eventName) => {
                dropZone.addEventListener(eventName, (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    dropZone.classList.remove("is-dragover");
                });
            });

            dropZone.addEventListener("drop", (event) => handler(event.dataTransfer?.files));
        }

        function updateSectionQuery(params) {
            const url = new URL(window.location.href);
            url.search = params.toString();
            window.history.replaceState({}, "", `${url.pathname}${url.search}`);
        }

        function renderExportOptions(files) {
            const items = Array.isArray(files) ? files : [];
            const currentValue = String(els.exportSelect.value || "").trim();
            const params = new URLSearchParams(window.location.search);
            const queryValue = String(params.get("filename") || "").trim();
            const targetValue = currentValue || queryValue;

            els.exportSelect.innerHTML = "";

            const placeholder = document.createElement("option");
            placeholder.value = "";
            placeholder.textContent = items.length
                ? "Bitte Domain waehlen"
                : "Keine Exportdateien gefunden";
            els.exportSelect.appendChild(placeholder);

            items.forEach((item) => {
                const option = document.createElement("option");
                const filename = String(item?.filename || "").trim();
                const rowCountDisplay = String(item?.row_count_display ?? "k. A.");
                const modifiedAt = String(item?.modified_at || "").trim();
                const domainName = String(item?.domain_name || filename).trim() || filename;

                option.value = filename;
                option.textContent = modifiedAt
                    ? `${domainName} (${rowCountDisplay} Zeilen, ${modifiedAt})`
                    : `${domainName} (${rowCountDisplay} Zeilen)`;
                els.exportSelect.appendChild(option);
            });

            if (targetValue && items.some((item) => String(item?.filename || "").trim() === targetValue)) {
                els.exportSelect.value = targetValue;
            }

            els.exportSelect.disabled = !items.length;
            els.loadExportBtn.disabled = !String(els.exportSelect.value || "").trim();
        }

        async function ensureExportOptionsLoaded(force) {
            if (!els.exportSelect || !els.loadExportBtn) {
                return [];
            }
            if (exportOptionsLoaded && !force) {
                return [];
            }
            if (exportOptionsRequest) {
                return exportOptionsRequest;
            }

            exportOptionsRequest = fetchJson(`${API_BASE}/create-anschreibens/exports`)
                .then((payload) => {
                    const files = Array.isArray(payload.files) ? payload.files : [];
                    renderExportOptions(files);
                    exportOptionsLoaded = true;
                    return files;
                })
                .catch((error) => {
                    renderExportOptions([]);
                    throw error;
                })
                .finally(() => {
                    exportOptionsRequest = null;
                });

            return exportOptionsRequest;
        }

        async function loadExportFilename(filename, updateQuery) {
            const normalizedFilename = String(filename || "").trim();
            if (!normalizedFilename) {
                showToast("Bitte zuerst eine Domain waehlen");
                return;
            }

            clearInlineError();
            showProgress("Exportdaten werden geladen...", 25);

            const urlParams = new URLSearchParams(window.location.search);
            const applicationId = urlParams.get("application_id") || "";
            const cachedApplication = getCachedApplication(applicationId);

            let payload;
            if (applicationId && cachedApplication) {
                payload = await fetchJson(`${API_BASE}/create-anschreibens/application-bootstrap`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        filename: normalizedFilename,
                        application_id: applicationId,
                        application: cachedApplication,
                        source_label: cachedApplication.source_label || "Supabase",
                    }),
                });
            } else {
                let url = `${API_BASE}/create-anschreibens/bootstrap?filename=${encodeURIComponent(normalizedFilename)}`;
                if (applicationId) {
                    url += `&application_id=${encodeURIComponent(applicationId)}`;
                }
                payload = await fetchJson(url);
            }
            if (!payload.session) {
                hideProgress();
                return;
            }

            applyLoadedSession(
                payload.session,
                payload.session.display_name || payload.session.filename || normalizedFilename,
            );
            if (els.exportSelect) {
                els.exportSelect.value = normalizedFilename;
                els.loadExportBtn.disabled = false;
            }
            if (updateQuery) {
                const params = new URLSearchParams();
                params.set("filename", normalizedFilename);
                if (applicationId) {
                    params.set("application_id", applicationId);
                }
                updateSectionQuery(params);
            }
            showProgress("Exportdaten geladen", 100);
            window.setTimeout(hideProgress, 600);
            showToast("Exportdaten wurden geladen");
        }

        function getCreateBootstrapQueryInfo() {
            const params = new URLSearchParams(window.location.search);
            const editCampaignId = String(params.get("edit_campaign") || "").trim();
            const autoloadSource = String(params.get("autoload") || "").trim();
            const filename = String(params.get("filename") || "").trim();
            const applicationId = String(params.get("application_id") || "").trim();
            const query = new URLSearchParams();

            if (editCampaignId) {
                query.set("edit_campaign", editCampaignId);
            } else if (autoloadSource) {
                query.set("autoload", autoloadSource);
            } else if (filename) {
                query.set("filename", filename);
            }

            if (applicationId) {
                query.set("application_id", applicationId);
            }

            return {
                key: query.toString(),
                query: query.toString(),
                editCampaignId,
                autoloadSource,
                filename,
                applicationId,
                application: getCachedApplication(applicationId),
            };
        }

        async function bootstrapCreateFromUrl() {
            const bootstrap = getCreateBootstrapQueryInfo();
            if (!bootstrap.key || bootstrap.key === lastBootstrapKey) {
                return;
            }

            lastBootstrapKey = bootstrap.key;
            clearInlineError();
            showProgress("Anschreiben-Daten werden geladen...", 25);

            try {
                let payload;
                if (bootstrap.applicationId && bootstrap.application && !bootstrap.editCampaignId && !bootstrap.autoloadSource) {
                    payload = await fetchJson(`${API_BASE}/create-anschreibens/application-bootstrap`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            filename: bootstrap.filename || "",
                            application_id: bootstrap.applicationId,
                            application: bootstrap.application,
                            source_label: bootstrap.application.source_label || "Supabase",
                        }),
                    });
                } else {
                    payload = await fetchJson(`${API_BASE}/create-anschreibens/bootstrap?${bootstrap.query}`);
                }
                if (!payload.session) {
                    hideProgress();
                    return;
                }

                let displayName = payload.session.display_name || "";
                if (payload.mode === "edit_campaign") {
                    displayName = displayName || `Campaign ${payload.session.edit_campaign_id || ""}`.trim();
                } else if (payload.mode === "autoload") {
                    displayName = buildAutoloadDisplayName(payload.session.source);
                } else if (payload.mode === "export_file") {
                    displayName = displayName || payload.session.filename || "Exportdatei";
                } else if (payload.mode === "firebase_only") {
                    displayName = "Bewerbung (Bitte Domain waehlen)";
                } else if (payload.mode === "application") {
                    displayName = displayName || "Bewerbung";
                }

                applyLoadedSession(payload.session, displayName);
                if (els.exportSelect && payload.session.filename) {
                    els.exportSelect.value = String(payload.session.filename || "");
                    els.loadExportBtn.disabled = !String(els.exportSelect.value || "").trim();
                }

                if (payload.session.application_summary) {
                    const summary = payload.session.application_summary;
                    firebaseBereich = String(summary.bereich || "").trim();
                    if (firebaseBereich && (payload.mode === "firebase_only" || payload.mode === "application")) {
                        autoSelectBereichDomain();
                    }
                }

                if (payload.mode === "firebase_only" || (payload.mode === "application" && !payload.session.filename)) {
                    showProgress("Bewerbung geladen", 100);
                    window.setTimeout(hideProgress, 600);
                    showToast("Bewerbung geladen. Bitte waehle eine Export-Domain aus.");
                } else {
                    showProgress(
                        payload.mode === "edit_campaign" ? "Anschreiben geladen" : "Daten geladen",
                        100,
                    );
                    window.setTimeout(hideProgress, 600);
                    showToast(
                        payload.mode === "edit_campaign"
                            ? "Gespeichertes Anschreiben wurde geladen"
                            : "Anschreiben-Daten wurden geladen",
                    );
                }
            } catch (error) {
                hideProgress();
                showInlineError(error.message || "Anschreiben-Daten konnten nicht geladen werden.");
                showToast(error.message || "Anschreiben-Daten konnten nicht geladen werden.");
            }
        }

        function getCachedApplication(applicationId) {
            const normalizedApplicationId = String(applicationId || "").trim();
            if (!normalizedApplicationId) {
                return null;
            }

            try {
                const rawValue = window.sessionStorage.getItem(`${applicationStoragePrefix}${normalizedApplicationId}`)
                    || window.sessionStorage.getItem(`${firebaseApplicationStoragePrefix}${normalizedApplicationId}`);
                return rawValue ? JSON.parse(rawValue) : null;
            } catch (_error) {
                return null;
            }
        }

        function getCachedFirebaseApplication(applicationId) {
            return getCachedApplication(applicationId);
        }

        function getFirebaseBootstrapInfo() {
            const params = new URLSearchParams(window.location.search);
            const queryApplicationId = String(params.get("application_id") || "").trim();
            let fallbackApplicationId = "";

            try {
                fallbackApplicationId = String(
                    window.sessionStorage.getItem(lastApplicationKey)
                    || window.sessionStorage.getItem(firebaseLastApplicationKey)
                    || "",
                ).trim();
            } catch (_error) {
                fallbackApplicationId = "";
            }

            const applicationId = queryApplicationId || fallbackApplicationId;
            return {
                key: applicationId,
                applicationId,
                application: getCachedApplication(applicationId),
            };
        }

        async function bootstrapFirebaseFromUrl() {
            const bootstrap = getFirebaseBootstrapInfo();
            if (!bootstrap.applicationId) {
                setSourcePrompt("Noch keine Bewerbung ausgewaehlt. Oeffne die Supabase-Liste und klicke bei einem Eintrag auf Next step.");
                renderApplicationSummary(null);
                return;
            }
            if (bootstrap.key === lastBootstrapKey) {
                return;
            }

            lastBootstrapKey = bootstrap.key;
            clearInlineError();
            showProgress("Bewerbung wird geladen...", 25);

            try {
                const payload = await fetchJson(`${API_BASE}/create-anschreibens/application-bootstrap`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        application_id: bootstrap.applicationId,
                        application: bootstrap.application || undefined,
                        source_label: "Supabase",
                    }),
                });
                if (!payload.session) {
                    hideProgress();
                    return;
                }

                applyLoadedSession(
                    payload.session,
                    payload.session.display_name || `Bewerbung ${bootstrap.applicationId}`,
                );
                renderApplicationSummary(payload.session.application_summary || {});
                setSourcePrompt("");

                const params = new URLSearchParams();
                params.set("application_id", bootstrap.applicationId);
                updateSectionQuery(params);

                showProgress("Bewerbung geladen", 100);
                window.setTimeout(hideProgress, 600);
                showToast("Bewerbung wurde geladen");

                const summary = payload.session.application_summary || {};
                firebaseBereich = String(summary.bereich || "").trim();
            } catch (error) {
                hideProgress();
                showInlineError(error.message || "Bewerbung konnte nicht geladen werden.");
                showToast(error.message || "Bewerbung konnte nicht geladen werden.");
            }
        }

        function autoSelectBereichDomain() {
            if (!firebaseBereich || !els.exportSelect) return;

            const bereichLower = firebaseBereich.toLowerCase();
            const options = Array.from(els.exportSelect.options);
            let bestMatch = null;

            for (const option of options) {
                if (!option.value) continue;
                const label = option.textContent.toLowerCase();
                const value = option.value.toLowerCase();
                if (value.includes(bereichLower) || label.includes(bereichLower) || bereichLower.includes(value.replace(/\.xlsx?$|\.csv$/i, "").replace(/[_-]/g, " ").trim())) {
                    bestMatch = option.value;
                    break;
                }
            }

            if (!bestMatch) {
                const bereichWords = bereichLower.split(/\s+/).filter(w => w.length > 2);
                for (const option of options) {
                    if (!option.value) continue;
                    const label = option.textContent.toLowerCase();
                    const matchCount = bereichWords.filter(w => label.includes(w)).length;
                    if (matchCount >= Math.max(1, Math.floor(bereichWords.length * 0.5))) {
                        bestMatch = option.value;
                        break;
                    }
                }
            }

            if (bestMatch) {
                els.exportSelect.value = bestMatch;
                els.loadExportBtn.disabled = false;
                loadExportFilename(bestMatch, false).catch(() => {});
            }
        }

        function bindEvents() {
            bindDropZone(els.designDropZone, els.designFileInput, handleDesignFiles);

            if (els.exportSelect && els.loadExportBtn) {
                els.exportSelect.addEventListener("change", () => {
                    els.loadExportBtn.disabled = !String(els.exportSelect.value || "").trim();
                });

                els.loadExportBtn.addEventListener("click", () => {
                    loadExportFilename(els.exportSelect.value, true).catch((error) => {
                        hideProgress();
                        showInlineError(error.message || "Exportdaten konnten nicht geladen werden.");
                        showToast(error.message || "Exportdaten konnten nicht geladen werden.");
                    });
                });
            }

            if (els.extractBtn) {
                els.extractBtn.addEventListener("click", async () => {
                    const pageStr = els.extractPageInput ? els.extractPageInput.value : "1";
                    const page = parseInt(pageStr, 10);
                    const pdfUrl = els.pdfContainer ? els.pdfContainer.dataset.pdfUrl : null;
                    
                    if (!pdfUrl) {
                        showToast("Kein PDF verfügbar. Bitte lade zuerst eine Bewerbung.");
                        return;
                    }
                    if (isNaN(page) || page < 1) {
                        showToast("Bitte eine gültige Seitenzahl (>= 1) eingeben.");
                        return;
                    }

                    els.extractBtn.disabled = true;
                    if (els.extractStatus) {
                        els.extractStatus.hidden = false;
                        els.extractStatus.textContent = "Extrahiere...";
                    }

                    try {
                        const data = await fetchJson("/api/extract-pdf-text", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ pdf_url: pdfUrl, page: page }),
                        });
                        
                        els.templateEditor.value = data.text || "";
                        persistActiveTemplateValue();
                        renderTemplateList();
                        
                        showToast("Text erfolgreich extrahiert");

                        // Automatically trigger AI templatize if columns are loaded
                        if (state.columns.length > 0) {
                            aiTemplatize().catch(() => {});
                        }
                    } catch (error) {
                        showInlineError(error.message || "Text-Extraktion fehlgeschlagen.");
                        showToast(error.message || "Text-Extraktion fehlgeschlagen.");
                    } finally {
                        els.extractBtn.disabled = false;
                        if (els.extractStatus) els.extractStatus.hidden = true;
                    }
                });
            }

            if (els.aiTemplatizeBtn) {
                els.aiTemplatizeBtn.addEventListener("click", () => {
                    aiTemplatize().catch((error) => {
                        hideProgress();
                        showInlineError(error.message || "KI-Verarbeitung fehlgeschlagen.");
                        showToast(error.message || "KI-Verarbeitung fehlgeschlagen.");
                    });
                });
            }

            els.saveTemplateBtn.addEventListener("click", () => {
                saveTemplate().catch((error) => {
                    showInlineError(error.message || "Vorlage konnte nicht gespeichert werden.");
                    showToast(error.message || "Vorlage konnte nicht gespeichert werden.");
                });
            });

            els.resetTemplateBtn.addEventListener("click", () => {
                els.templateEditor.value = defaultTemplate;
                persistActiveTemplateValue();
                renderTemplateList();
                clearValidation();
                showToast("Aktive Variante geleert");
            });

            els.addTemplateBtn.addEventListener("click", () => {
                addTemplate();
                showToast("Neue Variante erstellt");
            });

            els.deleteTemplateBtn.addEventListener("click", () => {
                deleteActiveTemplate();
                showToast("Variante entfernt");
            });

            els.resetLayoutBtn.addEventListener("click", () => {
                setLayoutInputs(defaultLayout);
                showToast("Layout auf Standard zurueckgesetzt");
            });

            els.previewBtn.addEventListener("click", () => {
                previewPdf().catch((error) => {
                    hideProgress();
                    showInlineError(error.message || "Vorschau fehlgeschlagen");
                    showToast(error.message || "Vorschau fehlgeschlagen");
                });
            });

            els.generateBtn.addEventListener("click", () => {
                generatePdfs().catch((error) => {
                    hideProgress();
                    showInlineError(error.message || "Generierung fehlgeschlagen");
                    showToast(error.message || "Generierung fehlgeschlagen");
                });
            });

            if (els.toEmailBtn) {
                els.toEmailBtn.addEventListener("click", () => {
                    transferToEmailSender().catch((error) => {
                        hideProgress();
                        showInlineError(error.message || "Transfer fehlgeschlagen");
                        showToast(error.message || "Transfer fehlgeschlagen");
                    });
                });
            }

            els.closeModalBtn.addEventListener("click", closePreview);
            els.closeFooterBtn.addEventListener("click", closePreview);

            els.formatToolbar.addEventListener("click", (event) => {
                const button = event.target.closest(".anschreiben-format-btn");
                if (!button) {
                    return;
                }
                wrapSelection(button.dataset.prefix || "", button.dataset.suffix || "");
                persistActiveTemplateValue();
                renderTemplateList();
            });

            els.templateEditor.addEventListener("input", () => {
                persistActiveTemplateValue();
                renderTemplateList();
            });

            window.addEventListener("keydown", (event) => {
                if (event.key === "Escape") {
                    closePreview();
                }
            });

            window.addEventListener("beforeunload", () => {
                if (state.sessionId) {
                    clearPdfSession(state.sessionId, true).catch(() => {});
                }
            });
        }

        function ensureInitialized() {
            if (initialized) {
                return;
            }
            initialized = true;
            setLayoutInputs(defaultLayout);
            syncFilenameFormatDisplay("{{Unternehmen}}");
            loadActiveTemplateIntoEditor();
            if (els.toEmailBtn && !transferEnabled) {
                els.toEmailBtn.hidden = true;
            }
            renderCachedApplicationDocuments();
            bindEvents();
        }

        return {
            show() {
                ensureInitialized();
                const exportPromise = ensureExportOptionsLoaded(false)
                    .catch((error) => {
                        showInlineError(error.message || "Exportdateien konnten nicht geladen werden.");
                    })
                    .finally(() => {
                        if (dataSourceMode === "export-selector") {
                            bootstrapCreateFromUrl().catch(() => {});
                        }
                    });

                if (dataSourceMode === "firebase-application") {
                    const firebasePromise = bootstrapFirebaseFromUrl().catch(() => {});
                    Promise.all([exportPromise, firebasePromise]).then(() => {
                        autoSelectBereichDomain();
                    });
                }
            },
            hide() {
                closePreview();
            },
        };
    }

    sections.buildAnschreibenSection = createAnschreibenSection;
    sections.createCreateAnschreibensSection = function createCreateAnschreibensSection() {
        return createAnschreibenSection({
            prefix: "create-anschreibens",
            dataSourceMode: "export-selector",
            defaultFilenameFormatLabel: "Automatisch aus Firma",
            transferEnabled: true,
        });
    };

    window.SPASections = sections;
})();

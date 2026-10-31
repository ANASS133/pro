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
            activeBgTemplateId: null,
            cachedBgTemplates: null,
            transferReadyCount: 0,
            templates: [defaultTemplate],
            activeTemplateIndex: 0,
            filenameFormat: "{{Unternehmen}}",
            variantNames: ["Variante 1"],
            previewRowIndex: 0,
            isDirty: false,
            history: [],
            historyIndex: -1,
            displayMode: "split",
            livePreviewObjectUrl: "",
            livePreviewDebounceTimer: null,
            autoFit: true,
            minFontSize: 8.0,
            selectedFont: "helvetica",
            showFoldMarks: false,
            dinPreset: null,
            watermarkText: "",
        };

        function byId(name) {
            return document.getElementById(`${prefix}-${name}`);
        }

        const els = {
            studioRoot: document.getElementById(`${prefix}-studio`),
            modeBtns: root.querySelectorAll(".as-mode-btn"),
            saveStatusPill: byId("saveStatusPill"),
            duplicateTemplateBtn: byId("duplicateTemplateBtn"),
            renameTemplateBtn: byId("renameTemplateBtn"),
            activeVariantTitle: document.getElementById("as-active-variant-title"),
            wordCountEl: document.getElementById("as-word-count"),
            charCountEl: document.getElementById("as-char-count"),
            autoDraftNote: document.getElementById("as-auto-draft-note"),
            editorUndoBtn: document.getElementById("as-editor-undo"),
            editorRedoBtn: document.getElementById("as-editor-redo"),
            livePreviewIframe: document.getElementById("as-live-preview-iframe"),
            livePreviewPlaceholder: document.getElementById("as-preview-placeholder"),
            liveDocName: document.getElementById("as-live-doc-name"),
            recordPrevBtn: document.getElementById("as-record-prev"),
            recordNextBtn: document.getElementById("as-record-next"),
            recordIndicator: document.getElementById("as-record-indicator"),
            refreshPreviewBtn: document.getElementById("as-refresh-preview"),
            checkRecords: document.getElementById("as-check-records"),
            checkVariants: document.getElementById("as-check-variants"),
            checkDesign: document.getElementById("as-check-design"),
            checkPlaceholders: document.getElementById("as-check-placeholders"),
            readinessPill: document.getElementById("as-readiness-pill"),
            placeholderSearch: document.getElementById("as-placeholder-search"),
            placeholderAccordion: document.getElementById("as-placeholder-accordion"),
            placeholderToggle: document.getElementById("as-placeholder-toggle"),
            placeholderCounter: document.getElementById("as-placeholder-counter"),
            error: byId("error"),
            exportSelect: byId("exportSelect"),
            clientSelect: byId("clientSelect"),
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
            removeDesignBtn: byId("removeDesignBtn"),
            bgTemplatesBtn: byId("bgTemplatesBtn"),
            bgTemplatesModal: byId("bgTemplatesModal"),
            closeBgTemplatesBtn: byId("closeBgTemplatesBtn"),
            cancelBgModalBtn: byId("cancelBgModalBtn"),
            clearBgTemplateBtn: byId("clearBgTemplateBtn"),
            bgTemplatesList: byId("bgTemplatesList"),
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
            atsTailorBtn: byId("atsTailorBtn"),
            atsModal: byId("atsModal"),
            closeAtsModalBtn: byId("closeAtsModalBtn"),
            atsJobTitle: byId("atsJobTitle"),
            atsCompanyName: byId("atsCompanyName"),
            atsRequirements: byId("atsRequirements"),
            atsCustomBullets: byId("atsCustomBullets"),
            atsRunBtn: byId("atsRunBtn"),
            atsCostBadge: byId("atsCostBadge"),
            atsCostText: byId("atsCostText"),
            atsResultArea: byId("atsResultArea"),
            atsResultBullets: byId("atsResultBullets"),
            atsInsertBtn: byId("atsInsertBtn"),
            atsCopyBtn: byId("atsCopyBtn"),
            goldenHookBtn: byId("goldenHookBtn"),
            goldenHookModal: byId("goldenHookModal"),
            closeGoldenHookModalBtn: byId("closeGoldenHookModalBtn"),
            hookCompanyName: byId("hookCompanyName"),
            hookJobTitle: byId("hookJobTitle"),
            hookContext: byId("hookContext"),
            hookRunBtn: byId("hookRunBtn"),
            hookCostBadge: byId("hookCostBadge"),
            hookCostText: byId("hookCostText"),
            hookResultArea: byId("hookResultArea"),
            hookResultText: byId("hookResultText"),
            hookInsertBtn: byId("hookInsertBtn"),
            hookCopyBtn: byId("hookCopyBtn"),
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
            ? "Please load an application first"
            : "Please load export data first";

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
            if (!Array.isArray(state.variantNames)) {
                state.variantNames = [];
            }
            while (state.variantNames.length < state.templates.length) {
                state.variantNames.push(`Variante ${state.variantNames.length + 1}`);
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
            els.error.textContent = String(message || "").trim() || "Unknown error.";
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

            if (normalizedLayout.auto_fit !== undefined) state.autoFit = Boolean(normalizedLayout.auto_fit);
            if (normalizedLayout.font) state.selectedFont = normalizedLayout.font;
            if (normalizedLayout.din_5008_preset) state.dinPreset = normalizedLayout.din_5008_preset;
            if (normalizedLayout.show_fold_marks !== undefined) state.showFoldMarks = Boolean(normalizedLayout.show_fold_marks);
            if (normalizedLayout.watermark !== undefined) state.watermarkText = normalizedLayout.watermark;
        }

        function getLayoutOptions() {
            const opts = {
                font_size: toNumber(els.fontSizeInput.value, defaultLayout.font_size),
                line_height: toNumber(els.lineHeightInput.value, defaultLayout.line_height),
                margin_top: toNumber(els.marginTopInput.value, defaultLayout.margin_top),
                margin_left: toNumber(els.marginLeftInput.value, defaultLayout.margin_left),
                margin_right: toNumber(els.marginRightInput.value, defaultLayout.margin_right),
                margin_bottom: toNumber(els.marginBottomInput.value, defaultLayout.margin_bottom),
                text_width: toNumber(els.textWidthInput.value, defaultLayout.text_width),
                text_height: toNumber(els.textHeightInput.value, defaultLayout.text_height),
                auto_fit: state.autoFit !== undefined ? state.autoFit : true,
                min_font_size: state.minFontSize || 8.0,
                font: state.selectedFont || "helvetica",
                show_fold_marks: Boolean(state.showFoldMarks),
            };
            if (state.dinPreset) {
                opts.din_5008_preset = state.dinPreset;
            }
            if (state.watermarkText) {
                opts.watermark = state.watermarkText;
            }
            return opts;
        }

        function persistActiveTemplateValue() {
            ensureTemplateState();
            state.templates[state.activeTemplateIndex] = els.templateEditor.value || "";
        }

        function updateEditorStats() {
            const text = els.templateEditor?.value || "";
            const trimmed = text.trim();
            const words = trimmed ? trimmed.split(/\s+/).length : 0;
            const chars = text.length;
            if (els.wordCountEl) {
                els.wordCountEl.textContent = `${words} ${words === 1 ? 'word' : 'words'}`;
            }
            if (els.charCountEl) {
                els.charCountEl.textContent = `${chars} ${chars === 1 ? 'Zeichen' : 'Zeichen'}`;
            }
        }

        function setSaveStatus(saved) {
            state.isDirty = !saved;
            if (els.saveStatusPill) {
                els.saveStatusPill.className = `as-save-indicator ${saved ? 'is-saved' : 'is-unsaved'}`;
                const textEl = els.saveStatusPill.querySelector(".as-save-text");
                if (textEl) {
                    textEl.textContent = saved ? "Saved" : "Unsaved";
                }
            }
            if (els.autoDraftNote) {
                els.autoDraftNote.textContent = saved ? "All changes saved" : "Unsaved changes";
            }
            updateReadiness();
        }

        function updateReadiness() {
            if (els.checkRecords) {
                const count = state.previewRows?.length || 0;
                els.checkRecords.textContent = `${count} ${count === 1 ? 'Kontakt' : 'Kontakte'}`;
            }
            if (els.checkVariants) {
                const count = state.templates?.length || 1;
                els.checkVariants.textContent = `${count} ${count === 1 ? 'Variante' : 'Varianten'}`;
            }
            if (els.checkDesign) {
                if (state.activeBgTemplateId) {
                    els.checkDesign.textContent = `Briefpapier (${state.activeBgTemplateId})`;
                } else if (state.designPdfName) {
                    els.checkDesign.textContent = "Eigenes PDF";
                } else {
                    els.checkDesign.textContent = "Standard";
                }
            }
            if (els.checkPlaceholders) {
                const editorText = els.templateEditor?.value || "";
                const matches = editorText.match(/\{\{([^}]+)\}\}/g) || [];
                const knownTokens = new Set([
                    ...state.columns,
                    "custom_hook",
                    "salutation",
                    "ansprechpartner",
                    "geschaeftsfuehrer",
                    "heutigenDatum",
                ]);
                const unresolved = matches
                    .map(m => m.replace(/^\{\{|\}\}$/g, "").trim())
                    .filter(t => !knownTokens.has(t));

                if (unresolved.length > 0 && state.columns.length > 0) {
                    els.checkPlaceholders.textContent = `${unresolved.length} incomplete`;
                    els.checkPlaceholders.className = "as-item-val is-warn";
                } else {
                    els.checkPlaceholders.textContent = "Valid";
                    els.checkPlaceholders.className = "as-item-val is-ok";
                }
            }
            if (els.readinessPill) {
                const hasData = state.previewRows?.length > 0;
                const hasText = Boolean((els.templateEditor?.value || "").trim());
                if (hasData && hasText) {
                    els.readinessPill.textContent = "Bereit";
                    els.readinessPill.className = "as-readiness-pill ready";
                } else {
                    els.readinessPill.textContent = !hasData ? "Warten auf Daten" : "Text leer";
                    els.readinessPill.className = "as-readiness-pill waiting";
                }
            }
        }

        function renderTemplateList() {
            ensureTemplateState();
            els.templateList.innerHTML = "";

            state.templates.forEach((template, index) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = `as-var-tab${index === state.activeTemplateIndex ? " is-active" : ""}${template.trim() ? "" : " is-empty"}`;
                const name = state.variantNames[index] || `Variante ${index + 1}`;
                button.innerHTML = `<span>${escapeHtml(name)}</span>${template.trim() ? "" : ' <span class="as-tab-empty">(leer)</span>'}`;
                button.title = `${name} auswählen`;
                button.addEventListener("click", () => switchTemplate(index));
                els.templateList.appendChild(button);
            });

            if (els.activeVariantTitle) {
                els.activeVariantTitle.textContent = state.variantNames[state.activeTemplateIndex] || `Variante ${state.activeTemplateIndex + 1}`;
            }

            els.deleteTemplateBtn.disabled = state.templates.length <= 1;
            updateEditorStats();
            updateReadiness();
        }

        function loadActiveTemplateIntoEditor() {
            ensureTemplateState();
            els.templateEditor.value = state.templates[state.activeTemplateIndex] || "";
            renderTemplateList();
            pushHistory(els.templateEditor.value);
            scheduleLivePreviewUpdate();
        }

        function switchTemplate(index) {
            persistActiveTemplateValue();
            state.activeTemplateIndex = index;
            loadActiveTemplateIntoEditor();
        }

        function addTemplate() {
            persistActiveTemplateValue();
            state.templates.push("");
            state.variantNames.push(`Variante ${state.templates.length}`);
            state.activeTemplateIndex = state.templates.length - 1;
            loadActiveTemplateIntoEditor();
            setSaveStatus(false);
        }

        function duplicateActiveTemplate() {
            persistActiveTemplateValue();
            const currentContent = state.templates[state.activeTemplateIndex] || "";
            const currentName = state.variantNames[state.activeTemplateIndex] || `Variante ${state.activeTemplateIndex + 1}`;
            state.templates.push(currentContent);
            state.variantNames.push(`${currentName} (Kopie)`);
            state.activeTemplateIndex = state.templates.length - 1;
            loadActiveTemplateIntoEditor();
            setSaveStatus(false);
            showToast("Variante dupliziert");
        }

        function renameActiveTemplate() {
            ensureTemplateState();
            const currentName = state.variantNames[state.activeTemplateIndex] || `Variante ${state.activeTemplateIndex + 1}`;
            const newName = window.prompt("Name der Variante eingeben:", currentName);
            if (newName && newName.trim()) {
                state.variantNames[state.activeTemplateIndex] = newName.trim();
                renderTemplateList();
                showToast(`Variante umbenannt in "${newName.trim()}"`);
            }
        }

        function deleteActiveTemplate() {
            ensureTemplateState();
            if (state.templates.length <= 1) {
                if (window.confirm("Do you want to clear this variation?")) {
                    state.templates[0] = "";
                    loadActiveTemplateIntoEditor();
                    setSaveStatus(false);
                    showToast("Variante geleert");
                }
                return;
            }
            if (window.confirm("Möchten Sie diese Variante wirklich löschen?")) {
                state.templates.splice(state.activeTemplateIndex, 1);
                state.variantNames.splice(state.activeTemplateIndex, 1);
                state.activeTemplateIndex = Math.max(0, state.activeTemplateIndex - 1);
                loadActiveTemplateIntoEditor();
                setSaveStatus(false);
                showToast("Variante gelöscht");
            }
        }

        function pushHistory(text) {
            if (state.historyIndex >= 0 && state.history[state.historyIndex] === text) {
                return;
            }
            if (state.historyIndex < state.history.length - 1) {
                state.history = state.history.slice(0, state.historyIndex + 1);
            }
            state.history.push(text);
            if (state.history.length > 50) {
                state.history.shift();
            }
            state.historyIndex = state.history.length - 1;
        }

        function editorUndo() {
            if (state.historyIndex > 0) {
                state.historyIndex--;
                els.templateEditor.value = state.history[state.historyIndex] || "";
                persistActiveTemplateValue();
                updateEditorStats();
                setSaveStatus(false);
                scheduleLivePreviewUpdate();
            }
        }

        function editorRedo() {
            if (state.historyIndex < state.history.length - 1) {
                state.historyIndex++;
                els.templateEditor.value = state.history[state.historyIndex] || "";
                persistActiveTemplateValue();
                updateEditorStats();
                setSaveStatus(false);
                scheduleLivePreviewUpdate();
            }
        }

        function setDisplayMode(mode) {
            const validModes = ["editor", "split", "preview"];
            const targetMode = validModes.includes(mode) ? mode : "split";
            state.displayMode = targetMode;

            if (els.studioRoot) {
                els.studioRoot.dataset.displayMode = targetMode;
            }

            if (els.modeBtns) {
                els.modeBtns.forEach((btn) => {
                    btn.classList.toggle("is-active", btn.dataset.mode === targetMode);
                });
            }

            try {
                window.localStorage.setItem("as_display_mode", targetMode);
            } catch (_e) {}

            if (targetMode !== "editor" && (!els.livePreviewIframe || !els.livePreviewIframe.src)) {
                updateLivePreview(state.previewRowIndex, true).catch(() => {});
            }
        }

        function initDisplayMode() {
            let savedMode = "split";
            try {
                savedMode = window.localStorage.getItem("as_display_mode") || "split";
            } catch (_e) {}
            setDisplayMode(savedMode);
        }

        async function updateLivePreview(rowIndex = state.previewRowIndex, silent = true) {
            if (!state.sessionId || !Array.isArray(state.previewRows) || state.previewRows.length === 0) {
                if (els.livePreviewPlaceholder) els.livePreviewPlaceholder.hidden = false;
                if (els.livePreviewIframe) {
                    els.livePreviewIframe.hidden = true;
                    els.livePreviewIframe.src = "";
                }
                if (els.recordIndicator) els.recordIndicator.textContent = "0 / 0";
                if (els.liveDocName) els.liveDocName.textContent = "Keine Daten";
                return;
            }

            const total = state.previewRows.length;
            const clampedIndex = Math.max(0, Math.min(total - 1, Number(rowIndex) || 0));
            state.previewRowIndex = clampedIndex;

            if (els.recordIndicator) {
                els.recordIndicator.textContent = `${clampedIndex + 1} / ${total}`;
            }

            const currentRow = state.previewRows[clampedIndex] || {};
            const recipientLabel = currentRow["Unternehmen"]
                || currentRow["Firma"]
                || currentRow["Company"]
                || currentRow["Nachname"]
                || `Empfänger ${clampedIndex + 1}`;

            if (els.liveDocName) {
                els.liveDocName.textContent = recipientLabel;
            }

            try {
                await saveTemplate({ silent: true });

                const response = await fetch(`${API_BASE}/preview-pdf`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        session_id: state.sessionId,
                        row_index: clampedIndex,
                        layout_options: getLayoutOptions(),
                    }),
                });

                if (!response.ok) {
                    return;
                }

                if (state.livePreviewObjectUrl) {
                    URL.revokeObjectURL(state.livePreviewObjectUrl);
                    state.livePreviewObjectUrl = "";
                }

                const blob = await response.blob();
                state.livePreviewObjectUrl = URL.createObjectURL(blob);

                if (els.livePreviewIframe) {
                    els.livePreviewIframe.src = state.livePreviewObjectUrl;
                    els.livePreviewIframe.hidden = false;
                }
                if (els.livePreviewPlaceholder) {
                    els.livePreviewPlaceholder.hidden = true;
                }
            } catch (_e) {
                // Ignore silent preview errors
            }
        }

        function scheduleLivePreviewUpdate() {
            if (state.livePreviewDebounceTimer) {
                window.clearTimeout(state.livePreviewDebounceTimer);
            }
            state.livePreviewDebounceTimer = window.setTimeout(() => {
                if (state.displayMode !== "editor") {
                    updateLivePreview(state.previewRowIndex, true).catch(() => {});
                }
            }, 1000);
        }

        function nextPreviewRecord() {
            if (!state.previewRows || !state.previewRows.length) return;
            if (state.previewRowIndex < state.previewRows.length - 1) {
                updateLivePreview(state.previewRowIndex + 1, false);
            }
        }

        function prevPreviewRecord() {
            if (!state.previewRows || !state.previewRows.length) return;
            if (state.previewRowIndex > 0) {
                updateLivePreview(state.previewRowIndex - 1, false);
            }
        }

        function insertPlaceholder(placeholderName) {
            const token = `{{${placeholderName}}}`;
            wrapSelection(token, "");
            persistActiveTemplateValue();
            renderTemplateList();
            setSaveStatus(false);
            scheduleLivePreviewUpdate();
            showToast(`Eingefügt: ${token}`, 1200);
        }

        function createPlaceholderPill(name, category, label) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = `placeholder-pill placeholder-pill--${category}`;
            btn.title = label ? `${label} - Klicken zum Einfügen: {{${name}}}` : `Klicken zum Einfügen: {{${name}}}`;

            let iconSvg = "";
            if (category === "smart") {
                iconSvg = `<svg class="pill-svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3L12 3Z"/></svg>`;
            } else if (category === "data") {
                iconSvg = `<svg class="pill-svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>`;
            } else if (category === "system") {
                iconSvg = `<svg class="pill-svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>`;
            }

            btn.innerHTML = `<span class="pill-icon">${iconSvg}</span><span class="pill-text">{{${escapeHtml(name)}}}</span>`;
            btn.addEventListener("click", (e) => {
                e.preventDefault();
                insertPlaceholder(name);
                btn.classList.add("is-popping");
                window.setTimeout(() => btn.classList.remove("is-popping"), 250);
            });
            return btn;
        }

        function renderPlaceholders(columns = []) {
            if (!els.placeholderTags) return;
            els.placeholderTags.innerHTML = "";

            const smartTokens = [
                { name: "custom_hook", label: "Dynamische Einleitung" },
                { name: "salutation", label: "Anrede (Sehr geehrte/r...)" },
                { name: "ansprechpartner", label: "Kontaktperson" },
                { name: "geschaeftsfuehrer", label: "Geschäftsführer" },
            ];

            const systemTokens = [
                { name: "heutigenDatum", label: "Heutiges Datum" },
            ];

            const defaultCompanyTokens = ["Unternehmen", "Ort", "Stelle"];
            const defaultContactTokens = ["Vorname", "Nachname", "Email"];

            const rawCols = Array.isArray(columns) ? columns : [];
            const isSmartOrSys = (c) => ["custom_hook", "salutation", "ansprechpartner", "geschaeftsfuehrer", "heutigenDatum"].includes(c);

            const matchedContact = rawCols.filter(c => !isSmartOrSys(c) && /vorname|nachname|name|email|mail|telefon|phone|mobil/i.test(c));
            const contactCols = matchedContact.length ? matchedContact : defaultContactTokens;

            const matchedCompany = rawCols.filter(c => !isSmartOrSys(c) && !contactCols.includes(c) && /firma|unternehmen|company|arbeitgeber|ort|city|plz|straße|adresse|branche|job|beruf|stelle|position/i.test(c));
            const companyCols = matchedCompany.length ? matchedCompany : defaultCompanyTokens;

            const otherCols = rawCols.filter(c => !isSmartOrSys(c) && !contactCols.includes(c) && !companyCols.includes(c));

            function createGroupRow(badgeText, badgeClass, tokens, category) {
                if (!tokens || !tokens.length) return null;
                const row = document.createElement("div");
                row.className = "as-placeholder-group-row";

                const badge = document.createElement("span");
                badge.className = `as-group-badge ${badgeClass}`;
                badge.textContent = badgeText;
                row.appendChild(badge);

                const pillsWrap = document.createElement("div");
                pillsWrap.className = "as-pills-wrap";
                tokens.forEach((t) => {
                    const name = typeof t === "string" ? t : t.name;
                    const label = typeof t === "object" ? t.label : "";
                    pillsWrap.appendChild(createPlaceholderPill(name, category, label));
                });
                row.appendChild(pillsWrap);
                return row;
            }

            // 1. KI
            const kiRow = createGroupRow("KI", "bg-ki", smartTokens, "smart");
            if (kiRow) els.placeholderTags.appendChild(kiRow);

            // 2. Kontakt
            const contactRow = createGroupRow("Kontakt", "bg-contact", contactCols, "data");
            if (contactRow) els.placeholderTags.appendChild(contactRow);

            // 3. Unternehmen
            const companyRow = createGroupRow("Firma", "bg-company", companyCols, "data");
            if (companyRow) els.placeholderTags.appendChild(companyRow);

            // 4. Datei-Spalten
            const dataRow = createGroupRow("Datei", "bg-data", otherCols, "data");
            if (dataRow) els.placeholderTags.appendChild(dataRow);

            // 5. System
            const sysRow = createGroupRow("System", "bg-sys", systemTokens, "system");
            if (sysRow) els.placeholderTags.appendChild(sysRow);

            const totalCount = smartTokens.length + systemTokens.length + contactCols.length + companyCols.length + otherCols.length;
            if (els.placeholderCounter) {
                els.placeholderCounter.textContent = `${totalCount} verfügbar`;
            }

            applyPlaceholderFilter();
        }

        function applyPlaceholderFilter() {
            if (!els.placeholderTags) return;
            const query = (els.placeholderSearch?.value || "").toLowerCase().trim();
            const pills = els.placeholderTags.querySelectorAll(".placeholder-pill");
            pills.forEach((pill) => {
                const text = pill.textContent.toLowerCase();
                const title = (pill.title || "").toLowerCase();
                const matches = !query || text.includes(query) || title.includes(query);
                pill.style.display = matches ? "inline-flex" : "none";
            });

            const rows = els.placeholderTags.querySelectorAll(".as-placeholder-group-row");
            rows.forEach((row) => {
                const visiblePills = row.querySelectorAll('.placeholder-pill:not([style*="display: none"])');
                row.style.display = visiblePills.length > 0 ? "flex" : "none";
            });
        }

        function renderColumns(columns) {
            els.columnList.innerHTML = "";
            (columns || []).forEach((column) => {
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "anschreiben-column-tag";
                btn.title = `Klicken, um {{${column}}} in die Vorlage einzufügen`;
                btn.textContent = `+ {{${column}}}`;
                btn.addEventListener("click", (e) => {
                    e.preventDefault();
                    insertPlaceholder(column);
                });
                els.columnList.appendChild(btn);
            });

            renderPlaceholders(columns);
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
                
            const isEditCampaign = Boolean(data.edit_campaign_id);
            let docs = [];
            if (data.application_data && Array.isArray(data.application_data.documents)) {
                docs = data.application_data.documents;
            } else if (data.application_summary && Array.isArray(data.application_summary.documents)) {
                docs = data.application_summary.documents;
            }

            if (docs.length > 0) {
                renderApplicationDocuments(docs);
            } else if (!isEditCampaign) {
                renderCachedApplicationDocuments();
            } else {
                currentDocuments = [];
                if (els.pdfContainer) els.pdfContainer.hidden = true;
                if (els.sourcePrompt) {
                    els.sourcePrompt.hidden = false;
                    els.sourcePrompt.textContent = "Für diese gespeicherte Kampagne sind keine separaten Bewerbungsdokumente im Editor hinterlegt.";
                }
            }

            renderColumns(state.columns);
            renderPreview(state.previewRows);
            loadActiveTemplateIntoEditor();
            clearValidation();
            clearInlineError();
            setSaveStatus(true);
            updateReadiness();
            updateLivePreview(0, true).catch(() => {});
        }

        async function loadStudioClients() {
            if (!els.clientSelect) return;
            try {
                const res = await fetch("/api/clients");
                if (!res.ok) return;
                const data = await res.json();
                const clients = Array.isArray(data.clients) ? data.clients : [];
                
                const currentVal = els.clientSelect.value;
                els.clientSelect.innerHTML = '<option value="">Select candidate profile...</option>';
                clients.forEach((c) => {
                    const opt = document.createElement("option");
                    opt.value = c.id;
                    const name = c.name || c.contact?.full_name || c.id;
                    const field = c.profile?.field ? ` (${c.profile.field})` : "";
                    opt.textContent = `${name}${field}`;
                    els.clientSelect.appendChild(opt);
                });
                if (currentVal && clients.some(c => c.id === currentVal)) {
                    els.clientSelect.value = currentVal;
                } else if (state.clientId && clients.some(c => c.id === state.clientId)) {
                    els.clientSelect.value = state.clientId;
                }
            } catch (_) {}
        }

        async function onStudioClientSelected(clientId) {
            state.clientId = clientId || null;
            if (!clientId) {
                if (els.applicationSummary) els.applicationSummary.hidden = true;
                return;
            }

            try {
                const res = await fetch(`/api/clients/${encodeURIComponent(clientId)}`);
                if (!res.ok) return;
                const data = await res.json();
                const client = data.client || {};
                const contact = client.contact || {};
                const profile = client.profile || {};
                const pkg = client.package || {};

                // Update studio applicant banner if elements exist
                if (els.summaryName) els.summaryName.textContent = client.name || contact.full_name || "Kandidat";
                if (els.summaryBereich) els.summaryBereich.textContent = profile.field || "Allgemein";
                if (els.summaryEmail) els.summaryEmail.textContent = contact.email || "";
                if (els.summaryWhatsapp) els.summaryWhatsapp.textContent = contact.phone || "";
                if (els.summaryDocuments) els.summaryDocuments.textContent = `${(client.documents || []).length} Dokumente`;
                if (els.applicationSummary) els.applicationSummary.hidden = false;

                // Candidate placeholders to inject into session
                const candidateFields = {
                    "Bewerber_Name": client.name || contact.full_name || "",
                    "Bewerber_Email": contact.email || "",
                    "Bewerber_Telefon": contact.phone || "",
                    "Bewerber_Strasse": contact.street || "",
                    "Bewerber_PLZ_Ort": `${contact.zip || ""} ${contact.city || ""}`.trim(),
                    "Bewerber_Titel": profile.target_title || profile.field || "",
                    "Bewerber_Erfahrung": profile.experience_years ? `${profile.experience_years} Jahre` : ""
                };

                // Add to state.columns if not present
                Object.keys(candidateFields).forEach((key) => {
                    if (!state.columns.includes(key)) {
                        state.columns.push(key);
                    }
                });

                // Update state.previewRows with candidate values
                if (Array.isArray(state.previewRows)) {
                    state.previewRows.forEach((row) => {
                        Object.assign(row, candidateFields);
                    });
                }

                // If active template is empty or default, provide a personalized intro
                if (els.templateEditor) {
                    let curText = els.templateEditor.value || "";
                    if (!curText.includes("{{Bewerber_Name}}") && (curText === defaultTemplate || !curText.trim())) {
                        els.templateEditor.value = `{{Bewerber_Name}}\n{{Bewerber_Strasse}}\n{{Bewerber_PLZ_Ort}}\n{{Bewerber_Telefon}} | {{Bewerber_Email}}\n\n` +
                            `{{Unternehmen}}\n{{Strasse}}\n{{PLZ}} {{Ort}}\n\n` +
                            `{{Ort}}, den {{heutigenDatum}}\n\n` +
                            `Bewerbung als {{Position}}\n\n` +
                            `Sehr geehrte Damen und Herren,\n\n` +
                            `mit großem Interesse bewerbe ich mich bei {{Unternehmen}} auf die ausgeschriebene Position als {{Position}}.\n\n` +
                            `Mit freundlichen Grüßen,\n{{Bewerber_Name}}`;
                        persistActiveTemplateValue();
                        renderTemplateList();
                    }
                }

                renderColumns(state.columns);
                renderPreview(state.previewRows);
                renderPlaceholders(state.columns);
                updateEditorStats();
                scheduleLivePreviewUpdate();

                // Sync candidate selection to active backend PDF session
                if (state.sessionId) {
                    fetch(`${API_BASE}/create-anschreibens/direct-jobs-bootstrap`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            session_id: state.sessionId,
                            client_id: clientId,
                            jobs: state.previewRows
                        })
                    }).catch(() => {});
                }

                showToast(`Kandidat ${client.name || clientId} für Anschreiben ausgewählt`);
            } catch (err) {
                showToast("Fehler beim Laden des Kandidatenprofils");
            }
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
            setSaveStatus(true);
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

        let currentTailoredBullets = [];

        function openAtsModal() {
            if (!els.atsModal) return;
            if (state.previewRows && state.previewRows.length > 0) {
                const firstRow = state.previewRows[0];
                const possibleCompany = firstRow["Unternehmen"] || firstRow["Firma"] || firstRow["Company"];
                if (possibleCompany && els.atsCompanyName) {
                    els.atsCompanyName.value = possibleCompany;
                }
                const possibleRole = firstRow["Beruf"] || firstRow["Stelle"] || firstRow["Job"] || firstRow["Position"];
                if (possibleRole && els.atsJobTitle) {
                    els.atsJobTitle.value = possibleRole;
                }
            }
            els.atsModal.hidden = false;
        }

        function closeAtsModal() {
            if (els.atsModal) els.atsModal.hidden = true;
        }

        async function runAtsTailoring() {
            if (!els.atsRunBtn) return;
            const jobTitle = (els.atsJobTitle?.value || "").trim();
            const companyName = (els.atsCompanyName?.value || "").trim();
            const jobRequirements = (els.atsRequirements?.value || "").trim();
            const currentBullets = (els.atsCustomBullets?.value || "").trim();

            els.atsRunBtn.disabled = true;
            els.atsRunBtn.innerHTML = "<span>⚡ Optimiere mit Luna...</span>";
            if (els.atsCostBadge) els.atsCostBadge.hidden = true;
            if (els.atsResultArea) els.atsResultArea.hidden = true;

            try {
                const data = await fetchJson("/api/pdf/ats-tailor", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        job_title: jobTitle,
                        company_name: companyName,
                        job_requirements: jobRequirements,
                        current_bullets: currentBullets,
                        profile_id: "anass_sibbi"
                    })
                });

                if (!data.success) {
                    throw new Error(data.error || "ATS-Optimierung fehlgeschlagen");
                }

                currentTailoredBullets = data.tailored_bullets || [];

                if (els.atsResultBullets) {
                    els.atsResultBullets.innerHTML = currentTailoredBullets
                        .map(b => `<div class="ats-bullet-item">• ${escapeHtml(b)}</div>`)
                        .join("");
                }

                if (els.atsCostBadge && els.atsCostText) {
                    els.atsCostBadge.hidden = false;
                    if (data.from_cache) {
                        els.atsCostBadge.className = "ats-cost-badge cached";
                        els.atsCostText.textContent = "⚡ 0 Tokens (Aus Cache - $0.00)";
                    } else {
                        const cost = data.usage?.estimated_cost_usd || 0.00003;
                        const tokens = data.usage?.total_tokens || 0;
                        els.atsCostBadge.className = "ats-cost-badge";
                        els.atsCostText.textContent = `⚡ ${tokens} Tokens | $${cost.toFixed(6)} USD`;
                    }
                }

                if (els.atsResultArea) els.atsResultArea.hidden = false;
                showToast("ATS-Keywords erfolgreich optimiert!");
            } catch (err) {
                showToast(err.message || "Fehler beim Anpassen");
            } finally {
                els.atsRunBtn.disabled = false;
                els.atsRunBtn.innerHTML = '<svg class="btn-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg><span>Keywords optimieren (~$0.00003)</span>';
            }
        }

        function insertTailoredBullets() {
            if (!currentTailoredBullets || !currentTailoredBullets.length) return;
            const formattedText = "\n" + currentTailoredBullets.map(b => `• ${b}`).join("\n") + "\n";
            const editor = els.templateEditor;
            if (!editor) return;

            const start = editor.selectionStart ?? editor.value.length;
            const end = editor.selectionEnd ?? editor.value.length;
            const before = editor.value.substring(0, start);
            const after = editor.value.substring(end);
            editor.value = before + formattedText + after;

            persistActiveTemplateValue();
            renderTemplateList();
            closeAtsModal();
            showToast("Stichpunkte ins Anschreiben eingefügt");
        }

        function copyTailoredBullets() {
            if (!currentTailoredBullets || !currentTailoredBullets.length) return;
            const formattedText = currentTailoredBullets.map(b => `• ${b}`).join("\n");
            navigator.clipboard.writeText(formattedText).then(() => {
                showToast("In Zwischenablage kopiert!");
            }).catch(() => {
                showToast("Kopieren fehlgeschlagen");
            });
        }

        let currentGoldenHook = "";

        function openGoldenHookModal() {
            if (!els.goldenHookModal) return;
            if (state.previewRows && state.previewRows.length > 0) {
                const firstRow = state.previewRows[0];
                const possibleCompany = firstRow["Unternehmen"] || firstRow["Firma"] || firstRow["Company"];
                if (possibleCompany && els.hookCompanyName) {
                    els.hookCompanyName.value = possibleCompany;
                }
                const possibleRole = firstRow["Beruf"] || firstRow["Stelle"] || firstRow["Job"] || firstRow["Position"];
                if (possibleRole && els.hookJobTitle) {
                    els.hookJobTitle.value = possibleRole;
                }
            }
            els.goldenHookModal.hidden = false;
        }

        function closeGoldenHookModal() {
            if (els.goldenHookModal) els.goldenHookModal.hidden = true;
        }

        async function runGoldenHook() {
            if (!els.hookRunBtn) return;
            const company = (els.hookCompanyName?.value || "").trim();
            const jobTitle = (els.hookJobTitle?.value || "").trim();
            const context = (els.hookContext?.value || "").trim();

            els.hookRunBtn.disabled = true;
            els.hookRunBtn.innerHTML = "<span>✨ Generiere Hook mit Luna...</span>";
            if (els.hookCostBadge) els.hookCostBadge.hidden = true;
            if (els.hookResultArea) els.hookResultArea.hidden = true;

            try {
                const data = await fetchJson("/api/pdf/golden-hook", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        company_name: company,
                        job_title: jobTitle,
                        job_requirements: context,
                        profile_id: "anass_sibbi"
                    })
                });

                if (!data.success) {
                    throw new Error(data.error || "Golden Hook Erstellung fehlgeschlagen");
                }

                currentGoldenHook = data.hook || "";
                if (els.hookResultText) {
                    els.hookResultText.textContent = `"${currentGoldenHook}"`;
                }

                if (els.hookCostBadge && els.hookCostText) {
                    els.hookCostBadge.hidden = false;
                    if (data.from_cache) {
                        els.hookCostBadge.className = "ats-cost-badge cached";
                        els.hookCostText.textContent = "⚡ 0 Tokens (Aus Cache - $0.00)";
                    } else {
                        const cost = data.usage?.estimated_cost_usd || 0.000015;
                        const tokens = data.usage?.total_tokens || 0;
                        els.hookCostBadge.className = "ats-cost-badge";
                        els.hookCostText.textContent = `⚡ ${tokens} Tokens | $${cost.toFixed(6)} USD`;
                    }
                }

                if (els.hookResultArea) els.hookResultArea.hidden = false;
                showToast("Golden Hook erfolgreich generiert!");
            } catch (err) {
                showToast(err.message || "Fehler beim Generieren");
            } finally {
                els.hookRunBtn.disabled = false;
                els.hookRunBtn.innerHTML = '<svg class="btn-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"></path></svg><span>Golden Hook generieren (~$0.000015)</span>';
            }
        }

        function insertGoldenHook() {
            if (!currentGoldenHook) return;
            const editor = els.templateEditor;
            if (!editor) return;

            const formattedText = currentGoldenHook + "\n\n";
            const start = editor.selectionStart ?? 0;
            const end = editor.selectionEnd ?? 0;
            const before = editor.value.substring(0, start);
            const after = editor.value.substring(end);
            editor.value = before + formattedText + after;

            persistActiveTemplateValue();
            renderTemplateList();
            closeGoldenHookModal();
            showToast("Golden Hook eingefügt");
        }

        function copyGoldenHook() {
            if (!currentGoldenHook) return;
            navigator.clipboard.writeText(currentGoldenHook).then(() => {
                showToast("In Zwischenablage kopiert!");
            }).catch(() => {
                showToast("Kopieren fehlgeschlagen");
            });
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

            state.activeBgTemplateId = null;
            uploadDesignPdf(file).catch((error) => {
                hideProgress();
                showInlineError(error.message || "Design-PDF Upload fehlgeschlagen");
                showToast(error.message || "Design-PDF Upload fehlgeschlagen");
            });
        }

        async function openBgTemplatesModal() {
            if (!els.bgTemplatesModal) return;
            els.bgTemplatesModal.hidden = false;
            await loadAndRenderBgTemplates();
        }

        function closeBgTemplatesModal() {
            if (els.bgTemplatesModal) {
                els.bgTemplatesModal.hidden = true;
            }
        }

        async function loadAndRenderBgTemplates() {
            if (!els.bgTemplatesList) return;
            if (!state.cachedBgTemplates) {
                els.bgTemplatesList.innerHTML = '<div class="bg-loading-state"><span class="spinner-ring"></span> Lade Vorlagen...</div>';
                try {
                    const data = await fetchJson(`${API_BASE}/pdf-background-templates`);
                    state.cachedBgTemplates = Array.isArray(data.templates) ? data.templates : [];
                } catch (e) {
                    els.bgTemplatesList.innerHTML = `<div class="bg-error-state">Vorlagen konnten nicht geladen werden: ${escapeHtml(e.message)}</div>`;
                    return;
                }
            }
            renderBgTemplatesList(state.cachedBgTemplates);
        }

        function renderBgTemplatesList(templates) {
            if (!els.bgTemplatesList) return;
            if (!templates || !templates.length) {
                els.bgTemplatesList.innerHTML = '<div class="empty-state">Keine Vorlagen verfügbar.</div>';
                return;
            }

            els.bgTemplatesList.innerHTML = templates.map((t) => {
                const isActive = state.activeBgTemplateId === t.id
                    || (state.designPdfName && state.designPdfName.toLowerCase().includes(t.name.toLowerCase()));
                return `
                    <div class="bg-template-card ${isActive ? 'is-active' : ''}" data-template-id="${escapeHtml(t.id)}">
                        <div class="bg-card-preview-wrap">
                            <div class="bg-mini-sheet" style="--p-color: ${t.primaryColor || '#4F46E5'}; --s-color: ${t.secondaryColor || '#818CF8'};">
                                <div class="bg-mini-header"></div>
                                <div class="bg-mini-accent"></div>
                                <div class="bg-mini-body">
                                    <span class="bg-mini-line w-80"></span>
                                    <span class="bg-mini-line w-60"></span>
                                    <span class="bg-mini-line w-90"></span>
                                    <span class="bg-mini-line w-70"></span>
                                    <span class="bg-mini-line w-50"></span>
                                </div>
                                <div class="bg-mini-din-mark mark-1"></div>
                                <div class="bg-mini-din-mark mark-2"></div>
                                <div class="bg-mini-din-mark mark-3"></div>
                                <div class="bg-mini-footer"></div>
                            </div>
                            ${isActive ? '<span class="bg-active-tag">✓ Aktiv</span>' : ''}
                        </div>
                        <div class="bg-card-info">
                            <div class="bg-card-top-row">
                                <span class="bg-category-badge">${escapeHtml(t.category || "Design")}</span>
                                <span class="bg-color-dot" style="background-color: ${t.primaryColor};" title="Primärfarbe: ${t.primaryColor}"></span>
                            </div>
                            <h4 class="bg-card-title">${escapeHtml(t.name)}</h4>
                            <p class="bg-card-desc">${escapeHtml(t.description || "")}</p>
                            <div class="bg-card-actions">
                                <a href="${API_BASE}/pdf-background-templates/${encodeURIComponent(t.id)}/pdf" target="_blank" class="bg-btn-preview" title="Vorlage in voller A4-Größe im neuen Tab ansehen">
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                                    Vorschau
                                </a>
                                <button type="button" class="bg-btn-select ${isActive ? 'is-selected' : ''}" data-action="select-template" data-template-id="${escapeHtml(t.id)}">
                                    ${isActive ? '✓ Ausgewählt' : 'Auswählen'}
                                </button>
                            </div>
                        </div>
                    </div>
                `;
            }).join("");

            els.bgTemplatesList.querySelectorAll('[data-action="select-template"]').forEach((btn) => {
                btn.addEventListener("click", async (e) => {
                    e.stopPropagation();
                    const templateId = btn.getAttribute("data-template-id");
                    if (templateId) {
                        await applyBgTemplate(templateId);
                    }
                });
            });

            els.bgTemplatesList.querySelectorAll('.bg-template-card').forEach((card) => {
                card.addEventListener("click", async (e) => {
                    if (e.target.closest('.bg-btn-preview')) return;
                    const templateId = card.getAttribute("data-template-id");
                    if (templateId) {
                        await applyBgTemplate(templateId);
                    }
                });
            });
        }

        async function applyBgTemplate(templateId) {
            if (!state.sessionId) {
                showToast(noDataMessage);
                return;
            }

            try {
                showProgress("Wende Hintergrund-Vorlage an...", 40);
                const res = await fetchJson(`${API_BASE}/set-background-template`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        session_id: state.sessionId,
                        template_id: templateId,
                    }),
                });

                state.activeBgTemplateId = templateId;
                setDesignFileState(res.filename || `Vorlage: ${templateId}`);

                if (res.recommendedMargins) {
                    const m = res.recommendedMargins;
                    if (els.marginTopInput && m.margin_top !== undefined) els.marginTopInput.value = m.margin_top;
                    if (els.marginLeftInput && m.margin_left !== undefined) els.marginLeftInput.value = m.margin_left;
                    if (els.marginRightInput && m.margin_right !== undefined) els.marginRightInput.value = m.margin_right;
                    if (els.marginBottomInput && m.margin_bottom !== undefined) els.marginBottomInput.value = m.margin_bottom;
                    if (els.textWidthInput && m.text_width !== undefined) els.textWidthInput.value = m.text_width;
                    if (els.textHeightInput && m.text_height !== undefined) els.textHeightInput.value = m.text_height;
                }

                closeBgTemplatesModal();
                showProgress("Vorlage aktiviert!", 100);
                window.setTimeout(hideProgress, 400);
                showToast(`Briefpapier "${res.template?.name || templateId}" erfolgreich aktiviert!`);
                updateReadiness();
                scheduleLivePreviewUpdate();
            } catch (err) {
                hideProgress();
                showToast(err.message || "Fehler beim Anwenden der Vorlage");
            }
        }

        async function clearBgTemplate() {
            if (!state.sessionId) {
                setDesignFileState("");
                state.activeBgTemplateId = null;
                closeBgTemplatesModal();
                updateReadiness();
                scheduleLivePreviewUpdate();
                return;
            }

            try {
                await fetchJson(`${API_BASE}/set-background-template`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        session_id: state.sessionId,
                        template_id: "none",
                    }),
                });

                state.activeBgTemplateId = null;
                setDesignFileState("");
                closeBgTemplatesModal();
                showToast("Hintergrund entfernt. Verwende Standard-Layout.");
                updateReadiness();
                scheduleLivePreviewUpdate();
            } catch (err) {
                showToast(err.message || "Fehler beim Entfernen");
            }
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
                if (bootstrap.applicationId && !bootstrap.editCampaignId && !bootstrap.autoloadSource) {
                    if (!bootstrap.application) {
                        try {
                            const cRes = await fetch(`/api/supabase/candidate-by-application/${encodeURIComponent(bootstrap.applicationId)}`);
                            if (cRes.ok) {
                                const cData = await cRes.json();
                                if (cData && cData.found && cData.client) {
                                    const c = cData.client;
                                    bootstrap.application = {
                                        id: bootstrap.applicationId,
                                        full_name: c.name || c.contact?.full_name || "",
                                        email: c.contact?.email || "",
                                        whatsapp: c.contact?.phone || "",
                                        field: c.profile?.field || "",
                                        bereich: c.profile?.field || "",
                                        pack: c.package?.name || "",
                                        source_label: `JobScout (${c.id})`,
                                        documents: (c.documents || []).map(d => ({
                                            path: d.filename || d.name,
                                            name: d.name || d.filename,
                                            is_cv: Boolean(d.is_cv)
                                        }))
                                    };
                                }
                            }
                        } catch (_) {}
                    }

                    if (bootstrap.application) {
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
                if (!bootstrap.application) {
                    try {
                        const cRes = await fetch(`/api/supabase/candidate-by-application/${encodeURIComponent(bootstrap.applicationId)}`);
                        if (cRes.ok) {
                            const cData = await cRes.json();
                            if (cData && cData.found && cData.client) {
                                const c = cData.client;
                                bootstrap.application = {
                                    id: bootstrap.applicationId,
                                    full_name: c.name || c.contact?.full_name || "",
                                    email: c.contact?.email || "",
                                    whatsapp: c.contact?.phone || "",
                                    field: c.profile?.field || "",
                                    bereich: c.profile?.field || "",
                                    pack: c.package?.name || "",
                                    source_label: `JobScout (${c.id})`,
                                    documents: (c.documents || []).map(d => ({
                                        path: d.filename || d.name,
                                        name: d.name || d.filename,
                                        is_cv: Boolean(d.is_cv)
                                    }))
                                };
                            }
                        }
                    } catch (_) {}
                }

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

            if (els.clientSelect) {
                els.clientSelect.addEventListener("change", (e) => {
                    onStudioClientSelected(e.target.value).catch(() => {});
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

            if (els.atsTailorBtn) els.atsTailorBtn.addEventListener("click", openAtsModal);
            if (els.closeAtsModalBtn) els.closeAtsModalBtn.addEventListener("click", closeAtsModal);
            if (els.atsRunBtn) els.atsRunBtn.addEventListener("click", runAtsTailoring);
            if (els.atsInsertBtn) els.atsInsertBtn.addEventListener("click", insertTailoredBullets);
            if (els.atsCopyBtn) els.atsCopyBtn.addEventListener("click", copyTailoredBullets);

            if (els.goldenHookBtn) els.goldenHookBtn.addEventListener("click", openGoldenHookModal);
            if (els.closeGoldenHookModalBtn) els.closeGoldenHookModalBtn.addEventListener("click", closeGoldenHookModal);
            if (els.hookRunBtn) els.hookRunBtn.addEventListener("click", runGoldenHook);
            if (els.hookInsertBtn) els.hookInsertBtn.addEventListener("click", insertGoldenHook);
            if (els.hookCopyBtn) els.hookCopyBtn.addEventListener("click", copyGoldenHook);

            if (els.modeBtns) {
                els.modeBtns.forEach((btn) => {
                    btn.addEventListener("click", () => setDisplayMode(btn.dataset.mode));
                });
            }

            if (els.duplicateTemplateBtn) {
                els.duplicateTemplateBtn.addEventListener("click", duplicateActiveTemplate);
            }

            if (els.renameTemplateBtn) {
                els.renameTemplateBtn.addEventListener("click", renameActiveTemplate);
            }

            if (els.placeholderToggle) {
                els.placeholderToggle.addEventListener("click", () => {
                    if (els.placeholderAccordion) {
                        els.placeholderAccordion.classList.toggle("is-collapsed");
                    }
                });
            }

            if (els.placeholderSearch) {
                els.placeholderSearch.addEventListener("input", applyPlaceholderFilter);
            }

            if (els.editorUndoBtn) {
                els.editorUndoBtn.addEventListener("click", editorUndo);
            }

            if (els.editorRedoBtn) {
                els.editorRedoBtn.addEventListener("click", editorRedo);
            }

            if (els.recordPrevBtn) {
                els.recordPrevBtn.addEventListener("click", prevPreviewRecord);
            }

            if (els.recordNextBtn) {
                els.recordNextBtn.addEventListener("click", nextPreviewRecord);
            }

            if (els.refreshPreviewBtn) {
                els.refreshPreviewBtn.addEventListener("click", () => {
                    updateLivePreview(state.previewRowIndex, false).catch(() => {});
                });
            }

            [
                els.fontSizeInput,
                els.lineHeightInput,
                els.marginTopInput,
                els.marginLeftInput,
                els.marginRightInput,
                els.marginBottomInput,
                els.textWidthInput,
                els.textHeightInput,
            ].forEach((inputEl) => {
                inputEl?.addEventListener("input", scheduleLivePreviewUpdate);
            });

            els.templateEditor.addEventListener("input", () => {
                persistActiveTemplateValue();
                renderTemplateList();
                updateEditorStats();
                setSaveStatus(false);
                pushHistory(els.templateEditor.value);
                scheduleLivePreviewUpdate();
            });

            els.templateEditor.addEventListener("keydown", (event) => {
                if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
                    event.preventDefault();
                    saveTemplate().catch((error) => {
                        showInlineError(error.message || "Vorlage konnte nicht gespeichert werden.");
                        showToast(error.message || "Vorlage konnte nicht gespeichert werden.");
                    });
                } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z" && !event.shiftKey) {
                    event.preventDefault();
                    editorUndo();
                } else if ((event.ctrlKey || event.metaKey) && (event.key.toLowerCase() === "y" || (event.key.toLowerCase() === "z" && event.shiftKey))) {
                    event.preventDefault();
                    editorRedo();
                }
            });

            els.formatToolbar.addEventListener("click", (event) => {
                const button = event.target.closest(".anschreiben-format-btn, .as-fmt-btn");
                if (!button || button.id === "as-editor-undo" || button.id === "as-editor-redo") {
                    return;
                }
                wrapSelection(button.dataset.prefix || "", button.dataset.suffix || "");
                persistActiveTemplateValue();
                renderTemplateList();
                setSaveStatus(false);
                pushHistory(els.templateEditor.value);
                scheduleLivePreviewUpdate();
            });

            if (els.bgTemplatesBtn) els.bgTemplatesBtn.addEventListener("click", openBgTemplatesModal);
            if (els.closeBgTemplatesBtn) els.closeBgTemplatesBtn.addEventListener("click", closeBgTemplatesModal);
            if (els.cancelBgModalBtn) els.cancelBgModalBtn.addEventListener("click", closeBgTemplatesModal);
            if (els.clearBgTemplateBtn) els.clearBgTemplateBtn.addEventListener("click", clearBgTemplate);
            if (els.removeDesignBtn) els.removeDesignBtn.addEventListener("click", clearBgTemplate);
            if (els.bgTemplatesModal) {
                els.bgTemplatesModal.addEventListener("click", (e) => {
                    if (e.target === els.bgTemplatesModal) closeBgTemplatesModal();
                });
            }

            window.addEventListener("keydown", (event) => {
                if (event.key === "Escape") {
                    closePreview();
                    closeAtsModal();
                    closeGoldenHookModal();
                    closeBgTemplatesModal();
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
            initDisplayMode();
            setLayoutInputs(defaultLayout);
            syncFilenameFormatDisplay("{{Unternehmen}}");
            loadActiveTemplateIntoEditor();
            renderPlaceholders(state.columns || []);
            updateEditorStats();
            setSaveStatus(true);
            updateReadiness();
            if (els.toEmailBtn && !transferEnabled) {
                els.toEmailBtn.hidden = true;
            }
            renderCachedApplicationDocuments();
            bindEvents();
        }

        return {
            show() {
                ensureInitialized();
                loadStudioClients().catch(() => {});

                // Check for direct session transferred from Search results
                const directSessionRaw = window.sessionStorage.getItem("anschreiben:direct-session");
                if (directSessionRaw) {
                    try {
                        window.sessionStorage.removeItem("anschreiben:direct-session");
                        const directSession = JSON.parse(directSessionRaw);
                        if (directSession && directSession.session_id) {
                            applyLoadedSession(directSession, directSession.display_name || "Direct from Search");
                            showToast(`⚡ ${directSession.row_count || directSession.preview?.length || 0} Stellen aus der Suche geladen`);
                            return;
                        }
                    } catch (_) {}
                }

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
                closeAtsModal();
                closeGoldenHookModal();
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

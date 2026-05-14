const API_BASE = '/api';

const state = {
    sessionId: null,
    editCampaignId: null,
    columns: [],
    previewRows: [],
    designPdfName: null,
    transferReadyCount: 0,
    templates: [''],
    activeTemplateIndex: 0,
};

const defaultTemplate = '';

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

const els = {
    dropZone: document.getElementById('dropZone'),
    fileInput: document.getElementById('fileInput'),
    designDropZone: document.getElementById('designDropZone'),
    designFileInput: document.getElementById('designFileInput'),
    designFileInfo: document.getElementById('designFileInfo'),
    designFileName: document.getElementById('designFileName'),
    fileInfo: document.getElementById('fileInfo'),
    fileName: document.getElementById('fileName'),
    rowCount: document.getElementById('rowCount'),
    columnList: document.getElementById('columnList'),
    dataPreview: document.getElementById('dataPreview'),
    previewTable: document.getElementById('previewTable'),
    placeholderTags: document.getElementById('placeholderTags'),
    templateEditor: document.getElementById('templateEditor'),
    validationResult: document.getElementById('validationResult'),
    filenameFormat: document.getElementById('filenameFormat'),
    fontSizeInput: document.getElementById('fontSizeInput'),
    lineHeightInput: document.getElementById('lineHeightInput'),
    marginTopInput: document.getElementById('marginTopInput'),
    marginLeftInput: document.getElementById('marginLeftInput'),
    marginRightInput: document.getElementById('marginRightInput'),
    marginBottomInput: document.getElementById('marginBottomInput'),
    textWidthInput: document.getElementById('textWidthInput'),
    textHeightInput: document.getElementById('textHeightInput'),
    resetLayoutBtn: document.getElementById('resetLayoutBtn'),
    saveTemplateBtn: document.getElementById('saveTemplateBtn'),
    resetTemplateBtn: document.getElementById('resetTemplateBtn'),
    addTemplateBtn: document.getElementById('addTemplateBtn'),
    deleteTemplateBtn: document.getElementById('deleteTemplateBtn'),
    templateList: document.getElementById('templateList'),
    previewBtn: document.getElementById('previewBtn'),
    generateBtn: document.getElementById('generateBtn'),
    toEmailBtn: document.getElementById('toEmailBtn'),
    progressArea: document.getElementById('progressArea'),
    progressFill: document.getElementById('progressFill'),
    progressText: document.getElementById('progressText'),
    previewModal: document.getElementById('previewModal'),
    pdfPreview: document.getElementById('pdfPreview'),
    closeModalBtn: document.getElementById('closeModalBtn'),
    closeFooterBtn: document.getElementById('closeFooterBtn'),
    toast: document.getElementById('toast'),
    formatToolbar: document.getElementById('formatToolbar'),
};

function ensureTemplateState() {
    if (!Array.isArray(state.templates) || !state.templates.length) {
        state.templates = [defaultTemplate];
    }
    if (state.activeTemplateIndex < 0 || state.activeTemplateIndex >= state.templates.length) {
        state.activeTemplateIndex = 0;
    }
}

function persistActiveTemplateValue() {
    ensureTemplateState();
    state.templates[state.activeTemplateIndex] = els.templateEditor.value || '';
}

function renderTemplateList() {
    ensureTemplateState();
    els.templateList.innerHTML = '';

    state.templates.forEach((template, index) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `template-chip${index === state.activeTemplateIndex ? ' active' : ''}${template.trim() ? '' : ' empty'}`;
        button.textContent = `Variante ${index + 1}${template.trim() ? '' : ' (leer)'}`;
        button.addEventListener('click', () => switchTemplate(index));
        els.templateList.appendChild(button);
    });

    els.deleteTemplateBtn.disabled = state.templates.length <= 1;
}

function loadActiveTemplateIntoEditor() {
    ensureTemplateState();
    els.templateEditor.value = state.templates[state.activeTemplateIndex] || '';
    renderTemplateList();
}

function switchTemplate(index) {
    persistActiveTemplateValue();
    state.activeTemplateIndex = index;
    loadActiveTemplateIntoEditor();
}

function addTemplate() {
    persistActiveTemplateValue();
    state.templates.push('');
    state.activeTemplateIndex = state.templates.length - 1;
    loadActiveTemplateIntoEditor();
}

function deleteActiveTemplate() {
    ensureTemplateState();
    if (state.templates.length <= 1) {
        state.templates[0] = '';
        state.activeTemplateIndex = 0;
    } else {
        state.templates.splice(state.activeTemplateIndex, 1);
        state.activeTemplateIndex = Math.max(0, state.activeTemplateIndex - 1);
    }
    loadActiveTemplateIntoEditor();
}

loadActiveTemplateIntoEditor();

function toNumber(value, fallback) {
    const n = Number.parseFloat(value);
    return Number.isFinite(n) ? n : fallback;
}

function setLayoutInputs(layout) {
    els.fontSizeInput.value = layout.font_size;
    els.lineHeightInput.value = layout.line_height;
    els.marginTopInput.value = layout.margin_top;
    els.marginLeftInput.value = layout.margin_left;
    els.marginRightInput.value = layout.margin_right;
    els.marginBottomInput.value = layout.margin_bottom;
    els.textWidthInput.value = layout.text_width;
    els.textHeightInput.value = layout.text_height;
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

setLayoutInputs(defaultLayout);

function showToast(message, timeout = 2600) {
    els.toast.textContent = message;
    els.toast.classList.remove('hidden');
    setTimeout(() => els.toast.classList.add('hidden'), timeout);
}

function wrapSelection(prefix, suffix) {
    const textarea = els.templateEditor;
    const start = textarea.selectionStart ?? 0;
    const end = textarea.selectionEnd ?? 0;
    const selectedText = textarea.value.slice(start, end);
    const replacement = `${prefix}${selectedText}${suffix}`;

    textarea.setRangeText(replacement, start, end, 'end');
    textarea.focus();

    const selectionStart = start + prefix.length;
    const selectionEnd = selectionStart + selectedText.length;
    textarea.setSelectionRange(selectionStart, selectionEnd);
}

function showProgress(message, percent = 0) {
    els.progressArea.classList.remove('hidden');
    els.progressText.textContent = message;
    els.progressFill.style.width = `${percent}%`;
}

function hideProgress() {
    els.progressArea.classList.add('hidden');
    els.progressFill.style.width = '0%';
}

function setValidation(type, message) {
    els.validationResult.className = 'validation-result';
    els.validationResult.classList.add(type);
    els.validationResult.textContent = message;
    els.validationResult.classList.remove('hidden');
}

function renderColumns(columns) {
    els.columnList.innerHTML = '';
    columns.forEach((col) => {
        const tag = document.createElement('span');
        tag.className = 'column-tag';
        tag.textContent = col;
        els.columnList.appendChild(tag);
    });

    const dynamicPlaceholders = columns.map((c) => `{{${c}}}`);
    const builtinPlaceholders = ['{{heutigenDatum}}'];
    els.placeholderTags.textContent = [...dynamicPlaceholders, ...builtinPlaceholders].join(' ');
}

function renderPreview(rows) {
    if (!rows.length) {
        els.dataPreview.classList.add('hidden');
        return;
    }

    const headers = Object.keys(rows[0]);
    const thead = `<thead><tr>${headers.map((h) => `<th>${h}</th>`).join('')}</tr></thead>`;
    const tbody = `<tbody>${rows
        .map((row) => `<tr>${headers.map((h) => `<td>${row[h] ?? ''}</td>`).join('')}</tr>`)
        .join('')}</tbody>`;

    els.previewTable.innerHTML = `<table>${thead}${tbody}</table>`;
    els.dataPreview.classList.remove('hidden');
}

function applyLoadedSession(data, displayName) {
    state.sessionId = data.session_id;
    state.editCampaignId = data.edit_campaign_id || null;
    state.columns = data.columns || [];
    state.previewRows = data.preview || [];
    state.transferReadyCount = 0;
    state.templates = Array.isArray(data.templates) && data.templates.length ? data.templates : [defaultTemplate];
    state.activeTemplateIndex = Number(data.active_template_index || 0);
    els.toEmailBtn.classList.add('hidden');
    setLayoutInputs(data.layout_options || defaultLayout);

    state.designPdfName = data.design_pdf_name || null;
    if (state.designPdfName) {
        els.designFileName.textContent = state.designPdfName;
        els.designFileInfo.classList.remove('hidden');
    } else {
        els.designFileInfo.classList.add('hidden');
        els.designFileName.textContent = '';
    }

    els.fileName.textContent = displayName;
    els.rowCount.textContent = data.row_count || state.previewRows.length || 0;
    els.fileInfo.classList.remove('hidden');

    renderColumns(state.columns);
    renderPreview(state.previewRows);
    loadActiveTemplateIntoEditor();
}

async function uploadExcel(file) {
    const formData = new FormData();
    formData.append('file', file);

    showProgress('Datei wird hochgeladen...', 20);

    const resp = await fetch(`${API_BASE}/upload-excel`, {
        method: 'POST',
        body: formData,
    });

    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Upload fehlgeschlagen');

    applyLoadedSession(data, file.name);

    showProgress('Upload erfolgreich', 100);
    setTimeout(hideProgress, 600);
    showToast('Datei erfolgreich hochgeladen');
}

async function autoloadCollectedJobs(source) {
    showProgress('Gesammelte Daten werden geladen...', 25);

    const resp = await fetch(`${API_BASE}/load-collected-jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: source || 'latest' }),
    });

    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || 'Automatisches Laden fehlgeschlagen');

    const src = data.source === 'manual' ? 'manual extraction' : data.source === 'auto' ? 'auto extraction' : 'collected';
    applyLoadedSession(data, `Collected jobs (${src})`);

    showProgress('Gesammelte Daten geladen', 100);
    setTimeout(hideProgress, 600);
    showToast('Collected data loaded automatically');
}

async function loadCampaignForEdit(campaignId) {
    showProgress('Gespeichertes Anschreiben wird geladen...', 25);

    const resp = await fetch(`${API_BASE}/campaign-anschreiben/${encodeURIComponent(campaignId)}`);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || 'Anschreiben konnte nicht geladen werden');

    applyLoadedSession(
        data,
        data.display_name || `Campaign ${campaignId}`
    );

    showProgress('Anschreiben geladen', 100);
    setTimeout(hideProgress, 600);
    showToast('Gespeichertes Anschreiben wurde geladen');
}

async function saveTemplate(options = {}) {
    const { silent = false } = options;
    if (!state.sessionId) {
        if (!silent) showToast('Bitte zuerst eine Datei hochladen');
        return;
    }

    persistActiveTemplateValue();

    const resp = await fetch(`${API_BASE}/save-template`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: state.sessionId,
            templates: state.templates,
            active_template_index: state.activeTemplateIndex,
        }),
    });

    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Template speichern fehlgeschlagen');

    if (data.missing_placeholders?.length) {
        setValidation('warn', `Unbekannte Platzhalter: ${data.missing_placeholders.join(', ')}`);
    } else {
        setValidation('ok', 'Vorlage gespeichert. Alle Platzhalter sind gültig.');
    }

    if (!silent) {
        showToast(`Vorlagen gespeichert (${data.template_count || state.templates.length})`);
    }
}

async function uploadDesignPdf(file) {
    if (!state.sessionId) {
        showToast('Bitte zuerst eine Datei hochladen');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);
    formData.append('session_id', state.sessionId);

    showProgress('Design-PDF wird hochgeladen...', 30);

    const resp = await fetch(`${API_BASE}/upload-design-pdf`, {
        method: 'POST',
        body: formData,
    });

    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Design-PDF Upload fehlgeschlagen');

    state.designPdfName = file.name;
    els.designFileName.textContent = file.name;
    els.designFileInfo.classList.remove('hidden');

    showProgress('Design-PDF gespeichert', 100);
    setTimeout(hideProgress, 500);
    showToast('Design-PDF erfolgreich hochgeladen');
}

async function previewPdf() {
    if (!state.sessionId) {
        showToast('Bitte zuerst eine Datei hochladen');
        return;
    }

    await saveTemplate({ silent: true });

    showProgress('Vorschau wird erstellt...', 45);

    const resp = await fetch(`${API_BASE}/preview-pdf`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: state.sessionId,
            row_index: 0,
            layout_options: getLayoutOptions(),
        }),
    });

    if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.error || 'Vorschau fehlgeschlagen');
    }

    const blob = await resp.blob();
    els.pdfPreview.src = URL.createObjectURL(blob);
    els.previewModal.classList.remove('hidden');

    showProgress('Vorschau bereit', 100);
    setTimeout(hideProgress, 500);
}

async function generatePdfs() {
    if (!state.sessionId) {
        showToast('Bitte zuerst eine Datei hochladen');
        return;
    }

    await saveTemplate({ silent: true });

    showProgress('PDFs werden generiert...', 35);

    const resp = await fetch(`${API_BASE}/generate-pdfs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: state.sessionId,
            layout_options: getLayoutOptions(),
        }),
    });

    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        throw new Error(data.error || 'Generierung fehlgeschlagen');
    }

    showProgress('PDFs gespeichert', 100);
    setTimeout(hideProgress, 500);
    const skipped = Number(data.skipped || 0);
    if (state.editCampaignId) {
        showToast(
            skipped > 0
                ? `Kampagne aktualisiert: ${data.count || 0} PDFs, ${skipped} Zeilen übersprungen`
                : 'Anschreiben für offene Empfänger aktualisiert'
        );
    } else if (skipped > 0) {
        showToast(`Fertig: ${data.count || 0} PDFs, ${skipped} Zeilen übersprungen`);
    } else {
        showToast(`Fertig: ${data.count || 0} PDFs in ${data.output_folder || 'Projektordner'}`);
    }
    state.transferReadyCount = Number(data.transfer_ready || 0);
    if (!state.editCampaignId && state.transferReadyCount > 0) {
        els.toEmailBtn.classList.remove('hidden');
    }
}

async function transferToEmailSender() {
    if (!state.sessionId) {
        showToast('Bitte zuerst eine Datei hochladen');
        return;
    }

    showProgress('Transfer zu Email Sender wird vorbereitet...', 40);
    const resp = await fetch(`${API_BASE}/prepare-email-transfer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: state.sessionId }),
    });

    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        throw new Error(data.error || 'Transfer fehlgeschlagen');
    }

    showProgress('Transfer bereit', 100);
    setTimeout(hideProgress, 300);
    window.location.href = data.redirect_url || '/send-emails';
}
async function updateFilenameFormat() {
    if (!state.sessionId) return;

    await fetch(`${API_BASE}/update-filename-format`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: state.sessionId,
            filename_format: els.filenameFormat.value || '{{Unternehmen}}',
        }),
    });
}

function closePreview() {
    els.previewModal.classList.add('hidden');
    els.pdfPreview.src = '';
}

function handleFiles(fileList) {
    const file = fileList?.[0];
    if (!file) return;

    if (!/\.(xlsx|xls|csv)$/i.test(file.name)) {
        showToast('Bitte eine Datei auswaehlen (.xlsx, .xls oder .csv)');
        return;
    }

    uploadExcel(file).catch((err) => {
        hideProgress();
        showToast(err.message || 'Upload fehlgeschlagen');
    });
}

function handleDesignFiles(fileList) {
    const file = fileList?.[0];
    if (!file) return;

    if (!/\.pdf$/i.test(file.name)) {
        showToast('Bitte eine PDF-Datei auswaehlen (.pdf)');
        return;
    }

    uploadDesignPdf(file).catch((err) => {
        hideProgress();
        showToast(err.message || 'Design-PDF Upload fehlgeschlagen');
    });
}

els.dropZone.addEventListener('click', () => els.fileInput.click());
els.fileInput.addEventListener('change', (e) => handleFiles(e.target.files));

['dragenter', 'dragover'].forEach((evt) => {
    els.dropZone.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        els.dropZone.classList.add('dragover');
    });
});

['dragleave', 'drop'].forEach((evt) => {
    els.dropZone.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        els.dropZone.classList.remove('dragover');
    });
});

els.dropZone.addEventListener('drop', (e) => handleFiles(e.dataTransfer.files));
els.designDropZone.addEventListener('click', () => els.designFileInput.click());
els.designFileInput.addEventListener('change', (e) => handleDesignFiles(e.target.files));

['dragenter', 'dragover'].forEach((evt) => {
    els.designDropZone.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        els.designDropZone.classList.add('dragover');
    });
});

['dragleave', 'drop'].forEach((evt) => {
    els.designDropZone.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        els.designDropZone.classList.remove('dragover');
    });
});

els.designDropZone.addEventListener('drop', (e) => handleDesignFiles(e.dataTransfer.files));
els.saveTemplateBtn.addEventListener('click', () => saveTemplate().catch((e) => showToast(e.message)));
els.resetTemplateBtn.addEventListener('click', () => {
    els.templateEditor.value = defaultTemplate;
    persistActiveTemplateValue();
    renderTemplateList();
    showToast('Aktive Variante geleert');
});
els.addTemplateBtn.addEventListener('click', () => {
    addTemplate();
    showToast('Neue Variante erstellt');
});
els.deleteTemplateBtn.addEventListener('click', () => {
    deleteActiveTemplate();
    showToast('Variante entfernt');
});
els.resetLayoutBtn.addEventListener('click', () => {
    setLayoutInputs(defaultLayout);
    showToast('Layout auf Standard zurückgesetzt');
});
els.previewBtn.addEventListener('click', () => previewPdf().catch((e) => {
    hideProgress();
    showToast(e.message);
}));
els.generateBtn.addEventListener('click', () => generatePdfs().catch((e) => {
    hideProgress();
    showToast(e.message);
}));
els.toEmailBtn.addEventListener('click', () => transferToEmailSender().catch((e) => {
    hideProgress();
    showToast(e.message);
}));
els.filenameFormat.addEventListener('blur', () => updateFilenameFormat().catch(() => {}));
els.closeModalBtn.addEventListener('click', closePreview);
els.closeFooterBtn.addEventListener('click', closePreview);
window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closePreview();
});
window.addEventListener('beforeunload', () => {
    if (state.sessionId) {
        fetch(`${API_BASE}/clear-session/${state.sessionId}`, { method: 'DELETE', keepalive: true }).catch(() => {});
    }
});

els.formatToolbar?.addEventListener('click', (event) => {
    const button = event.target.closest('.format-btn');
    if (!button) {
        return;
    }
    wrapSelection(button.dataset.prefix || '', button.dataset.suffix || '');
    persistActiveTemplateValue();
    renderTemplateList();
});

els.templateEditor.addEventListener('input', () => {
    persistActiveTemplateValue();
    renderTemplateList();
});

const pageParams = new URLSearchParams(window.location.search);
const editCampaignId = pageParams.get('edit_campaign');
const autoloadSource = pageParams.get('autoload');
if (editCampaignId) {
    loadCampaignForEdit(editCampaignId).catch((err) => {
        hideProgress();
        showToast(err.message || 'Campaign load failed');
    });
} else if (autoloadSource) {
    autoloadCollectedJobs(autoloadSource).catch((err) => {
        hideProgress();
        showToast(err.message || 'Auto-load failed');
    });
}



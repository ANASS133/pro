(function () {
    const sections = window.SPASections || {};

    sections.createSendEmailsSection = function createSendEmailsSection() {
        const form = document.getElementById('send-emails-bulkForm');
        const resultDiv = document.getElementById('send-emails-result');
        const sendBtn = document.getElementById('send-emails-sendBtn');
        const saveTemplateBtn = document.getElementById('send-emails-saveTemplateBtn');
        const stopSendBtn = document.getElementById('send-emails-stopSendBtn');
        const campaignIdInput = form.querySelector('input[name="campaign_id"]');
        const transferIdInput = form.querySelector('input[name="transfer_session_id"]');
        const dataFileInput = document.getElementById('send-emails-data_file');
        const dataFileName = document.getElementById('send-emails-data_file_name');
        const attachmentsInput = document.getElementById('send-emails-attachments');
        const attachmentsName = document.getElementById('send-emails-attachments_name');
        const oneDocumentToggle = document.getElementById('send-emails-one_document_enabled');
        const oneDocumentFields = document.getElementById('send-emails-oneDocumentFields');
        const oneDocumentBaseInput = document.getElementById('send-emails-one_document_base_file');
        const oneDocumentBaseName = document.getElementById('send-emails-one_document_base_file_name');
        const sendProgressDock = document.getElementById('send-emails-sendProgressDock');
        const sendProgressText = document.getElementById('send-emails-sendProgressText');
        const sendProgressFill = document.getElementById('send-emails-sendProgressFill');
        const dayPresetSelect = document.getElementById('send-emails-day_preset');
        const errorDiv = document.getElementById('send-emails-error');
        const transferBox = document.getElementById('send-emails-transfer-box');
        const campaignBox = document.getElementById('send-emails-campaign-box');
        const deleteCampaignBtn = document.getElementById('send-emails-deleteCampaignBtn');

        if (!form || !resultDiv || !sendBtn) {
            return {
                show() {},
                hide() {},
            };
        }

        let sendJobPoll = null;
        let activeSendJobId = '';
        const escapeHtml = window.SPAUtils?.escapeHtml || ((value) => String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;'));
        const SEND_FORM_STATE_KEY = 'aa_send_form_state_v1';
        const SEND_RESULT_FLASH_KEY = 'aa_send_result_flash_v1';
        const DAY_PRESETS = {
            day1: {
                limit: '100',
                jitter_min_seconds: '90',
                jitter_max_seconds: '140',
                batch_size: '10',
                batch_pause_minutes: '35'
            },
            day2: {
                limit: '200',
                jitter_min_seconds: '85',
                jitter_max_seconds: '130',
                batch_size: '15',
                batch_pause_minutes: '30'
            },
            day3: {
                limit: '300',
                jitter_min_seconds: '80',
                jitter_max_seconds: '120',
                batch_size: '20',
                batch_pause_minutes: '25'
            },
            day4: {
                limit: '500',
                jitter_min_seconds: '75',
                jitter_max_seconds: '110',
                batch_size: '20',
                batch_pause_minutes: '20'
            }
        };

        function updateFileLabel(inputEl, outputEl, isMultiple = false) {
            const files = Array.from(inputEl.files || []);
            if (!files.length) {
                outputEl.textContent = 'Keine Datei ausgew\u00E4hlt';
                outputEl.title = '';
                return;
            }

            if (!isMultiple) {
                outputEl.textContent = files[0].name;
                outputEl.title = files[0].name;
                return;
            }

            const names = files.map((file) => file.name);
            const shortText = names.length <= 2
                ? names.join(', ')
                : `${names.slice(0, 2).join(', ')} +${names.length - 2} weitere`;
            outputEl.textContent = shortText;
            outputEl.title = names.join(', ');
        }

        dataFileInput.addEventListener('change', () => updateFileLabel(dataFileInput, dataFileName));
        attachmentsInput.addEventListener('change', () => updateFileLabel(attachmentsInput, attachmentsName, true));
        if (oneDocumentBaseInput && oneDocumentBaseName) {
            oneDocumentBaseInput.addEventListener('change', () => {
                updateFileLabel(oneDocumentBaseInput, oneDocumentBaseName);
            });
        }

        function syncOneDocumentFields() {
            if (!oneDocumentToggle || !oneDocumentFields) {
                return;
            }
            oneDocumentFields.hidden = !oneDocumentToggle.checked;
        }

        if (oneDocumentToggle) {
            oneDocumentToggle.addEventListener('change', () => {
                syncOneDocumentFields();
                saveSendFormState();
            });
        }

        function setLoadedCampaignDeleteState(isSending) {
            if (!deleteCampaignBtn) {
                return;
            }

            const hasCampaignId = Boolean(String(campaignIdInput?.value || '').trim());
            deleteCampaignBtn.disabled = !hasCampaignId || isSending;
            deleteCampaignBtn.textContent = isSending ? 'Versand aktiv' : 'Vorlage löschen';
            deleteCampaignBtn.title = isSending
                ? 'Laufenden Versand zuerst stoppen oder abschließen'
                : '';
        }

        function consumeTransientResult() {
            const raw = sessionStorage.getItem(SEND_RESULT_FLASH_KEY);
            if (!raw) {
                return;
            }

            sessionStorage.removeItem(SEND_RESULT_FLASH_KEY);
            try {
                const payload = JSON.parse(raw);
                if (!payload || !payload.message) {
                    return;
                }
                resultDiv.className = `result ${payload.level === 'error' ? 'error' : 'success'}`;
                resultDiv.textContent = payload.message;
                resultDiv.style.display = 'block';
            } catch (_error) {
                // ignore invalid transient payload
            }
        }

        function saveSendFormState() {
            const state = {
                full_name: document.getElementById('send-emails-full_name')?.value || '',
                sender_email: document.getElementById('send-emails-sender_email')?.value || '',
                recipient_column: document.getElementById('send-emails-recipient_column')?.value || '',
                limit: document.getElementById('send-emails-limit')?.value || '',
                day_preset: dayPresetSelect?.value || '',
                jitter_min_seconds: document.getElementById('send-emails-jitter_min_seconds')?.value || '',
                jitter_max_seconds: document.getElementById('send-emails-jitter_max_seconds')?.value || '',
                batch_size: document.getElementById('send-emails-batch_size')?.value || '',
                batch_pause_minutes: document.getElementById('send-emails-batch_pause_minutes')?.value || '',
                one_document_enabled: oneDocumentToggle?.checked ? '1' : '',
                one_document_page: document.getElementById('send-emails-one_document_page')?.value || '',
                one_document_action: document.getElementById('send-emails-one_document_action')?.value || 'replace',
                subject_template: document.getElementById('send-emails-subject_template')?.value || '',
                body_template: document.getElementById('send-emails-body_template')?.value || ''
            };
            localStorage.setItem(SEND_FORM_STATE_KEY, JSON.stringify(state));
        }

        function setInputValueIfEmpty(element, value) {
            if (!element) {
                return false;
            }
            const normalizedValue = String(value || '').trim();
            if (!normalizedValue || String(element.value || '').trim()) {
                return false;
            }
            element.value = normalizedValue;
            return true;
        }

        function setTextareaValueIfEmpty(element, value) {
            if (!element) {
                return false;
            }
            const normalizedValue = String(value || '');
            if (!normalizedValue.trim() || String(element.value || '').trim()) {
                return false;
            }
            element.value = normalizedValue;
            return true;
        }

        function applyTransferDefaults(transferInfo) {
            const fullNameInput = document.getElementById('send-emails-full_name');
            const senderEmailInput = document.getElementById('send-emails-sender_email');
            const subjectInput = document.getElementById('send-emails-subject_template');
            const bodyInput = document.getElementById('send-emails-body_template');

            const fullNameApplied = setInputValueIfEmpty(fullNameInput, transferInfo.full_name);
            const senderApplied = setInputValueIfEmpty(senderEmailInput, transferInfo.sender_email);
            const subjectApplied = setInputValueIfEmpty(subjectInput, transferInfo.email_subject_template);
            const bodyApplied = setTextareaValueIfEmpty(bodyInput, transferInfo.email_body_template);

            if (fullNameApplied || senderApplied || subjectApplied || bodyApplied) {
                saveSendFormState();
            }
        }

        function applyDayPreset(presetKey) {
            const preset = DAY_PRESETS[presetKey];
            if (!preset) {
                return;
            }

            Object.entries(preset).forEach(([id, value]) => {
                const el = document.getElementById(`send-emails-${id}`);
                if (el) {
                    el.value = value;
                }
            });
        }

        function detectDayPresetFromInputs() {
            const currentValues = {
                limit: document.getElementById('send-emails-limit')?.value || '',
                jitter_min_seconds: document.getElementById('send-emails-jitter_min_seconds')?.value || '',
                jitter_max_seconds: document.getElementById('send-emails-jitter_max_seconds')?.value || '',
                batch_size: document.getElementById('send-emails-batch_size')?.value || '',
                batch_pause_minutes: document.getElementById('send-emails-batch_pause_minutes')?.value || ''
            };

            const matchingPreset = Object.entries(DAY_PRESETS).find(([, preset]) =>
                Object.entries(preset).every(([key, value]) => currentValues[key] === value)
            );

            return matchingPreset ? matchingPreset[0] : '';
        }

        function restoreSendFormState() {
            const raw = localStorage.getItem(SEND_FORM_STATE_KEY);
            if (!raw) {
                if (dayPresetSelect) {
                    dayPresetSelect.value = detectDayPresetFromInputs();
                }
                syncOneDocumentFields();
                return;
            }
            try {
                const state = JSON.parse(raw);
                Object.entries(state).forEach(([id, value]) => {
                    if (id === 'one_document_enabled') {
                        if (oneDocumentToggle) {
                            oneDocumentToggle.checked = Boolean(value);
                        }
                        return;
                    }
                    const el = document.getElementById(`send-emails-${id}`);
                    if (!el || el.value) {
                        return;
                    }
                    el.value = typeof value === 'string' ? value : '';
                });
                syncOneDocumentFields();
                if (dayPresetSelect && !dayPresetSelect.value) {
                    dayPresetSelect.value = detectDayPresetFromInputs();
                }
            } catch (_error) {
                // ignore bad local state
            }
        }

        function bindSendFormState() {
            ['full_name', 'sender_email', 'recipient_column', 'limit', 'day_preset', 'jitter_min_seconds', 'jitter_max_seconds', 'batch_size', 'batch_pause_minutes', 'one_document_page', 'one_document_action', 'subject_template', 'body_template'].forEach((id) => {
                const el = document.getElementById(`send-emails-${id}`);
                if (!el) {
                    return;
                }
                el.addEventListener('input', saveSendFormState);
                el.addEventListener('change', saveSendFormState);
            });
        }

        if (dayPresetSelect) {
            dayPresetSelect.addEventListener('change', () => {
                applyDayPreset(dayPresetSelect.value);
                saveSendFormState();
            });
        }

        function setSendingUiActive() {
            sendBtn.disabled = true;
            saveTemplateBtn.disabled = true;
            sendBtn.textContent = 'Wird gesendet...';
            stopSendBtn.style.display = 'block';
            stopSendBtn.disabled = false;
            stopSendBtn.textContent = 'Speichern und stoppen';
            sendProgressDock.classList.add('visible');
            setLoadedCampaignDeleteState(true);
        }

        function resetSendingUi() {
            sendBtn.disabled = false;
            saveTemplateBtn.disabled = false;
            sendBtn.textContent = 'Massenversand starten';
            stopSendBtn.style.display = 'none';
            stopSendBtn.disabled = false;
            stopSendBtn.textContent = 'Speichern und stoppen';
            setLoadedCampaignDeleteState(false);
        }

        async function saveTemplateToDashboard() {
            resultDiv.style.display = 'none';
            saveTemplateBtn.disabled = true;
            const previousLabel = saveTemplateBtn.textContent;
            saveTemplateBtn.textContent = 'Speichert...';

            try {
                const formData = new FormData(form);
                const response = await fetch('/api/campaign/save', {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.message || 'Vorlage konnte nicht gespeichert werden');
                }

                if (data.campaign_id && campaignIdInput) {
                    campaignIdInput.value = data.campaign_id;
                    const currentUrl = new URL(window.location.href);
                    currentUrl.searchParams.set('campaign', data.campaign_id);
                    currentUrl.searchParams.delete('transfer');
                    window.history.replaceState({}, '', currentUrl.toString());
                }

                saveSendFormState();
                resultDiv.className = 'result success';
                resultDiv.textContent = data.message || 'Vorlage gespeichert.';
                resultDiv.style.display = 'block';
            } catch (saveError) {
                resultDiv.className = 'result error';
                resultDiv.textContent = saveError.message || 'Vorlage konnte nicht gespeichert werden.';
                resultDiv.style.display = 'block';
            } finally {
                saveTemplateBtn.disabled = false;
                saveTemplateBtn.textContent = previousLabel;
            }
        }

        function attachToSendJob(jobId) {
            activeSendJobId = String(jobId || '').trim();
            if (!activeSendJobId) {
                return;
            }
            setSendingUiActive();
            if (sendJobPoll) {
                clearInterval(sendJobPoll);
            }
            sendJobPoll = setInterval(async () => {
                try {
                    await pollSendJobStatus();
                } catch (pollError) {
                    if (sendJobPoll) {
                        clearInterval(sendJobPoll);
                        sendJobPoll = null;
                    }
                    resetSendingUi();
                    resultDiv.className = 'result error';
                    resultDiv.textContent = pollError.message || 'Versandfortschritt konnte nicht geladen werden.';
                    resultDiv.style.display = 'block';
                }
            }, 1500);
        }

        function updateSendProgress(job) {
            const total = Number(job.total || 0);
            const processed = Number(job.processed || 0);
            const sentSuccess = Number(job.sent_success || 0);
            const percent = Math.max(0, Math.min(100, Number(job.percent || 0)));
            const stageMessage = (job.message || '').trim();
            const remainingSeconds = Number(job.estimated_remaining_seconds);

            function formatEta(seconds) {
                if (!Number.isFinite(seconds) || seconds < 0) {
                    return '';
                }
                if (seconds < 60) {
                    return `${Math.round(seconds)}s`;
                }
                const hours = Math.floor(seconds / 3600);
                const minutes = Math.floor((seconds % 3600) / 60);
                const secs = Math.round(seconds % 60);
                if (hours > 0) {
                    return `${hours}h ${minutes}m`;
                }
                if (minutes > 0) {
                    return `${minutes}m ${secs}s`;
                }
                return `${secs}s`;
            }

            sendProgressDock.classList.add('visible');
            sendProgressFill.style.width = `${percent}%`;
            const etaText = total > processed && Number.isFinite(remainingSeconds)
                ? ` | ETA ${formatEta(remainingSeconds)}`
                : '';
            const base = `Gesendet ${sentSuccess}/${total} | Verarbeitet ${processed}/${total} | ${percent.toFixed(1)}%${etaText}`;
            sendProgressText.textContent = stageMessage ? `${base} | ${stageMessage}` : base;
        }

        async function pollSendJobStatus() {
            if (!activeSendJobId) {
                return;
            }
            const response = await fetch(`/api/send-bulk/status/${activeSendJobId}`);
            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.message || 'Versandfortschritt konnte nicht geladen werden');
            }

            const job = data.job || {};
            updateSendProgress(job);

            if (job.campaign_id && campaignIdInput) {
                campaignIdInput.value = job.campaign_id;
                const currentUrl = new URL(window.location.href);
                currentUrl.searchParams.set('campaign', job.campaign_id);
                currentUrl.searchParams.delete('transfer');
                window.history.replaceState({}, '', currentUrl.toString());
            }

            if (job.status === 'completed' || job.status === 'failed') {
                if (sendJobPoll) {
                    clearInterval(sendJobPoll);
                    sendJobPoll = null;
                }
                activeSendJobId = '';
                resetSendingUi();
                resultDiv.className = `result ${job.success ? 'success' : 'error'}`;
                resultDiv.textContent = job.message || 'Versandauftrag abgeschlossen.';
                resultDiv.style.display = 'block';
            }
        }

        async function restoreActiveSendJobForCampaign() {
            const campaignId = String(campaignIdInput?.value || '').trim();
            if (!campaignId) {
                return;
            }

            const response = await fetch(`/api/send-bulk/active?campaign_id=${encodeURIComponent(campaignId)}`);
            const data = await response.json();
            if (!response.ok || !data.success || !data.job || !data.job.job_id) {
                return;
            }

            attachToSendJob(data.job.job_id);
            await pollSendJobStatus();
        }

        async function deleteLoadedCampaign() {
            const campaignId = String(campaignIdInput?.value || '').trim();
            if (!campaignId) {
                return;
            }
            if (!window.confirm('Diese gespeicherte Vorlage löschen? Das kann nicht rückgängig gemacht werden.')) {
                return;
            }

            resultDiv.style.display = 'none';
            const previousLabel = deleteCampaignBtn.textContent;
            deleteCampaignBtn.disabled = true;
            deleteCampaignBtn.textContent = 'Loescht...';

            try {
                const response = await fetch(`/api/campaign/delete/${encodeURIComponent(campaignId)}`, {
                    method: 'POST'
                });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.message || 'Vorlage konnte nicht gelöscht werden');
                }

                sessionStorage.setItem(SEND_RESULT_FLASH_KEY, JSON.stringify({
                    level: 'success',
                    message: data.message || 'Vorlage wurde gelöscht.'
                }));

                const currentUrl = new URL(window.location.href);
                currentUrl.searchParams.delete('campaign');
                window.location.href = currentUrl.toString();
            } catch (deleteError) {
                resultDiv.className = 'result error';
                resultDiv.textContent = deleteError.message || 'Vorlage konnte nicht gelöscht werden.';
                resultDiv.style.display = 'block';
                deleteCampaignBtn.textContent = previousLabel;
                setLoadedCampaignDeleteState(Boolean(activeSendJobId));
            }
        }

        async function loadCampaignData() {
            const urlParams = new URLSearchParams(window.location.search);
            const transferId = (urlParams.get('transfer') || '').trim();
            const campaignId = (urlParams.get('campaign') || '').trim();

            if (!transferId && !campaignId) {
                return;
            }

            try {
                const query = transferId 
                    ? `?transfer=${encodeURIComponent(transferId)}`
                    : `?campaign=${encodeURIComponent(campaignId)}`;
                
                const response = await fetch(`/api/send-emails/campaigns${query}`);
                const data = await response.json();

                if (!response.ok || !data.success) {
                    if (data.transfer_error) {
                        errorDiv.textContent = data.transfer_error;
                        errorDiv.hidden = false;
                    }
                    if (data.campaign_error) {
                        errorDiv.textContent = data.campaign_error;
                        errorDiv.hidden = false;
                    }
                    return;
                }

                if (data.campaign_info) {
                    renderCampaignInfo(data.campaign_info, data.active_send_job);
                } else if (data.transfer_info) {
                    renderTransferInfo(data.transfer_info);
                }
            } catch (error) {
                errorDiv.textContent = 'Fehler beim Laden der Kampagnendaten: ' + error.message;
                errorDiv.hidden = false;
            }
        }

        function renderCampaignInfo(campaignInfo, activeSendJob) {
            campaignIdInput.value = campaignInfo.id || '';
            dataFileInput.disabled = true;
            dataFileName.textContent = `${campaignInfo.total_rows} Empf\u00E4nger geladen`;

            const html = `
                <div class="campaign-box-head">
                    <div>
                        <strong>Gespeicherte Vorlage geladen:</strong> ${campaignInfo.name}<br>
                        Fortschritt: ${campaignInfo.sent_rows}/${campaignInfo.total_rows} gesendet, ${campaignInfo.remaining_rows} offen.
                        ${campaignInfo.one_document?.enabled ? `<br>One Document Mode: ${campaignInfo.one_document.action === 'add' ? 'Add' : 'Replace'} auf Seite ${campaignInfo.one_document.page || 1}${campaignInfo.one_document.base_filename ? ` | ${escapeHtml(campaignInfo.one_document.base_filename)}` : ''}` : ''}
                    </div>
                    <button
                        class="btn btn-danger btn-inline"
                        type="button"
                        id="send-emails-deleteCampaignBtn"
                        ${activeSendJob ? 'disabled title="Laufenden Versand zuerst stoppen oder abschließen"' : ''}
                    >
                        ${activeSendJob ? 'Versand aktiv' : 'Vorlage löschen'}
                    </button>
                </div>
                ${campaignInfo.preview ? `
                    <ul class="campaign-list">
                        ${campaignInfo.preview.map(row => `<li>Zeile ${row.row_index} | ${row.recipient} | ${row.company}</li>`).join('')}
                    </ul>
                ` : ''}
            `;
            campaignBox.innerHTML = html;
            campaignBox.hidden = false;

            const newDeleteBtn = document.getElementById('send-emails-deleteCampaignBtn');
            if (newDeleteBtn) {
                newDeleteBtn.addEventListener('click', () => deleteLoadedCampaign());
            }

            if (campaignInfo.full_name) {
                setInputValueIfEmpty(document.getElementById('send-emails-full_name'), campaignInfo.full_name);
            }
            if (campaignInfo.sender_email) {
                setInputValueIfEmpty(document.getElementById('send-emails-sender_email'), campaignInfo.sender_email);
            }
            if (campaignInfo.recipient_column) {
                setInputValueIfEmpty(document.getElementById('send-emails-recipient_column'), campaignInfo.recipient_column);
            }
            if (campaignInfo.subject_template) {
                setInputValueIfEmpty(document.getElementById('send-emails-subject_template'), campaignInfo.subject_template);
            }
            if (campaignInfo.body_template) {
                setTextareaValueIfEmpty(document.getElementById('send-emails-body_template'), campaignInfo.body_template);
            }
            if (campaignInfo.one_document) {
                const oneDocumentInfo = campaignInfo.one_document;
                if (oneDocumentToggle) {
                    oneDocumentToggle.checked = Boolean(oneDocumentInfo.enabled);
                }
                const pageInput = document.getElementById('send-emails-one_document_page');
                if (pageInput && oneDocumentInfo.page) {
                    pageInput.value = String(oneDocumentInfo.page);
                }
                const actionInput = document.getElementById('send-emails-one_document_action');
                if (actionInput && oneDocumentInfo.action) {
                    actionInput.value = String(oneDocumentInfo.action);
                }
                if (oneDocumentBaseName && oneDocumentInfo.base_filename) {
                    oneDocumentBaseName.textContent = `Gespeichert: ${oneDocumentInfo.base_filename}`;
                    oneDocumentBaseName.title = oneDocumentInfo.base_filename;
                }
                syncOneDocumentFields();
            }

            saveSendFormState();

            if (activeSendJob && activeSendJob.job_id) {
                attachToSendJob(activeSendJob.job_id);
            }
        }

        function renderTransferInfo(transferInfo) {
            transferIdInput.value = transferInfo.id || '';
            dataFileInput.disabled = true;
            dataFileName.textContent = `${transferInfo.total_rows} Empf\u00E4nger geladen`;

            const html = `
                <strong>Transfer aus Anschreiben geladen:</strong> ${transferInfo.total_rows} Empf\u00E4nger mit zugeordneten PDF-Dateien.
                ${transferInfo.preview ? `
                    <ul class="transfer-list">
                        ${transferInfo.preview.map(row => `<li>${row.recipient} | ${row.company || 'k. A.'} | ${row.filename}</li>`).join('')}
                    </ul>
                ` : ''}
            `;
            transferBox.innerHTML = html;
            transferBox.hidden = false;

            applyTransferDefaults(transferInfo);
        }

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            setSendingUiActive();
            resultDiv.style.display = 'none';
            sendProgressDock.classList.add('visible');
            sendProgressText.textContent = 'Versandauftrag wird gestartet...';
            sendProgressFill.style.width = '0%';

            try {
                const formData = new FormData(form);
                const response = await fetch('/api/send-bulk/start', {
                    method: 'POST',
                    body: formData
                });

                const data = await response.json();
                if (!response.ok || !data.success || !data.job_id) {
                    throw new Error(data.message || 'Versandauftrag konnte nicht gestartet werden');
                }

                attachToSendJob(data.job_id);
                saveSendFormState();
                await pollSendJobStatus();
            } catch (_error) {
                resultDiv.className = 'result error';
                resultDiv.textContent = _error.message || 'Netzwerkfehler. Bitte erneut versuchen.';
                resultDiv.style.display = 'block';
                resetSendingUi();
            }
        });

        stopSendBtn.addEventListener('click', async () => {
            if (!activeSendJobId) {
                return;
            }
            stopSendBtn.disabled = true;
            stopSendBtn.textContent = 'Stoppe...';

            try {
                const response = await fetch(`/api/send-bulk/stop/${activeSendJobId}`, {
                    method: 'POST'
                });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.message || 'Stoppen konnte nicht angefordert werden');
                }
            } catch (stopError) {
                stopSendBtn.disabled = false;
                stopSendBtn.textContent = 'Speichern und stoppen';
                resultDiv.className = 'result error';
                resultDiv.textContent = stopError.message || 'Stoppen konnte nicht angefordert werden.';
                resultDiv.style.display = 'block';
            }
        });

        saveTemplateBtn.addEventListener('click', () => {
            saveTemplateToDashboard().catch(() => {});
        });

        return {
            show() {
                consumeTransientResult();
                restoreSendFormState();
                bindSendFormState();
                loadCampaignData().catch(() => {});
            },
            hide() {
                if (sendJobPoll) {
                    clearInterval(sendJobPoll);
                    sendJobPoll = null;
                }
            },
        };
    };

    window.SPASections = sections;
})();

(function () {
    const sections = window.SPASections || {};

    sections.createSendEmailsSection = function createSendEmailsSection() {
        const form = document.getElementById('send-emails-bulkForm');
        const resultDiv = document.getElementById('send-emails-result');
        const sendBtn = document.getElementById('send-emails-sendBtn');
        const saveTemplateBtn = document.getElementById('send-emails-saveTemplateBtn');
        const stopSendBtn = document.getElementById('send-emails-stopSendBtn');
        const campaignIdInput = form ? form.querySelector('input[name="campaign_id"]') : null;
        const transferIdInput = form ? form.querySelector('input[name="transfer_session_id"]') : null;
        const dataFileInput = document.getElementById('send-emails-data_file');
        const dataFileName = document.getElementById('send-emails-data_file_name');
        const dropzone = document.getElementById('send-emails-dropzone');
        const dropzonePrompt = document.getElementById('cb-dropzone-prompt');
        const fileLoadedState = document.getElementById('cb-file-loaded-state');
        const fileMetaSummary = document.getElementById('cb-file-meta-summary');
        const fileStatsGrid = document.getElementById('cb-file-stats-grid');
        const statTotalRows = document.getElementById('stat-total-rows');
        const statValidEmails = document.getElementById('stat-valid-emails');
        const statDuplicateEmails = document.getElementById('stat-duplicate-emails');
        const statTotalColumns = document.getElementById('stat-total-columns');
        const recipientColumnInput = document.getElementById('send-emails-recipient_column');
        const columnChipsContainer = document.getElementById('cb-column-chips');
        const previewTable = document.getElementById('cb-preview-table');
        const previewTableHead = document.getElementById('cb-preview-table-head');
        const previewTableBody = document.getElementById('cb-preview-table-body');
        const tableEmptyState = document.getElementById('cb-table-empty-state');
        const tableRowCountBadge = document.getElementById('cb-table-row-count-badge');
        const headerRecipientCount = document.getElementById('cb-header-recipient-count');
        const headerStepIndicator = document.getElementById('cb-header-step-indicator');

        // Step 2 elements
        const subjectInput = document.getElementById('send-emails-subject_template');
        const bodyInput = document.getElementById('send-emails-body_template');
        const subjectCounter = document.getElementById('cb-subject-counter');
        const bodyCounter = document.getElementById('cb-body-counter');
        const templateVarChips = document.getElementById('cb-template-var-chips');
        const attachmentsInput = document.getElementById('send-emails-attachments');
        const attachmentsChipsList = document.getElementById('cb-attachments-chips-list');
        const oneDocumentToggle = document.getElementById('send-emails-one_document_enabled');
        const oneDocumentFields = document.getElementById('send-emails-oneDocumentFields');
        const oneDocumentBaseInput = document.getElementById('send-emails-one_document_base_file');
        const oneDocumentBaseName = document.getElementById('send-emails-one_document_base_file_name');
        const sampleRowSelect = document.getElementById('cb-sample-row-select');
        const previewToVal = document.getElementById('cb-preview-to-val');
        const previewSubjectVal = document.getElementById('cb-preview-subject-val');
        const previewBodyVal = document.getElementById('cb-preview-body-val');

        // Step 3 elements
        const fullNameInput = document.getElementById('send-emails-full_name');
        const senderEmailInput = document.getElementById('send-emails-sender_email');
        const appPasswordInput = document.getElementById('send-emails-app_password');
        const pwToggleBtn = document.getElementById('cb-pw-toggle');
        const dayPresetSelect = document.getElementById('send-emails-day_preset');
        const limitInput = document.getElementById('send-emails-limit');
        const jitterMinInput = document.getElementById('send-emails-jitter_min_seconds');
        const jitterMaxInput = document.getElementById('send-emails-jitter_max_seconds');
        const batchSizeInput = document.getElementById('send-emails-batch_size');
        const batchPauseInput = document.getElementById('send-emails-batch_pause_minutes');

        // Step 4 elements
        const summarySender = document.getElementById('cb-summary-sender');
        const summaryRecipients = document.getElementById('cb-summary-recipients');
        const summaryAttachments = document.getElementById('cb-summary-attachments');
        const summaryDuration = document.getElementById('cb-summary-duration');
        const checkSender = document.getElementById('check-sender');
        const checkRecipients = document.getElementById('check-recipients');
        const checkSubject = document.getElementById('check-subject');
        const checkBody = document.getElementById('check-body');
        const testRecipientInput = document.getElementById('cb-test-recipient-input');
        const sendTestBtn = document.getElementById('cb-send-test-btn');
        const testBtnText = document.getElementById('cb-test-btn-text');
        const testBtnSpinner = document.getElementById('cb-test-btn-spinner');
        const testResultMsg = document.getElementById('cb-test-result-msg');
        const confirmCheckbox = document.getElementById('send-emails-confirm-checkbox');

        // Navigation & progress elements
        const wizardBackBtn = document.getElementById('cb-wizard-back-btn');
        const wizardNextBtn = document.getElementById('cb-wizard-next-btn');
        const autosaveIndicator = document.getElementById('cb-autosave-indicator');
        const sendProgressDock = document.getElementById('send-emails-sendProgressDock');
        const sendProgressText = document.getElementById('send-emails-sendProgressText');
        const sendProgressFill = document.getElementById('send-emails-sendProgressFill');
        const sendProgressStatusText = document.getElementById('send-emails-sendProgressStatusText');
        const errorDiv = document.getElementById('send-emails-error');
        const transferBox = document.getElementById('send-emails-transfer-box');
        const campaignBox = document.getElementById('send-emails-campaign-box');

        if (!form || !sendBtn) {
            return {
                show() {},
                hide() {},
            };
        }

        let currentStep = 1;
        let lastFocusedInput = subjectInput;
        let activeSendJobId = '';
        let sendJobPoll = null;
        let parsedDataRows = [];
        let detectedColumns = [];
        let totalFileRows = 0;
        let validEmailCount = 0;
        let duplicateCount = 0;

        const escapeHtml = window.SPAUtils?.escapeHtml || ((value) => String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;'));

        const SEND_FORM_STATE_KEY = 'aa_send_form_state_v2';
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

        // --- STEP WIZARD NAVIGATION ---
        function goToStep(step) {
            const targetStep = Math.max(1, Math.min(4, Number(step) || 1));
            currentStep = targetStep;

            // Update Stepper List
            for (let i = 1; i <= 4; i++) {
                const item = document.getElementById(`stepper-item-${i}`);
                const pane = document.getElementById(`wizard-pane-${i}`);
                if (!item || !pane) continue;

                if (i < currentStep) {
                    item.className = 'stepper-item completed';
                    pane.classList.remove('active');
                } else if (i === currentStep) {
                    item.className = 'stepper-item active';
                    pane.classList.add('active');
                } else {
                    item.className = 'stepper-item upcoming';
                    pane.classList.remove('active');
                }
            }

            // Update Header Indicator
            if (headerStepIndicator) {
                headerStepIndicator.textContent = `${currentStep} / 4`;
            }

            // Update Footer Buttons
            if (wizardBackBtn) {
                wizardBackBtn.hidden = (currentStep === 1);
            }

            if (wizardNextBtn) {
                if (currentStep < 4) {
                    wizardNextBtn.hidden = false;
                    wizardNextBtn.querySelector('span').textContent = `Next to Step ${currentStep + 1}`;
                } else {
                    wizardNextBtn.hidden = true;
                }
            }

            if (sendBtn) {
                sendBtn.hidden = (currentStep !== 4);
                if (currentStep === 4) {
                    validateStep4();
                }
            }

            // Specific step hooks
            if (currentStep === 2) {
                updateLivePreview();
                updateCharCounters();
            } else if (currentStep === 3) {
                highlightActivePresetCard();
            } else if (currentStep === 4) {
                updateSummaryDashboard();
                validateStep4();
                // Default test recipient to sender email if empty
                if (testRecipientInput && !testRecipientInput.value.trim() && senderEmailInput?.value) {
                    testRecipientInput.value = senderEmailInput.value.trim();
                }
            }

            // Scroll smoothly to top of wizard container
            const container = document.querySelector('.campaign-builder-wrapper');
            if (container) {
                container.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        }

        window.CampaignWizard = {
            goToStep: goToStep
        };

        if (wizardBackBtn) {
            wizardBackBtn.addEventListener('click', () => {
                if (currentStep > 1) {
                    goToStep(currentStep - 1);
                }
            });
        }

        if (wizardNextBtn) {
            wizardNextBtn.addEventListener('click', () => {
                if (currentStep < 4) {
                    goToStep(currentStep + 1);
                }
            });
        }

        // --- STEP 1: FILE UPLOAD & PREVIEW ---
        async function handleUploadedDataFile(file) {
            if (!file) return;

            if (dropzonePrompt) dropzonePrompt.hidden = true;
            if (fileLoadedState) fileLoadedState.hidden = false;
            if (dataFileName) dataFileName.textContent = file.name;
            if (fileMetaSummary) fileMetaSummary.textContent = `Analyzing file (${formatFileSize(file.size)})...`;

            const formData = new FormData();
            formData.append('data_file', file);

            try {
                const response = await fetch('/api/send-bulk/preview-file', {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();

                if (!response.ok || !data.success) {
                    throw new Error(data.message || 'File analysis failed');
                }

                totalFileRows = data.total_rows || 0;
                validEmailCount = data.valid_email_count || 0;
                duplicateCount = data.duplicate_count || 0;
                detectedColumns = data.columns || [];
                parsedDataRows = data.preview_rows || [];

                // Update loaded summary
                if (fileMetaSummary) {
                    fileMetaSummary.textContent = `${totalFileRows} rows detected • ${formatFileSize(file.size)}`;
                }

                // Show & update stats
                if (fileStatsGrid) fileStatsGrid.hidden = false;
                if (statTotalRows) statTotalRows.textContent = totalFileRows;
                if (statValidEmails) statValidEmails.textContent = validEmailCount;
                if (statDuplicateEmails) statDuplicateEmails.textContent = duplicateCount;
                if (statTotalColumns) statTotalColumns.textContent = detectedColumns.length;
                if (headerRecipientCount) headerRecipientCount.textContent = totalFileRows;

                // Auto-set recipient column
                if (data.detected_recipient_column && recipientColumnInput) {
                    recipientColumnInput.value = data.detected_recipient_column;
                }

                renderColumnChips(detectedColumns, data.detected_recipient_column);
                renderPreviewTable(detectedColumns, parsedDataRows);
                renderDynamicVariablePills(detectedColumns);
                populateSampleRowSelector(parsedDataRows);
                updateLivePreview();
                saveSendFormState();
            } catch (err) {
                if (fileMetaSummary) {
                    fileMetaSummary.textContent = `Error: ${err.message}`;
                }
                showErrorNotification(err.message || 'Error analyzing file.');
            }
        }

        function formatFileSize(bytes) {
            if (!bytes || bytes <= 0) return '0 B';
            const units = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(1024));
            return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
        }

        function renderColumnChips(columns, activeCol) {
            if (!columnChipsContainer) return;
            columnChipsContainer.innerHTML = '';

            columns.forEach(col => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = `cb-col-chip ${col.toLowerCase() === (activeCol || '').toLowerCase() ? 'active' : ''}`;
                btn.textContent = col;
                btn.title = `Select column '${col}' as recipient email`;
                btn.addEventListener('click', () => {
                    if (recipientColumnInput) {
                        recipientColumnInput.value = col;
                        saveSendFormState();
                    }
                    columnChipsContainer.querySelectorAll('.cb-col-chip').forEach(c => c.classList.remove('active'));
                    btn.classList.add('active');
                    updateLivePreview();
                });
                columnChipsContainer.appendChild(btn);
            });
        }

        function renderPreviewTable(columns, rows) {
            if (!previewTable || !previewTableHead || !previewTableBody) return;

            if (!rows || rows.length === 0) {
                if (tableEmptyState) tableEmptyState.hidden = false;
                previewTable.hidden = true;
                if (tableRowCountBadge) tableRowCountBadge.textContent = '0 rows loaded';
                return;
            }

            if (tableEmptyState) tableEmptyState.hidden = true;
            previewTable.hidden = false;
            if (tableRowCountBadge) tableRowCountBadge.textContent = `${totalFileRows} rows found (Showing first ${rows.length})`;

            // Render Header
            let headHtml = '<tr><th style="width: 45px;">#</th>';
            columns.forEach(col => {
                const isEmail = col.toLowerCase().includes('mail') || col.toLowerCase() === (recipientColumnInput?.value || '').toLowerCase();
                headHtml += `<th>${escapeHtml(col)} ${isEmail ? '<span class="cb-pill-sm">Email</span>' : ''}</th>`;
            });
            headHtml += '</tr>';
            previewTableHead.innerHTML = headHtml;

            // Render Body
            let bodyHtml = '';
            rows.forEach((row, idx) => {
                bodyHtml += `<tr><td class="text-muted">${idx + 1}</td>`;
                columns.forEach(col => {
                    const val = row[col] || '';
                    const isEmail = val.includes('@') && val.includes('.');
                    bodyHtml += `<td>${isEmail ? `<span class="cb-table-email">${escapeHtml(val)}</span>` : escapeHtml(val)}</td>`;
                });
                bodyHtml += '</tr>';
            });
            previewTableBody.innerHTML = bodyHtml;
        }

        function renderDynamicVariablePills(columns) {
            if (!templateVarChips) return;

            // Preserve standard default pills
            const defaultVars = ['company', 'person', 'email', 'city'];
            const allVars = new Set(defaultVars);
            columns.forEach(col => {
                const cleaned = col.trim();
                if (cleaned) allVars.add(cleaned);
            });

            templateVarChips.innerHTML = '';
            allVars.forEach(v => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'cb-var-pill';
                btn.setAttribute('data-var', `{{${v}}}`);
                btn.textContent = `+ {{${v}}}`;
                btn.addEventListener('click', () => insertVariableAtCursor(`{{${v}}}`));
                templateVarChips.appendChild(btn);
            });
        }

        function populateSampleRowSelector(rows) {
            if (!sampleRowSelect) return;
            sampleRowSelect.innerHTML = '';

            if (!rows || rows.length === 0) {
                sampleRowSelect.innerHTML = '<option value="0">Row 1 (Sample)</option>';
                return;
            }

            rows.forEach((row, idx) => {
                const opt = document.createElement('option');
                opt.value = String(idx);
                const recCol = recipientColumnInput?.value || 'email';
                const recipient = row[recCol] || row['email'] || row['recipient'] || `Recipient ${idx + 1}`;
                const company = row['company'] || row['Unternehmen'] || row['firma'] || '';
                opt.textContent = `Row ${idx + 1}: ${recipient}${company ? ` (${company})` : ''}`;
                sampleRowSelect.appendChild(opt);
            });
        }

        // Drag & Drop Listeners
        if (dropzone) {
            ['dragenter', 'dragover'].forEach(eventName => {
                dropzone.addEventListener(eventName, (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    dropzone.classList.add('drag-active');
                });
            });

            ['dragleave', 'drop'].forEach(eventName => {
                dropzone.addEventListener(eventName, (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    dropzone.classList.remove('drag-active');
                });
            });

            dropzone.addEventListener('drop', (e) => {
                const files = e.dataTransfer?.files;
                if (files && files.length > 0) {
                    if (dataFileInput) {
                        dataFileInput.files = files;
                    }
                    handleUploadedDataFile(files[0]);
                }
            });
        }

        if (dataFileInput) {
            dataFileInput.addEventListener('change', () => {
                if (dataFileInput.files && dataFileInput.files[0]) {
                    handleUploadedDataFile(dataFileInput.files[0]);
                }
            });
        }

        // --- STEP 2: COMPOSE & LIVE PREVIEW ---
        function insertVariableAtCursor(variableStr) {
            const target = lastFocusedInput || subjectInput || bodyInput;
            if (!target) return;

            const start = target.selectionStart || 0;
            const end = target.selectionEnd || 0;
            const text = target.value;
            target.value = text.substring(0, start) + variableStr + text.substring(end);
            target.focus();
            const newCursorPos = start + variableStr.length;
            target.setSelectionRange(newCursorPos, newCursorPos);

            updateCharCounters();
            updateLivePreview();
            saveSendFormState();
        }

        if (subjectInput) {
            subjectInput.addEventListener('focus', () => { lastFocusedInput = subjectInput; });
            subjectInput.addEventListener('input', () => {
                updateCharCounters();
                updateLivePreview();
                saveSendFormState();
            });
        }

        if (bodyInput) {
            bodyInput.addEventListener('focus', () => { lastFocusedInput = bodyInput; });
            bodyInput.addEventListener('input', () => {
                updateCharCounters();
                updateLivePreview();
                saveSendFormState();
            });
        }

        function updateCharCounters() {
            if (subjectCounter && subjectInput) {
                subjectCounter.textContent = `${subjectInput.value.length} characters`;
            }
            if (bodyCounter && bodyInput) {
                const text = bodyInput.value.trim();
                const words = text ? text.split(/\s+/).length : 0;
                bodyCounter.textContent = `${words} words | ${bodyInput.value.length} characters`;
            }
        }

        function updateLivePreview() {
            if (!previewSubjectVal || !previewBodyVal) return;

            const rowIndex = Number(sampleRowSelect?.value || 0);
            const sampleRow = (parsedDataRows && parsedDataRows[rowIndex]) ? parsedDataRows[rowIndex] : {
                company: 'JobScout Partner GmbH',
                Unternehmen: 'JobScout Partner GmbH',
                person: 'Frau Dr. Schmidt',
                name: 'Frau Dr. Schmidt',
                email: 'kontakt@jobscout-partner.de',
                city: 'München'
            };

            const recCol = recipientColumnInput?.value || 'email';
            const recipientEmail = sampleRow[recCol] || sampleRow['email'] || 'empfaenger@unternehmen.de';
            if (previewToVal) {
                previewToVal.textContent = recipientEmail;
            }

            const rawSubject = subjectInput?.value || '';
            const rawBody = bodyInput?.value || '';

            const renderTemplate = (tmpl, data) => {
                if (!tmpl) return '';
                return tmpl.replace(/\{\{\s*([a-zA-Z0-9_\u00C0-\u017F]+)\s*\}\}/g, (match, key) => {
                    // Try exact, lower, and fallback lookup
                    if (data[key] !== undefined) return data[key];
                    const lowerKey = key.toLowerCase();
                    const foundKey = Object.keys(data).find(k => k.toLowerCase() === lowerKey);
                    if (foundKey && data[foundKey] !== undefined) return data[foundKey];
                    return match;
                });
            };

            const renderedSubject = renderTemplate(rawSubject, sampleRow);
            const renderedBody = renderTemplate(rawBody, sampleRow);

            previewSubjectVal.textContent = renderedSubject || 'No subject entered yet';
            previewBodyVal.textContent = renderedBody || 'Rendered email body preview will appear here...';
        }

        if (sampleRowSelect) {
            sampleRowSelect.addEventListener('change', updateLivePreview);
        }

        // Attachments Management
        if (attachmentsInput) {
            attachmentsInput.addEventListener('change', () => {
                renderAttachmentsChips(Array.from(attachmentsInput.files || []));
            });
        }

        function renderAttachmentsChips(files) {
            if (!attachmentsChipsList) return;
            attachmentsChipsList.innerHTML = '';

            if (!files || files.length === 0) {
                attachmentsChipsList.innerHTML = '<span class="cb-attachments-empty">No attachments added yet.</span>';
                return;
            }

            files.forEach((file) => {
                const chip = document.createElement('div');
                chip.className = 'cb-attachment-chip';
                chip.innerHTML = `
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
                    <span class="cb-attachment-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>
                    <span class="cb-attachment-size">(${formatFileSize(file.size)})</span>
                `;
                attachmentsChipsList.appendChild(chip);
            });
        }

        // One Document Mode Toggle
        if (oneDocumentToggle && oneDocumentFields) {
            oneDocumentToggle.addEventListener('change', () => {
                oneDocumentFields.hidden = !oneDocumentToggle.checked;
                saveSendFormState();
            });
        }

        if (oneDocumentBaseInput && oneDocumentBaseName) {
            oneDocumentBaseInput.addEventListener('change', () => {
                const files = oneDocumentBaseInput.files || [];
                if (files.length > 0) {
                    oneDocumentBaseName.textContent = files[0].name;
                } else {
                    oneDocumentBaseName.textContent = 'No file selected';
                }
            });
        }

        // --- STEP 3: SETTINGS & PRESETS ---
        if (pwToggleBtn && appPasswordInput) {
            pwToggleBtn.addEventListener('click', () => {
                const isPassword = appPasswordInput.type === 'password';
                appPasswordInput.type = isPassword ? 'text' : 'password';
                const eyeOpen = pwToggleBtn.querySelector('.eye-open');
                const eyeClosed = pwToggleBtn.querySelector('.eye-closed');
                if (eyeOpen && eyeClosed) {
                    eyeOpen.hidden = isPassword;
                    eyeClosed.hidden = !isPassword;
                }
            });
        }

        function applyDayPreset(presetKey) {
            const preset = DAY_PRESETS[presetKey];
            if (!preset) return;

            if (limitInput) limitInput.value = preset.limit;
            if (jitterMinInput) jitterMinInput.value = preset.jitter_min_seconds;
            if (jitterMaxInput) jitterMaxInput.value = preset.jitter_max_seconds;
            if (batchSizeInput) batchSizeInput.value = preset.batch_size;
            if (batchPauseInput) batchPauseInput.value = preset.batch_pause_minutes;

            if (dayPresetSelect) dayPresetSelect.value = presetKey;
            highlightActivePresetCard(presetKey);
            saveSendFormState();
        }

        function highlightActivePresetCard(presetKey) {
            const key = presetKey || dayPresetSelect?.value || '';
            document.querySelectorAll('.cb-preset-card').forEach(card => {
                if (card.getAttribute('data-preset') === key) {
                    card.classList.add('active');
                } else {
                    card.classList.remove('active');
                }
            });
        }

        document.querySelectorAll('.cb-preset-card').forEach(card => {
            card.addEventListener('click', () => {
                const presetKey = card.getAttribute('data-preset');
                applyDayPreset(presetKey);
            });
        });

        // --- STEP 4: REVIEW & VALIDATION ---
        function updateSummaryDashboard() {
            if (summarySender) {
                summarySender.textContent = senderEmailInput?.value.trim() || 'Not specified';
            }
            if (summaryRecipients) {
                const count = totalFileRows || 0;
                summaryRecipients.textContent = `${count} Recipients`;
            }
            if (summaryAttachments) {
                const attCount = attachmentsInput?.files?.length || 0;
                const hasOneDoc = oneDocumentToggle?.checked;
                const parts = [];
                if (attCount > 0) parts.push(`${attCount} ${attCount === 1 ? 'Attachment' : 'Attachments'}`);
                if (hasOneDoc) parts.push('One Document PDF');
                summaryAttachments.textContent = parts.length > 0 ? parts.join(' + ') : 'No attachments';
            }
            if (summaryDuration) {
                const count = totalFileRows || 0;
                const jMin = Number(jitterMinInput?.value) || 80;
                const jMax = Number(jitterMaxInput?.value) || 120;
                const avgJitter = (jMin + jMax) / 2;
                const bSize = Number(batchSizeInput?.value) || 20;
                const bPause = (Number(batchPauseInput?.value) || 25) * 60;

                const batches = bSize > 0 ? Math.floor(count / bSize) : 0;
                const totalSeconds = (count * avgJitter) + (batches * bPause);

                if (totalSeconds < 60) {
                    summaryDuration.textContent = `~ ${Math.round(totalSeconds)} seconds`;
                } else if (totalSeconds < 3600) {
                    summaryDuration.textContent = `~ ${Math.round(totalSeconds / 60)} minutes`;
                } else {
                    const hours = Math.floor(totalSeconds / 3600);
                    const minutes = Math.round((totalSeconds % 3600) / 60);
                    summaryDuration.textContent = `~ ${hours}h ${minutes}m`;
                }
            }
        }

        function validateStep4() {
            let isValid = true;

            // 1. Sender credentials
            const hasSender = Boolean(senderEmailInput?.value.trim() && appPasswordInput?.value.trim());
            updateCheckItem(checkSender, hasSender);
            if (!hasSender) isValid = false;

            // 2. Recipients
            const hasRecipients = Boolean(totalFileRows > 0 || transferIdInput?.value || campaignIdInput?.value);
            updateCheckItem(checkRecipients, hasRecipients);
            if (!hasRecipients) isValid = false;

            // 3. Subject
            const hasSubject = Boolean(subjectInput?.value.trim());
            updateCheckItem(checkSubject, hasSubject);
            if (!hasSubject) isValid = false;

            // 4. Body
            const hasBody = Boolean(bodyInput?.value.trim());
            updateCheckItem(checkBody, hasBody);
            if (!hasBody) isValid = false;

            // Confirmation checkbox
            const isConfirmed = Boolean(confirmCheckbox?.checked);
            if (sendBtn) {
                sendBtn.disabled = !(isValid && isConfirmed);
            }

            return isValid;
        }

        function updateCheckItem(itemEl, isOk) {
            if (!itemEl) return;
            if (isOk) {
                itemEl.className = 'cb-check-item success';
            } else {
                itemEl.className = 'cb-check-item error';
            }
        }

        if (confirmCheckbox) {
            confirmCheckbox.addEventListener('change', validateStep4);
        }

        // Test Email Sender
        if (sendTestBtn) {
            sendTestBtn.addEventListener('click', async () => {
                const senderEmail = senderEmailInput?.value.trim();
                const appPassword = appPasswordInput?.value.trim();
                const testRecipient = testRecipientInput?.value.trim() || senderEmail;
                const subject = subjectInput?.value.trim();
                const body = bodyInput?.value.trim();

                if (!senderEmail || !appPassword) {
                    showTestResult('Please enter sender email and Gmail App Password in Step 3 first.', false);
                    return;
                }
                if (!testRecipient) {
                    showTestResult('Please provide a test recipient email address.', false);
                    return;
                }

                sendTestBtn.disabled = true;
                if (testBtnSpinner) testBtnSpinner.hidden = false;
                if (testBtnText) testBtnText.textContent = 'Sending test email...';

                try {
                    const testFormData = new FormData();
                    testFormData.append('sender_email', senderEmail);
                    testFormData.append('app_password', appPassword);
                    testFormData.append('test_recipient', testRecipient);
                    testFormData.append('subject_template', subject || 'JobScout Test Email');
                    testFormData.append('body_template', body || 'This is a test email.');
                    testFormData.append('full_name', fullNameInput?.value.trim() || '');

                    // Include attachments if present
                    if (attachmentsInput?.files) {
                        Array.from(attachmentsInput.files).forEach(f => {
                            testFormData.append('attachments', f);
                        });
                    }

                    const response = await fetch('/api/send-bulk/test-email', {
                        method: 'POST',
                        body: testFormData
                    });
                    const data = await response.json();

                    if (!response.ok || !data.success) {
                        throw new Error(data.message || 'Error sending test email');
                    }

                    showTestResult(data.message || 'Test email sent successfully!', true);
                } catch (testErr) {
                    showTestResult(testErr.message || 'Test email could not be sent.', false);
                } finally {
                    sendTestBtn.disabled = false;
                    if (testBtnSpinner) testBtnSpinner.hidden = true;
                    if (testBtnText) testBtnText.textContent = 'Send Test Email Now';
                }
            });
        }

        function showTestResult(msg, isSuccess) {
            if (!testResultMsg) return;
            testResultMsg.hidden = false;
            testResultMsg.className = `cb-test-status ${isSuccess ? 'success' : 'error'}`;
            testResultMsg.textContent = msg;
        }

        function showErrorNotification(msg) {
            if (!errorDiv) return;
            errorDiv.textContent = msg;
            errorDiv.hidden = false;
        }

        // --- DRAFT PERSISTENCE (SECURITY-SAFE) ---
        // Excludes app_password!
        function saveSendFormState() {
            const state = {
                full_name: fullNameInput?.value || '',
                sender_email: senderEmailInput?.value || '',
                recipient_column: recipientColumnInput?.value || '',
                limit: limitInput?.value || '',
                day_preset: dayPresetSelect?.value || '',
                jitter_min_seconds: jitterMinInput?.value || '',
                jitter_max_seconds: jitterMaxInput?.value || '',
                batch_size: batchSizeInput?.value || '',
                batch_pause_minutes: batchPauseInput?.value || '',
                one_document_enabled: oneDocumentToggle?.checked ? '1' : '',
                one_document_page: document.getElementById('send-emails-one_document_page')?.value || '',
                one_document_action: document.getElementById('send-emails-one_document_action')?.value || 'replace',
                subject_template: subjectInput?.value || '',
                body_template: bodyInput?.value || ''
            };
            try {
                localStorage.setItem(SEND_FORM_STATE_KEY, JSON.stringify(state));
                if (autosaveIndicator) {
                    autosaveIndicator.classList.add('saving');
                    setTimeout(() => autosaveIndicator.classList.remove('saving'), 800);
                }
            } catch (_e) {
                // Ignore localStorage errors
            }
        }

        function restoreSendFormState() {
            const raw = localStorage.getItem(SEND_FORM_STATE_KEY);
            if (!raw) return;

            try {
                const state = JSON.parse(raw);
                if (fullNameInput && !fullNameInput.value) fullNameInput.value = state.full_name || '';
                if (senderEmailInput && !senderEmailInput.value) senderEmailInput.value = state.sender_email || '';
                if (recipientColumnInput && !recipientColumnInput.value) recipientColumnInput.value = state.recipient_column || 'email';
                if (limitInput && !limitInput.value) limitInput.value = state.limit || '';
                if (dayPresetSelect && !dayPresetSelect.value) dayPresetSelect.value = state.day_preset || '';
                if (jitterMinInput && !jitterMinInput.value) jitterMinInput.value = state.jitter_min_seconds || '';
                if (jitterMaxInput && !jitterMaxInput.value) jitterMaxInput.value = state.jitter_max_seconds || '';
                if (batchSizeInput && !batchSizeInput.value) batchSizeInput.value = state.batch_size || '';
                if (batchPauseInput && !batchPauseInput.value) batchPauseInput.value = state.batch_pause_minutes || '';

                if (oneDocumentToggle) {
                    oneDocumentToggle.checked = Boolean(state.one_document_enabled);
                    if (oneDocumentFields) oneDocumentFields.hidden = !oneDocumentToggle.checked;
                }
                const pageInput = document.getElementById('send-emails-one_document_page');
                if (pageInput && !pageInput.value) pageInput.value = state.one_document_page || '1';
                const actionInput = document.getElementById('send-emails-one_document_action');
                if (actionInput && !actionInput.value) actionInput.value = state.one_document_action || 'replace';

                if (subjectInput && !subjectInput.value) subjectInput.value = state.subject_template || '';
                if (bodyInput && !bodyInput.value) bodyInput.value = state.body_template || '';

                highlightActivePresetCard(state.day_preset);
                updateCharCounters();
                updateLivePreview();
            } catch (_e) {
                // Ignore parse errors
            }
        }

        function bindAutoSaveEvents() {
            [fullNameInput, senderEmailInput, recipientColumnInput, limitInput, jitterMinInput, jitterMaxInput, batchSizeInput, batchPauseInput].forEach(el => {
                if (!el) return;
                el.addEventListener('input', saveSendFormState);
                el.addEventListener('change', saveSendFormState);
            });
        }

        // --- CAMPAIGN & TRANSFER URL LOADER ---
        async function loadCampaignOrTransferData() {
            const urlParams = new URLSearchParams(window.location.search);
            const transferId = (urlParams.get('transfer') || '').trim();
            const campaignId = (urlParams.get('campaign') || '').trim();

            if (!transferId && !campaignId) return;

            try {
                const query = transferId 
                    ? `?transfer=${encodeURIComponent(transferId)}`
                    : `?campaign=${encodeURIComponent(campaignId)}`;
                
                const response = await fetch(`/api/send-emails/campaigns${query}`);
                const data = await response.json();

                if (!response.ok || !data.success) {
                    if (data.transfer_error) showErrorNotification(data.transfer_error);
                    if (data.campaign_error) showErrorNotification(data.campaign_error);
                    return;
                }

                if (data.campaign_info) {
                    renderCampaignInfo(data.campaign_info, data.active_send_job);
                } else if (data.transfer_info) {
                    renderTransferInfo(data.transfer_info);
                }
            } catch (err) {
                showErrorNotification('Error loading campaign data: ' + err.message);
            }
        }

        function renderCampaignInfo(campaignInfo, activeSendJob) {
            if (campaignIdInput) campaignIdInput.value = campaignInfo.id || '';
            if (dataFileInput) dataFileInput.disabled = true;
            if (dataFileName) dataFileName.textContent = `${campaignInfo.total_rows} recipients loaded`;
            if (fileMetaSummary) fileMetaSummary.textContent = `Saved campaign: ${campaignInfo.name || campaignInfo.id}`;
            if (dropzonePrompt) dropzonePrompt.hidden = true;
            if (fileLoadedState) fileLoadedState.hidden = false;

            totalFileRows = campaignInfo.total_rows || 0;
            if (headerRecipientCount) headerRecipientCount.textContent = totalFileRows;

            const html = `
                <div class="campaign-box-head">
                    <div>
                        <strong>Saved template loaded:</strong> ${escapeHtml(campaignInfo.name)}<br>
                        Progress: ${campaignInfo.sent_rows}/${campaignInfo.total_rows} sent, ${campaignInfo.remaining_rows} remaining.
                        ${campaignInfo.one_document?.enabled ? `<br>One Document Mode: ${campaignInfo.one_document.action === 'add' ? 'Add' : 'Replace'} on page ${campaignInfo.one_document.page || 1}` : ''}
                    </div>
                </div>
            `;
            if (campaignBox) {
                campaignBox.innerHTML = html;
                campaignBox.hidden = false;
            }

            if (fullNameInput && campaignInfo.full_name) fullNameInput.value = campaignInfo.full_name;
            if (senderEmailInput && campaignInfo.sender_email) senderEmailInput.value = campaignInfo.sender_email;
            if (recipientColumnInput && campaignInfo.recipient_column) recipientColumnInput.value = campaignInfo.recipient_column;
            if (subjectInput && campaignInfo.subject_template) subjectInput.value = campaignInfo.subject_template;
            if (bodyInput && campaignInfo.body_template) bodyInput.value = campaignInfo.body_template;

            if (campaignInfo.preview && campaignInfo.preview.length > 0) {
                parsedDataRows = campaignInfo.preview.map(p => ({
                    recipient: p.recipient,
                    email: p.recipient,
                    company: p.company,
                    filename: p.filename
                }));
                populateSampleRowSelector(parsedDataRows);
                renderPreviewTable(['email', 'company', 'filename'], parsedDataRows);
            }

            updateCharCounters();
            updateLivePreview();
            saveSendFormState();

            if (activeSendJob && activeSendJob.job_id) {
                attachToSendJob(activeSendJob.job_id);
            }
        }

        function renderTransferInfo(transferInfo) {
            if (transferIdInput) transferIdInput.value = transferInfo.id || '';
            if (dataFileInput) dataFileInput.disabled = true;
            if (dataFileName) dataFileName.textContent = `${transferInfo.total_rows} recipients loaded from cover letters`;
            if (fileMetaSummary) fileMetaSummary.textContent = `${transferInfo.total_rows} recipients with personalized cover letter PDFs`;
            if (dropzonePrompt) dropzonePrompt.hidden = true;
            if (fileLoadedState) fileLoadedState.hidden = false;

            totalFileRows = transferInfo.total_rows || 0;
            if (headerRecipientCount) headerRecipientCount.textContent = totalFileRows;

            const html = `
                <div>
                    <strong>Cover letter transfer loaded:</strong> ${transferInfo.total_rows} recipients with attached PDF documents.
                </div>
            `;
            if (transferBox) {
                transferBox.innerHTML = html;
                transferBox.hidden = false;
            }

            if (fullNameInput && transferInfo.full_name) fullNameInput.value = transferInfo.full_name;
            if (senderEmailInput && transferInfo.sender_email) senderEmailInput.value = transferInfo.sender_email;
            if (subjectInput && transferInfo.email_subject_template) subjectInput.value = transferInfo.email_subject_template;
            if (bodyInput && transferInfo.email_body_template) bodyInput.value = transferInfo.email_body_template;

            if (transferInfo.preview && transferInfo.preview.length > 0) {
                parsedDataRows = transferInfo.preview.map(p => ({
                    recipient: p.recipient,
                    email: p.recipient,
                    company: p.company || 'N/A',
                    filename: p.filename
                }));
                populateSampleRowSelector(parsedDataRows);
                renderPreviewTable(['email', 'company', 'filename'], parsedDataRows);
            }

            updateCharCounters();
            updateLivePreview();
            saveSendFormState();
        }

        // --- SUBMISSION & SEND PROGRESS ---
        function setSendingUiActive() {
            if (sendBtn) {
                sendBtn.disabled = true;
                sendBtn.textContent = 'Sending in progress...';
            }
            if (saveTemplateBtn) saveTemplateBtn.disabled = true;
            if (stopSendBtn) {
                stopSendBtn.style.display = 'inline-flex';
                stopSendBtn.disabled = false;
                stopSendBtn.textContent = 'Save and stop';
            }
            if (sendProgressDock) sendProgressDock.classList.add('visible');
            if (sendProgressStatusText) sendProgressStatusText.textContent = 'Sending active';
        }

        function resetSendingUi() {
            if (sendBtn) {
                sendBtn.disabled = false;
                sendBtn.textContent = 'Launch Bulk Send Now';
            }
            if (saveTemplateBtn) saveTemplateBtn.disabled = false;
            if (stopSendBtn) {
                stopSendBtn.style.display = 'none';
                stopSendBtn.disabled = false;
            }
            if (sendProgressStatusText) sendProgressStatusText.textContent = 'Completed';
        }

        async function saveTemplateToDashboard() {
            if (!saveTemplateBtn) return;
            if (resultDiv) resultDiv.style.display = 'none';
            saveTemplateBtn.disabled = true;
            const prevLabel = saveTemplateBtn.innerHTML;
            saveTemplateBtn.innerHTML = '<span>Saving template...</span>';

            try {
                const formData = new FormData(form);
                const response = await fetch('/api/campaign/save', {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                if (!response.ok || !data.success) {
                    throw new Error(data.message || 'Template could not be saved');
                }

                if (data.campaign_id && campaignIdInput) {
                    campaignIdInput.value = data.campaign_id;
                    const currentUrl = new URL(window.location.href);
                    currentUrl.searchParams.set('campaign', data.campaign_id);
                    currentUrl.searchParams.delete('transfer');
                    window.history.replaceState({}, '', currentUrl.toString());
                }

                saveSendFormState();
                if (resultDiv) {
                    resultDiv.className = 'cb-alert result success';
                    resultDiv.textContent = data.message || 'Template saved to dashboard successfully.';
                    resultDiv.style.display = 'block';
                }
            } catch (err) {
                if (resultDiv) {
                    resultDiv.className = 'cb-alert result error';
                    resultDiv.textContent = err.message || 'Template could not be saved.';
                    resultDiv.style.display = 'block';
                }
            } finally {
                saveTemplateBtn.disabled = false;
                saveTemplateBtn.innerHTML = prevLabel;
            }
        }

        function attachToSendJob(jobId) {
            activeSendJobId = String(jobId || '').trim();
            if (!activeSendJobId) return;

            setSendingUiActive();
            if (sendJobPoll) clearInterval(sendJobPoll);

            sendJobPoll = setInterval(async () => {
                try {
                    await pollSendJobStatus();
                } catch (err) {
                    if (sendJobPoll) {
                        clearInterval(sendJobPoll);
                        sendJobPoll = null;
                    }
                    resetSendingUi();
                    if (resultDiv) {
                        resultDiv.className = 'cb-alert result error';
                        resultDiv.textContent = err.message || 'Could not update send progress.';
                        resultDiv.style.display = 'block';
                    }
                }
            }, 1500);
        }

        async function pollSendJobStatus() {
            if (!activeSendJobId) return;

            const response = await fetch(`/api/send-bulk/status/${activeSendJobId}`);
            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.message || 'Could not load send status');
            }

            const job = data.job || {};
            updateSendProgress(job);

            if (job.campaign_id && campaignIdInput) {
                campaignIdInput.value = job.campaign_id;
            }

            if (job.status === 'completed' || job.status === 'failed') {
                if (sendJobPoll) {
                    clearInterval(sendJobPoll);
                    sendJobPoll = null;
                }
                activeSendJobId = '';
                resetSendingUi();
                if (resultDiv) {
                    resultDiv.className = `cb-alert result ${job.success ? 'success' : 'error'}`;
                    resultDiv.textContent = job.message || 'Campaign finished.';
                    resultDiv.style.display = 'block';
                }
            }
        }

        function updateSendProgress(job) {
            const total = Number(job.total || 0);
            const processed = Number(job.processed || 0);
            const sentSuccess = Number(job.sent_success || 0);
            const percent = Math.max(0, Math.min(100, Number(job.percent || 0)));
            const stageMessage = (job.message || '').trim();
            const remainingSeconds = Number(job.estimated_remaining_seconds);

            function formatEta(seconds) {
                if (!Number.isFinite(seconds) || seconds < 0) return '';
                if (seconds < 60) return `${Math.round(seconds)}s`;
                const hours = Math.floor(seconds / 3600);
                const minutes = Math.floor((seconds % 3600) / 60);
                const secs = Math.round(seconds % 60);
                if (hours > 0) return `${hours}h ${minutes}m`;
                if (minutes > 0) return `${minutes}m ${secs}s`;
                return `${secs}s`;
            }

            if (sendProgressDock) sendProgressDock.classList.add('visible');
            if (sendProgressFill) sendProgressFill.style.width = `${percent}%`;

            const etaText = total > processed && Number.isFinite(remainingSeconds)
                ? ` | ETA ${formatEta(remainingSeconds)}`
                : '';
            const base = `Sent ${sentSuccess}/${total} | Processed ${processed}/${total} | ${percent.toFixed(1)}%${etaText}`;
            if (sendProgressText) {
                sendProgressText.textContent = stageMessage ? `${base} | ${stageMessage}` : base;
            }
        }

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!validateStep4()) {
                showErrorNotification('Please review all required fields in the previous steps.');
                return;
            }

            setSendingUiActive();
            if (resultDiv) resultDiv.style.display = 'none';
            if (sendProgressText) sendProgressText.textContent = 'Starting campaign job...';
            if (sendProgressFill) sendProgressFill.style.width = '0%';

            try {
                const formData = new FormData(form);
                const response = await fetch('/api/send-bulk/start', {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();

                if (!response.ok || !data.success || !data.job_id) {
                    throw new Error(data.message || 'Could not start campaign job');
                }

                attachToSendJob(data.job_id);
                saveSendFormState();
                await pollSendJobStatus();
            } catch (err) {
                if (resultDiv) {
                    resultDiv.className = 'cb-alert result error';
                    resultDiv.textContent = err.message || 'Network error. Please try again.';
                    resultDiv.style.display = 'block';
                }
                resetSendingUi();
            }
        });

        if (stopSendBtn) {
            stopSendBtn.addEventListener('click', async () => {
                if (!activeSendJobId) return;
                stopSendBtn.disabled = true;
                stopSendBtn.textContent = 'Stopping...';

                try {
                    const response = await fetch(`/api/send-bulk/stop/${activeSendJobId}`, {
                        method: 'POST'
                    });
                    const data = await response.json();
                    if (!response.ok || !data.success) {
                        throw new Error(data.message || 'Could not request stop');
                    }
                } catch (stopErr) {
                    stopSendBtn.disabled = false;
                    stopSendBtn.textContent = 'Save and stop';
                    if (resultDiv) {
                        resultDiv.className = 'cb-alert result error';
                        resultDiv.textContent = stopErr.message || 'Could not request stop.';
                        resultDiv.style.display = 'block';
                    }
                }
            });
        }

        if (saveTemplateBtn) {
            saveTemplateBtn.addEventListener('click', () => {
                saveTemplateToDashboard().catch(() => {});
            });
        }

        function consumeTransientResult() {
            const raw = sessionStorage.getItem(SEND_RESULT_FLASH_KEY);
            if (!raw) return;
            sessionStorage.removeItem(SEND_RESULT_FLASH_KEY);

            try {
                const payload = JSON.parse(raw);
                if (!payload || !payload.message || !resultDiv) return;
                resultDiv.className = `cb-alert result ${payload.level === 'error' ? 'error' : 'success'}`;
                resultDiv.textContent = payload.message;
                resultDiv.style.display = 'block';
            } catch (_e) {
                // Ignore transient flash parse errors
            }
        }

        return {
            show() {
                consumeTransientResult();
                restoreSendFormState();
                bindAutoSaveEvents();
                goToStep(1);
                loadCampaignOrTransferData().catch(() => {});
            },
            hide() {
                if (sendJobPoll) {
                    clearInterval(sendJobPoll);
                    sendJobPoll = null;
                }
            }
        };
    };

    window.SPASections = sections;
})();

/**
 * JobScout WhatsApp AI Customer Support Center SPA Section Controller
 * Provides real-time support inbox, atomic takeover/resume controls,
 * AI configuration, live SSE streaming, and knowledge base management.
 */
(function () {
    const sections = window.SPASections || {};

    sections.createWhatsAppSection = function createWhatsAppSection() {
        const root = document.getElementById("whatsapp-section");
        if (!root) {
            return { show() {}, hide() {} };
        }

        // State
        let activeTab = "inbox";
        let conversations = [];
        let activeConvId = null;
        let activeConv = null;
        let sseSource = null;
        let candidateCache = [];
        let isEmergencyPaused = false;

        // Navigation Tabs
        const tabButtons = Array.from(root.querySelectorAll(".wa-tab-btn"));
        const tabViews = {
            inbox: document.getElementById("wa-view-inbox"),
            overview: document.getElementById("wa-view-overview"),
            config: document.getElementById("wa-view-config"),
            kb: document.getElementById("wa-view-kb"),
            setup: document.getElementById("wa-view-setup"),
        };

        // Header controls
        const sseIndicator = document.getElementById("wa-sse-indicator");
        const sseText = document.getElementById("wa-sse-text");
        const btnEmergencyPauseHeader = document.getElementById("wa-btn-emergency-pause-header");
        const tabUnreadCounter = document.getElementById("wa-tab-unread-counter");

        // Inbox DOM elements
        const convListEl = document.getElementById("wa-conversations-list");
        const searchInput = document.getElementById("wa-search-conversations");
        const filterChips = Array.from(root.querySelectorAll(".wa-filter-chip"));
        const convTotalCountEl = document.getElementById("wa-conv-total-count");
        const btnRefreshConvs = document.getElementById("wa-btn-refresh-convs");

        // Chat DOM elements
        const chatPlaceholder = document.getElementById("wa-chat-placeholder");
        const chatActiveView = document.getElementById("wa-chat-active-view");
        const headerAvatar = document.getElementById("wa-header-avatar");
        const headerName = document.getElementById("wa-header-name");
        const headerPhone = document.getElementById("wa-header-phone");
        const headerModeBadge = document.getElementById("wa-header-mode-badge");
        const headerAssigned = document.getElementById("wa-header-assigned");
        const headerWindow = document.getElementById("wa-header-window");
        const headerVersion = document.getElementById("wa-header-version");

        const btnTakeover = document.getElementById("wa-btn-takeover");
        const btnResumeAi = document.getElementById("wa-btn-resume-ai");
        const btnEscalate = document.getElementById("wa-btn-escalate");
        const btnCloseChat = document.getElementById("wa-btn-close-chat");

        const chatTimeline = document.getElementById("wa-chat-timeline");
        const draftBox = document.getElementById("wa-draft-box");
        const draftText = document.getElementById("wa-draft-text");
        const btnUseDraft = document.getElementById("wa-btn-use-draft");
        const btnDismissDraft = document.getElementById("wa-btn-dismiss-draft");
        const btnGenerateDraft = document.getElementById("wa-btn-generate-draft");

        const composerForm = document.getElementById("wa-composer-form");
        const composerInput = document.getElementById("wa-composer-input");
        const composerModeHint = document.getElementById("wa-composer-mode-hint");

        // Dossier DOM elements
        const dossierDetails = document.getElementById("wa-dossier-details");
        const dossierEmptyState = document.getElementById("wa-dossier-empty-state");
        const dossierVerifyBadge = document.getElementById("wa-dossier-verify-badge");
        const clientLinkSelect = document.getElementById("wa-client-link-select");
        const btnLinkClient = document.getElementById("wa-btn-link-client");
        const dossierName = document.getElementById("wa-dossier-name");
        const dossierClientId = document.getElementById("wa-dossier-client-id");
        const dossierEmail = document.getElementById("wa-dossier-email");
        const dossierPayment = document.getElementById("wa-dossier-payment");
        const dossierProfession = document.getElementById("wa-dossier-profession");
        const dossierDatasetBadge = document.getElementById("wa-dossier-dataset-badge");
        const dossierDatasetDetail = document.getElementById("wa-dossier-dataset-detail");
        const dossierAppsSent = document.getElementById("wa-dossier-apps-sent");
        const dossierAppsReplied = document.getElementById("wa-dossier-apps-replied");
        const dossierAppsInterviews = document.getElementById("wa-dossier-apps-interviews");
        const dossierAppStatus = document.getElementById("wa-dossier-app-status");
        const dossierDocsList = document.getElementById("wa-dossier-docs-list");
        const dossierSummary = document.getElementById("wa-dossier-summary");
        const dossierEscalationWrap = document.getElementById("wa-dossier-escalation-reason-wrap");
        const dossierEscalationReason = document.getElementById("wa-dossier-escalation-reason");

        // Metrics DOM
        const metricAiActive = document.getElementById("wa-metric-ai-active");
        const metricHumanActive = document.getElementById("wa-metric-human-active");
        const metricEscalations = document.getElementById("wa-metric-escalations");
        const metricMessagesToday = document.getElementById("wa-metric-messages-today");
        const metricFailedMessages = document.getElementById("wa-metric-failed-messages");
        const metricAiCost = document.getElementById("wa-metric-ai-cost");
        const metricTokens = document.getElementById("wa-metric-tokens");
        const metricLatency = document.getElementById("wa-metric-latency");
        const metricTakeoverRate = document.getElementById("wa-metric-takeover-rate");
        const auditTableBody = document.getElementById("wa-audit-table-body");
        const btnRefreshAudit = document.getElementById("wa-btn-refresh-audit");

        // Config DOM
        const configAiEnabled = document.getElementById("wa-config-ai-enabled-toggle");
        const configProvider = document.getElementById("wa-config-provider");
        const configModel = document.getElementById("wa-config-model");
        const configFallbackEnabled = document.getElementById("wa-config-fallback-enabled");
        const configBrandVoice = document.getElementById("wa-config-brand-voice");
        const configSystemPrompt = document.getElementById("wa-config-system-prompt");
        const configMaxTokens = document.getElementById("wa-config-max-tokens");
        const btnSaveConfig = document.getElementById("wa-btn-save-config");
        const configSaveStatus = document.getElementById("wa-config-save-status");
        const toolCheckboxes = Array.from(root.querySelectorAll(".wa-tool-checkbox"));

        // Knowledge Base DOM
        const kbSearch = document.getElementById("wa-kb-search");
        const kbCatFilter = document.getElementById("wa-kb-category-filter");
        const kbTableBody = document.getElementById("wa-kb-table-body");
        const btnAddKb = document.getElementById("wa-btn-add-kb");
        const kbModal = document.getElementById("wa-kb-modal");
        const kbModalTitle = document.getElementById("wa-kb-modal-title");
        const kbForm = document.getElementById("wa-kb-form");
        const kbFormId = document.getElementById("wa-kb-form-id");
        const kbFormCategory = document.getElementById("wa-kb-form-category");
        const kbFormTitle = document.getElementById("wa-kb-form-title");
        const kbFormContent = document.getElementById("wa-kb-form-content");
        const kbFormKeywords = document.getElementById("wa-kb-form-keywords");
        const btnCloseKbModal = document.getElementById("wa-btn-close-kb-modal");
        const btnCancelKb = document.getElementById("wa-btn-cancel-kb");

        // Setup & Simulator DOM
        const btnCopyWebhook = document.getElementById("wa-btn-copy-webhook");
        const setupWebhookUrl = document.getElementById("wa-setup-webhook-url");
        const setupVerifyToken = document.getElementById("wa-setup-verify-token");
        const setupPhoneId = document.getElementById("wa-setup-phone-id");
        const setupToken = document.getElementById("wa-setup-token");
        const btnSaveCredentials = document.getElementById("wa-btn-save-credentials");
        const simFrom = document.getElementById("wa-sim-from");
        const simName = document.getElementById("wa-sim-name");
        const simBody = document.getElementById("wa-sim-body");
        const btnSimulateMsg = document.getElementById("wa-btn-simulate-msg");
        const btnSimQuickHuman = document.getElementById("wa-btn-sim-quick-human");
        const simResult = document.getElementById("wa-sim-result");

        let activeFilter = "all";

        // Tab Switching
        function switchTab(targetTab) {
            activeTab = targetTab;
            tabButtons.forEach(btn => {
                const isTarget = btn.getAttribute("data-wa-tab") === targetTab;
                btn.classList.toggle("active", isTarget);
            });
            Object.keys(tabViews).forEach(tab => {
                if (tabViews[tab]) {
                    tabViews[tab].classList.toggle("active", tab === targetTab);
                }
            });

            if (targetTab === "overview") {
                loadMetrics();
                loadAuditLogs();
            } else if (targetTab === "config") {
                loadSettings();
            } else if (targetTab === "kb") {
                loadKnowledgeBase();
            } else if (targetTab === "setup") {
                updateWebhookUrl();
            }
        }

        tabButtons.forEach(btn => {
            btn.addEventListener("click", () => {
                const tab = btn.getAttribute("data-wa-tab");
                if (tab) switchTab(tab);
            });
        });

        function updateWebhookUrl() {
            if (setupWebhookUrl) {
                const host = window.location.origin;
                setupWebhookUrl.value = `${host}/api/whatsapp/webhook`;
            }
        }

        // SSE Real-Time Stream
        function initSSE() {
            if (sseSource) {
                sseSource.close();
            }
            try {
                sseSource = new EventSource("/api/whatsapp/stream");
                sseSource.onopen = () => {
                    if (sseIndicator) sseIndicator.classList.add("connected");
                    if (sseText) sseText.textContent = "Real-time SSE: Connected";
                };
                sseSource.onerror = () => {
                    if (sseIndicator) sseIndicator.classList.remove("connected");
                    if (sseText) sseText.textContent = "Real-time SSE: Disconnected";
                };

                sseSource.addEventListener("new_message", (evt) => {
                    try {
                        const data = JSON.parse(evt.data);
                        handleRealtimeNewMessage(data);
                    } catch (e) {
                        console.error("SSE parse error", e);
                    }
                });

                sseSource.addEventListener("status_update", (evt) => {
                    try {
                        const data = JSON.parse(evt.data);
                        handleRealtimeStatusUpdate(data);
                    } catch (e) {
                        console.error("SSE status parse error", e);
                    }
                });

                sseSource.addEventListener("mode_change", (evt) => {
                    try {
                        const data = JSON.parse(evt.data);
                        handleRealtimeModeChange(data);
                    } catch (e) {
                        console.error("SSE mode change error", e);
                    }
                });

                sseSource.addEventListener("takeover", (evt) => {
                    try {
                        const data = JSON.parse(evt.data);
                        handleRealtimeTakeover(data);
                    } catch (e) {
                        console.error("SSE takeover error", e);
                    }
                });

                sseSource.addEventListener("escalation", (evt) => {
                    try {
                        const data = JSON.parse(evt.data);
                        handleRealtimeEscalation(data);
                    } catch (e) {
                        console.error("SSE escalation error", e);
                    }
                });
            } catch (err) {
                console.error("Could not initialize WhatsApp SSE", err);
            }
        }

        function handleRealtimeNewMessage(data) {
            // If active conversation matches, append message
            if (activeConvId && (activeConvId === data.conversation_id || (activeConv && activeConv.wa_id === data.wa_id))) {
                appendChatMessage(data);
                scrollChatToBottom();
            }
            // Update list preview
            loadConversations(false);
        }

        function handleRealtimeStatusUpdate(data) {
            if (activeConvId === data.conversation_id && data.message_id) {
                const tickEl = root.querySelector(`[data-msg-id="${data.message_id}"] .wa-msg-status`);
                if (tickEl) {
                    tickEl.innerHTML = renderDeliveryIcon(data.status);
                }
            }
        }

        function handleRealtimeModeChange(data) {
            if (activeConvId === data.conversation_id) {
                if (activeConv) {
                    activeConv.mode = data.mode;
                    activeConv.version = data.version;
                }
                updateChatHeaderUI();
            }
            loadConversations(false);
        }

        function handleRealtimeTakeover(data) {
            if (activeConvId === data.conversation_id) {
                if (activeConv) {
                    activeConv.mode = "HUMAN_ACTIVE";
                    activeConv.version = data.version;
                    activeConv.assigned_agent = data.agent || "Administrator";
                }
                updateChatHeaderUI();
            }
            loadConversations(false);
        }

        function handleRealtimeEscalation(data) {
            if (activeConvId === data.conversation_id) {
                if (activeConv) {
                    activeConv.mode = "ESCALATED";
                    activeConv.escalation_reason = data.reason || "Human assistance requested";
                }
                updateChatHeaderUI();
            }
            loadConversations(false);
        }

        // Conversations List
        async function loadConversations(shouldSelectFirst = false) {
            try {
                const res = await fetch("/api/whatsapp/conversations");
                const json = await res.json();
                if (json.success && Array.isArray(json.data)) {
                    conversations = json.data;
                    renderConversationsList();
                    updateUnreadCounter();

                    if (shouldSelectFirst && conversations.length > 0 && !activeConvId) {
                        selectConversation(conversations[0].id);
                    }
                }
            } catch (err) {
                console.error("Failed to load WhatsApp conversations", err);
            }
        }

        function updateUnreadCounter() {
            let totalUnread = 0;
            conversations.forEach(c => {
                totalUnread += (c.unread_count || 0);
            });
            if (tabUnreadCounter) {
                if (totalUnread > 0) {
                    tabUnreadCounter.textContent = totalUnread;
                    tabUnreadCounter.style.display = "inline-flex";
                } else {
                    tabUnreadCounter.style.display = "none";
                }
            }
        }

        function renderConversationsList() {
            if (!convListEl) return;
            const query = (searchInput ? searchInput.value : "").trim().toLowerCase();

            const filtered = conversations.filter(c => {
                if (activeFilter !== "all" && c.mode !== activeFilter) {
                    return false;
                }
                if (query) {
                    const name = (c.display_name || "").toLowerCase();
                    const waId = (c.wa_id || "").toLowerCase();
                    const clientId = (c.client_id || "").toLowerCase();
                    const snippet = (c.last_message_snippet || "").toLowerCase();
                    return name.includes(query) || waId.includes(query) || clientId.includes(query) || snippet.includes(query);
                }
                return true;
            });

            if (convTotalCountEl) {
                convTotalCountEl.textContent = `${filtered.length} of ${conversations.length} conversations`;
            }

            if (filtered.length === 0) {
                convListEl.innerHTML = `<div class="wa-empty-state">No conversations found.</div>`;
                return;
            }

            convListEl.innerHTML = filtered.map(c => {
                const isSelected = c.id === activeConvId;
                const initial = (c.display_name || c.wa_id || "?").charAt(0).toUpperCase();
                const modeClass = getModeBadgeClass(c.mode);
                const modeLabel = getModeLabel(c.mode);
                const timeStr = formatRelativeTime(c.last_activity_at);
                const unreadBadge = c.unread_count > 0 ? `<span class="wa-conv-unread">${c.unread_count}</span>` : "";

                return `
                    <div class="wa-conv-item ${isSelected ? "active" : ""}" data-id="${c.id}">
                        <div class="wa-conv-avatar">${escapeHtml(initial)}</div>
                        <div class="wa-conv-body">
                            <div class="wa-conv-top">
                                <span class="wa-conv-name">${escapeHtml(c.display_name || c.wa_id)}</span>
                                <span class="wa-conv-time">${escapeHtml(timeStr)}</span>
                            </div>
                            <div class="wa-conv-preview">${escapeHtml(c.last_message_snippet || "No messages")}</div>
                            <div class="wa-conv-meta">
                                <span class="wa-mode-tag ${modeClass}">${modeLabel}</span>
                                ${c.client_id ? `<span class="wa-client-pill font-mono">ID: ${escapeHtml(c.client_id.slice(0, 8))}</span>` : ""}
                                ${unreadBadge}
                            </div>
                        </div>
                    </div>
                `;
            }).join("");

            // Attach click handlers
            convListEl.querySelectorAll(".wa-conv-item").forEach(item => {
                item.addEventListener("click", () => {
                    const id = item.getAttribute("data-id");
                    if (id) selectConversation(id);
                });
            });
        }

        async function selectConversation(convId) {
            activeConvId = convId;
            activeConv = conversations.find(c => c.id === convId);

            renderConversationsList();

            if (chatPlaceholder) chatPlaceholder.style.display = "none";
            if (chatActiveView) chatActiveView.style.display = "flex";

            updateChatHeaderUI();
            if (draftBox) draftBox.style.display = "none";

            // Mark read & fetch messages
            await fetch(`/api/whatsapp/conversations/${convId}/read`, { method: "POST" });
            if (activeConv) activeConv.unread_count = 0;
            updateUnreadCounter();

            await loadChatMessages(convId);
            await loadClientDossier(activeConv ? activeConv.client_id : null, activeConv ? activeConv.wa_id : null);
        }

        function updateChatHeaderUI() {
            if (!activeConv) return;
            if (headerName) headerName.textContent = activeConv.display_name || activeConv.wa_id;
            if (headerPhone) headerPhone.textContent = activeConv.wa_id;
            if (headerAvatar) headerAvatar.textContent = (activeConv.display_name || activeConv.wa_id || "?").charAt(0).toUpperCase();

            if (headerModeBadge) {
                headerModeBadge.className = `wa-mode-badge ${getModeBadgeClass(activeConv.mode)}`;
                headerModeBadge.textContent = getModeLabel(activeConv.mode);
            }

            if (headerAssigned) {
                headerAssigned.textContent = `Agent: ${activeConv.assigned_agent || "Unassigned"}`;
            }

            if (headerVersion) {
                headerVersion.textContent = `v${activeConv.version || 1}`;
            }

            // Mode button availability
            if (btnTakeover) {
                btnTakeover.style.display = activeConv.mode === "HUMAN_ACTIVE" ? "none" : "inline-flex";
            }
            if (btnResumeAi) {
                btnResumeAi.style.display = activeConv.mode === "AI_ACTIVE" ? "none" : "inline-flex";
            }
            if (composerModeHint) {
                composerModeHint.textContent = activeConv.mode === "AI_ACTIVE"
                    ? "🤖 AI is currently replying automatically. Sending a message takes over manually."
                    : "👤 Human mode active. No automated AI responses.";
            }
        }

        async function loadChatMessages(convId) {
            if (!chatTimeline) return;
            chatTimeline.innerHTML = `<div class="wa-loading-chat">Loading chat history...</div>`;

            try {
                const res = await fetch(`/api/whatsapp/conversations/${convId}/messages`);
                const json = await res.json();
                if (json.success && Array.isArray(json.data)) {
                    renderChatMessages(json.data);
                    scrollChatToBottom();
                } else {
                    chatTimeline.innerHTML = `<div class="wa-empty-chat">No messages yet.</div>`;
                }
            } catch (err) {
                console.error("Failed to load chat messages", err);
                chatTimeline.innerHTML = `<div class="wa-empty-chat">Failed to load chat.</div>`;
            }
        }

        function renderChatMessages(messages) {
            if (!chatTimeline) return;
            if (messages.length === 0) {
                chatTimeline.innerHTML = `<div class="wa-empty-chat">No messages yet.</div>`;
                return;
            }

            chatTimeline.innerHTML = messages.map(msg => renderMessageHTML(msg)).join("");
        }

        function renderMessageHTML(msg) {
            const isOutbound = msg.direction === "outbound";
            const senderType = msg.sender_type || (isOutbound ? "ai" : "client");
            const bubbleClass = isOutbound ? "wa-msg-outbound" : "wa-msg-inbound";
            const senderTag = getSenderTag(senderType);
            const timeStr = formatTime(msg.created_at);
            const statusIcon = isOutbound ? renderDeliveryIcon(msg.delivery_status) : "";

            let metaInfo = "";
            if (msg.ai_metadata) {
                try {
                    const parsed = typeof msg.ai_metadata === "string" ? JSON.parse(msg.ai_metadata) : msg.ai_metadata;
                    if (parsed.model) {
                        metaInfo = `<span class="wa-msg-model font-mono">${escapeHtml(parsed.model)}</span>`;
                    }
                } catch (e) {}
            }

            return `
                <div class="wa-msg-wrap ${bubbleClass}" data-msg-id="${msg.id}">
                    <div class="wa-msg-bubble">
                        <div class="wa-msg-top">
                            ${senderTag}
                            ${metaInfo}
                        </div>
                        <div class="wa-msg-content">${formatMessageText(msg.content)}</div>
                        <div class="wa-msg-footer">
                            <span class="wa-msg-time">${timeStr}</span>
                            ${statusIcon}
                        </div>
                    </div>
                </div>
            `;
        }

        function appendChatMessage(msg) {
            if (!chatTimeline) return;
            const emptyEl = chatTimeline.querySelector(".wa-empty-chat");
            if (emptyEl) emptyEl.remove();

            const div = document.createElement("div");
            div.innerHTML = renderMessageHTML(msg);
            chatTimeline.appendChild(div.firstElementChild);
        }

        function scrollChatToBottom() {
            if (chatTimeline) {
                chatTimeline.scrollTop = chatTimeline.scrollHeight;
            }
        }

        // Actions: Take Over, Resume AI, Escalate, Close
        btnTakeover.addEventListener("click", async () => {
            if (!activeConvId) return;
            try {
                btnTakeover.disabled = true;
                const res = await fetch(`/api/whatsapp/conversations/${activeConvId}/takeover`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ agent_name: "Administrator" })
                });
                const json = await res.json();
                if (json.success) {
                    if (activeConv) {
                        activeConv.mode = "HUMAN_ACTIVE";
                        activeConv.version = json.version;
                        activeConv.assigned_agent = "Administrator";
                    }
                    updateChatHeaderUI();
                    loadConversations(false);
                    showToast("Successfully taken over. Autonomous AI replies are stopped for this chat.");
                } else {
                    alert(`Takeover failed: ${json.error || "Unknown error"}`);
                }
            } catch (err) {
                console.error(err);
                alert("Failed to take over.");
            } finally {
                btnTakeover.disabled = false;
            }
        });

        btnResumeAi.addEventListener("click", async () => {
            if (!activeConvId) return;
            try {
                btnResumeAi.disabled = true;
                const res = await fetch(`/api/whatsapp/conversations/${activeConvId}/resume-ai`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" }
                });
                const json = await res.json();
                if (json.success) {
                    if (activeConv) {
                        activeConv.mode = "AI_ACTIVE";
                        activeConv.version = json.version;
                    }
                    updateChatHeaderUI();
                    loadConversations(false);
                    showToast("AI resumed successfully. Future messages will be handled autonomously.");
                } else {
                    alert(`Activation failed: ${json.error}`);
                }
            } catch (err) {
                console.error(err);
                alert("Failed to resume AI.");
            } finally {
                btnResumeAi.disabled = false;
            }
        });

        btnEscalate.addEventListener("click", async () => {
            if (!activeConvId) return;
            const reason = prompt("Enter escalation reason:", "Client requested human assistance");
            if (!reason) return;

            try {
                const res = await fetch(`/api/whatsapp/conversations/${activeConvId}/escalate`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ reason })
                });
                const json = await res.json();
                if (json.success) {
                    if (activeConv) {
                        activeConv.mode = "ESCALATED";
                        activeConv.escalation_reason = reason;
                    }
                    updateChatHeaderUI();
                    loadConversations(false);
                    showToast("Conversation marked as escalated.");
                }
            } catch (err) {
                console.error(err);
            }
        });

        btnCloseChat.addEventListener("click", async () => {
            if (!activeConvId) return;
            if (!confirm("Are you sure you want to close this conversation?")) return;

            try {
                const res = await fetch(`/api/whatsapp/conversations/${activeConvId}/close`, {
                    method: "POST"
                });
                const json = await res.json();
                if (json.success) {
                    if (activeConv) activeConv.mode = "CLOSED";
                    updateChatHeaderUI();
                    loadConversations(false);
                    showToast("Conversation closed.");
                }
            } catch (err) {
                console.error(err);
            }
        });

        // Sending Manual Message
        composerForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const text = composerInput.value.trim();
            if (!text || !activeConvId) return;

            composerInput.value = "";
            try {
                const res = await fetch(`/api/whatsapp/conversations/${activeConvId}/messages`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        content: text,
                        sender_name: "Administrator"
                    })
                });
                const json = await res.json();
                if (json.success) {
                    if (activeConv) {
                        activeConv.mode = "HUMAN_ACTIVE";
                        activeConv.version = json.version || (activeConv.version + 1);
                    }
                    updateChatHeaderUI();
                    loadConversations(false);
                } else {
                    alert(`Message could not be sent: ${json.error || "Error"}`);
                }
            } catch (err) {
                console.error("Send message error", err);
                alert("Failed to send message.");
            }
        });

        // AI Draft Suggestion
        btnGenerateDraft.addEventListener("click", async () => {
            if (!activeConvId) return;
            btnGenerateDraft.disabled = true;
            btnGenerateDraft.textContent = "⏳ Generating draft...";

            try {
                const res = await fetch(`/api/whatsapp/conversations/${activeConvId}/suggest-draft`, {
                    method: "POST"
                });
                const json = await res.json();
                if (json.success && json.draft) {
                    draftText.textContent = json.draft;
                    draftBox.style.display = "block";
                } else {
                    alert(`Could not generate draft: ${json.error || "Error"}`);
                }
            } catch (err) {
                console.error(err);
                alert("Failed to retrieve AI draft.");
            } finally {
                btnGenerateDraft.disabled = false;
                btnGenerateDraft.textContent = "✨ Suggest AI Draft";
            }
        });

        btnUseDraft.addEventListener("click", () => {
            if (draftText && composerInput) {
                composerInput.value = draftText.textContent;
                composerInput.focus();
                draftBox.style.display = "none";
            }
        });

        btnDismissDraft.addEventListener("click", () => {
            draftBox.style.display = "none";
        });

        // Dossier & Account Linking
        async function loadCandidatesForLinking() {
            try {
                const res = await fetch("/api/clients");
                const json = await res.json();
                if (json.success && Array.isArray(json.clients)) {
                    candidateCache = json.clients;
                    if (clientLinkSelect) {
                        clientLinkSelect.innerHTML = `<option value="">Select candidate...</option>` +
                            candidateCache.map(c => `
                                <option value="${escapeHtml(c.id)}">${escapeHtml(c.name || c.id)} (${escapeHtml(c.email || c.profession || "")})</option>
                            `).join("");
                    }
                }
            } catch (err) {
                console.error("Failed to load candidates for linking", err);
            }
        }

        btnLinkClient.addEventListener("click", async () => {
            if (!activeConvId || !clientLinkSelect.value) return;
            const clientId = clientLinkSelect.value;
            try {
                const res = await fetch(`/api/whatsapp/conversations/${activeConvId}/link-client`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ client_id: clientId })
                });
                const json = await res.json();
                if (json.success) {
                    if (activeConv) activeConv.client_id = clientId;
                    await loadClientDossier(clientId, activeConv ? activeConv.wa_id : null);
                    loadConversations(false);
                    showToast("Candidate account linked successfully.");
                }
            } catch (err) {
                console.error(err);
            }
        });

        async function loadClientDossier(clientId, waId) {
            if (!dossierDetails || !dossierEmptyState) return;

            if (!clientId) {
                dossierDetails.style.display = "none";
                dossierEmptyState.style.display = "block";
                if (dossierVerifyBadge) {
                    dossierVerifyBadge.className = "wa-verify-pill pill-guest";
                    dossierVerifyBadge.textContent = "Guest (Unverified)";
                }
                return;
            }

            try {
                const res = await fetch(`/api/whatsapp/tools/execute`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        tool_name: "get_client_profile",
                        tool_args: { client_id: clientId },
                        client_id: clientId,
                        wa_id: waId
                    })
                });
                const json = await res.json();
                if (json.success && json.result) {
                    const data = json.result;
                    dossierEmptyState.style.display = "none";
                    dossierDetails.style.display = "block";

                    if (dossierVerifyBadge) {
                        dossierVerifyBadge.className = "wa-verify-pill pill-verified";
                        dossierVerifyBadge.textContent = "✓ Verified";
                    }

                    if (dossierName) dossierName.textContent = data.full_name || "—";
                    if (dossierClientId) dossierClientId.textContent = data.client_id || clientId;
                    if (dossierEmail) dossierEmail.textContent = data.email || "—";
                    if (dossierPayment) {
                        const isPaid = data.payment_status === "Bezahlt" || data.payment_status === "Paid";
                        dossierPayment.innerHTML = isPaid
                            ? `<span class="wa-tag-green">Paid</span>`
                            : `<span class="wa-tag-amber">${escapeHtml(data.payment_status || "Pending")}</span>`;
                    }

                    if (dossierProfession) dossierProfession.textContent = data.ausbildung_field || "Not specified";

                    // Load stats
                    loadDossierStats(clientId);
                    // Check dataset availability
                    loadDatasetAvailability(data.ausbildung_field);
                    // Documents
                    renderDocumentList(data.documents);
                }
            } catch (err) {
                console.error("Dossier load error", err);
            }
        }

        async function loadDossierStats(clientId) {
            try {
                const res = await fetch(`/api/whatsapp/tools/execute`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        tool_name: "get_client_application_statistics",
                        tool_args: { client_id: clientId },
                        client_id: clientId
                    })
                });
                const json = await res.json();
                if (json.success && json.result) {
                    const r = json.result;
                    if (dossierAppsSent) dossierAppsSent.textContent = r.sent_applications_count || 0;
                    if (dossierAppsReplied) dossierAppsReplied.textContent = r.replies_count || 0;
                    if (dossierAppsInterviews) dossierAppsInterviews.textContent = r.interviews_count || 0;
                    if (dossierAppStatus) dossierAppStatus.textContent = r.status || "In Progress";
                }
            } catch (e) {}
        }

        async function loadDatasetAvailability(profession) {
            if (!profession || !dossierDatasetBadge) return;
            dossierDatasetBadge.textContent = "Checking...";
            dossierDatasetBadge.className = "wa-badge-dataset";

            try {
                const res = await fetch(`/api/whatsapp/tools/execute`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        tool_name: "get_profession_dataset_availability",
                        tool_args: { profession: profession }
                    })
                });
                const json = await res.json();
                if (json.success && json.result) {
                    const r = json.result;
                    if (r.has_exact_match) {
                        dossierDatasetBadge.textContent = "Available";
                        dossierDatasetBadge.className = "wa-badge-dataset badge-green";
                    } else if (r.has_similar_match) {
                        dossierDatasetBadge.textContent = "Similar";
                        dossierDatasetBadge.className = "wa-badge-dataset badge-yellow";
                    } else {
                        dossierDatasetBadge.textContent = "Missing";
                        dossierDatasetBadge.className = "wa-badge-dataset badge-red";
                    }
                    if (dossierDatasetDetail) {
                        dossierDatasetDetail.textContent = r.message || "";
                    }
                }
            } catch (e) {}
        }

        function renderDocumentList(docs) {
            if (!dossierDocsList) return;
            const items = [
                { key: "cv", label: "Resume / CV", checked: docs && (docs.cv || docs.cv_url) },
                { key: "certificates", label: "Certificates / Diplomas", checked: docs && docs.certificates },
                { key: "cover_letter", label: "Cover Letter Template", checked: docs && docs.cover_letter },
            ];

            dossierDocsList.innerHTML = items.map(d => `
                <div class="wa-doc-item">
                    <span class="wa-doc-icon">${d.checked ? "✅" : "⚪"}</span>
                    <span class="wa-doc-label ${d.checked ? "doc-uploaded" : "doc-missing"}">${d.label}</span>
                </div>
            `).join("");
        }

        // Metrics & Audit Logs
        async function loadMetrics() {
            try {
                const res = await fetch("/api/whatsapp/metrics");
                const json = await res.json();
                if (json.success && json.data) {
                    const m = json.data;
                    if (metricAiActive) metricAiActive.textContent = m.active_ai_conversations || 0;
                    if (metricHumanActive) metricHumanActive.textContent = m.human_managed_conversations || 0;
                    if (metricEscalations) metricEscalations.textContent = m.pending_escalations || 0;
                    if (metricMessagesToday) metricMessagesToday.textContent = m.messages_today || 0;
                    if (metricFailedMessages) metricFailedMessages.textContent = m.failed_messages || 0;
                    if (metricAiCost) metricAiCost.textContent = `$${Number(m.estimated_ai_cost_usd || 0).toFixed(4)}`;
                    if (metricTokens) metricTokens.textContent = `${m.tokens_total || 0} Tokens`;
                    if (metricLatency) metricLatency.textContent = `${Number(m.avg_latency_seconds || 1.1).toFixed(1)}s`;
                    if (metricTakeoverRate) metricTakeoverRate.textContent = `${Number(m.takeover_rate_percent || 0).toFixed(0)}%`;
                }
            } catch (err) {
                console.error("Failed to load metrics", err);
            }
        }

        async function loadAuditLogs() {
            if (!auditTableBody) return;
            try {
                const res = await fetch("/api/whatsapp/audit-logs?limit=30");
                const json = await res.json();
                if (json.success && Array.isArray(json.data)) {
                    if (json.data.length === 0) {
                        auditTableBody.innerHTML = `<tr><td colspan="5" class="wa-td-empty">No audit events recorded.</td></tr>`;
                        return;
                    }
                    auditTableBody.innerHTML = json.data.map(log => `
                        <tr>
                            <td class="font-mono" style="font-size:11.5px;">${formatDateTime(log.created_at)}</td>
                            <td><span class="wa-audit-badge action-${log.action}">${escapeHtml(log.action)}</span></td>
                            <td class="font-mono" style="font-size:11.5px;">${escapeHtml(log.conversation_id ? log.conversation_id.slice(0, 8) : "—")}</td>
                            <td>${escapeHtml(log.performed_by || "System")}</td>
                            <td style="font-size:12px; color:#94a3b8;">${escapeHtml(log.details || "")}</td>
                        </tr>
                    `).join("");
                }
            } catch (err) {
                console.error("Failed to load audit logs", err);
            }
        }

        if (btnRefreshAudit) btnRefreshAudit.addEventListener("click", loadAuditLogs);

        // Settings / AI Config
        async function loadSettings() {
            try {
                const res = await fetch("/api/whatsapp/settings");
                const json = await res.json();
                if (json.success && json.settings) {
                    const s = json.settings;
                    isEmergencyPaused = s.ai_enabled === "false" || s.ai_enabled === false;
                    if (configAiEnabled) configAiEnabled.checked = !isEmergencyPaused;
                    if (configProvider) configProvider.value = s.primary_provider || "openai";
                    if (configModel) configModel.value = s.primary_model || "gpt-6-luna";
                    if (configFallbackEnabled) configFallbackEnabled.checked = s.fallback_provider_enabled !== "false";
                    if (configBrandVoice) configBrandVoice.value = s.brand_voice || "";
                    if (configSystemPrompt) configSystemPrompt.value = s.system_prompt || "";
                    if (configMaxTokens) configMaxTokens.value = s.max_response_tokens || 450;

                    if (setupVerifyToken && s.meta_verify_token) setupVerifyToken.value = s.meta_verify_token;
                    if (setupPhoneId && s.meta_phone_number_id) setupPhoneId.value = s.meta_phone_number_id;

                    updatePauseHeaderButton();
                }
            } catch (err) {
                console.error("Failed to load settings", err);
            }
        }

        function updatePauseHeaderButton() {
            if (btnEmergencyPauseHeader) {
                if (isEmergencyPaused) {
                    btnEmergencyPauseHeader.classList.add("paused");
                    btnEmergencyPauseHeader.innerHTML = "▶️ Resume AI (Paused)";
                } else {
                    btnEmergencyPauseHeader.classList.remove("paused");
                    btnEmergencyPauseHeader.innerHTML = "⏸️ Emergency AI Pause";
                }
            }
        }

        if (btnEmergencyPauseHeader) {
            btnEmergencyPauseHeader.addEventListener("click", async () => {
                const nextState = !isEmergencyPaused;
                try {
                    await fetch("/api/whatsapp/settings", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ ai_enabled: nextState ? "false" : "true" })
                    });
                    isEmergencyPaused = nextState;
                    if (configAiEnabled) configAiEnabled.checked = !isEmergencyPaused;
                    updatePauseHeaderButton();
                    showToast(isEmergencyPaused ? "Emergency pause enabled: Autonomous AI replies stopped." : "Autonomous AI replies resumed.");
                } catch (e) {
                    console.error(e);
                }
            });
        }

        if (configAiEnabled) {
            configAiEnabled.addEventListener("change", async () => {
                const active = configAiEnabled.checked;
                isEmergencyPaused = !active;
                updatePauseHeaderButton();
                await fetch("/api/whatsapp/settings", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ ai_enabled: active ? "true" : "false" })
                });
            });
        }

        if (btnSaveConfig) {
            btnSaveConfig.addEventListener("click", async () => {
                btnSaveConfig.disabled = true;
                if (configSaveStatus) configSaveStatus.textContent = "Saving...";

                const payload = {
                    primary_provider: configProvider.value,
                    primary_model: configModel.value,
                    fallback_provider_enabled: configFallbackEnabled.checked ? "true" : "false",
                    brand_voice: configBrandVoice.value,
                    system_prompt: configSystemPrompt.value,
                    max_response_tokens: configMaxTokens.value,
                    ai_enabled: configAiEnabled.checked ? "true" : "false",
                };

                try {
                    const res = await fetch("/api/whatsapp/settings", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload)
                    });
                    const json = await res.json();
                    if (json.success) {
                        if (configSaveStatus) configSaveStatus.textContent = "✓ Saved!";
                        setTimeout(() => { if (configSaveStatus) configSaveStatus.textContent = ""; }, 3000);
                    }
                } catch (err) {
                    console.error(err);
                    if (configSaveStatus) configSaveStatus.textContent = "Error saving settings";
                } finally {
                    btnSaveConfig.disabled = false;
                }
            });
        }

        if (btnSaveCredentials) {
            btnSaveCredentials.addEventListener("click", async () => {
                const payload = {
                    meta_verify_token: setupVerifyToken.value,
                    meta_phone_number_id: setupPhoneId.value,
                };
                if (setupToken.value) {
                    payload.meta_access_token = setupToken.value;
                }

                try {
                    const res = await fetch("/api/whatsapp/settings", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload)
                    });
                    const json = await res.json();
                    if (json.success) {
                        alert("Meta API credentials saved securely.");
                        setupToken.value = "";
                    }
                } catch (e) {
                    console.error(e);
                }
            });
        }

        if (btnCopyWebhook) {
            btnCopyWebhook.addEventListener("click", () => {
                if (setupWebhookUrl) {
                    navigator.clipboard.writeText(setupWebhookUrl.value);
                    btnCopyWebhook.textContent = "Copied!";
                    setTimeout(() => { btnCopyWebhook.textContent = "Copy"; }, 2000);
                }
            });
        }

        // Knowledge Base CRUD
        async function loadKnowledgeBase() {
            if (!kbTableBody) return;
            const query = (kbSearch ? kbSearch.value : "").trim();
            const category = kbCatFilter ? kbCatFilter.value : "";

            let url = "/api/whatsapp/knowledge-base?";
            if (query) url += `query=${encodeURIComponent(query)}&`;
            if (category) url += `category=${encodeURIComponent(category)}`;

            try {
                const res = await fetch(url);
                const json = await res.json();
                if (json.success && Array.isArray(json.data)) {
                    if (json.data.length === 0) {
                        kbTableBody.innerHTML = `<tr><td colspan="6" class="wa-td-empty">No knowledge base articles found.</td></tr>`;
                        return;
                    }
                    kbTableBody.innerHTML = json.data.map(item => `
                        <tr>
                            <td><span class="wa-cat-tag cat-${item.category}">${escapeHtml(item.category)}</span></td>
                            <td class="font-bold">${escapeHtml(item.title)}</td>
                            <td style="max-width:320px; font-size:12.5px; color:#cbd5e1;">${escapeHtml(item.content.slice(0, 120))}${item.content.length > 120 ? "..." : ""}</td>
                            <td style="font-size:11.5px; color:#94a3b8;">${escapeHtml(item.keywords || "—")}</td>
                            <td><span class="wa-tag-green">Active</span></td>
                            <td>
                                <div style="display:flex; gap:6px;">
                                    <button type="button" class="wa-btn-sm-edit" data-edit-kb="${item.id}">Edit</button>
                                    <button type="button" class="wa-btn-sm-del" data-del-kb="${item.id}">Delete</button>
                                </div>
                            </td>
                        </tr>
                    `).join("");

                    kbTableBody.querySelectorAll("[data-edit-kb]").forEach(btn => {
                        btn.addEventListener("click", () => {
                            const id = btn.getAttribute("data-edit-kb");
                            const item = json.data.find(d => d.id === id);
                            if (item) openKbModal(item);
                        });
                    });

                    kbTableBody.querySelectorAll("[data-del-kb]").forEach(btn => {
                        btn.addEventListener("click", async () => {
                            const id = btn.getAttribute("data-del-kb");
                            if (confirm("Are you sure you want to delete this article?")) {
                                await fetch(`/api/whatsapp/knowledge-base/${id}`, { method: "DELETE" });
                                loadKnowledgeBase();
                            }
                        });
                    });
                }
            } catch (err) {
                console.error("Failed to load KB", err);
            }
        }

        if (kbSearch) kbSearch.addEventListener("input", debounce(loadKnowledgeBase, 300));
        if (kbCatFilter) kbCatFilter.addEventListener("change", loadKnowledgeBase);

        function openKbModal(item = null) {
            if (!kbModal) return;
            kbModal.style.display = "flex";
            if (item) {
                kbModalTitle.textContent = "Edit Knowledge Article";
                kbFormId.value = item.id;
                kbFormCategory.value = item.category;
                kbFormTitle.value = item.title;
                kbFormContent.value = item.content;
                kbFormKeywords.value = item.keywords || "";
            } else {
                kbModalTitle.textContent = "New Knowledge Article";
                kbForm.reset();
                kbFormId.value = "";
            }
        }

        if (btnAddKb) btnAddKb.addEventListener("click", () => openKbModal());
        if (btnCloseKbModal) btnCloseKbModal.addEventListener("click", () => { kbModal.style.display = "none"; });
        if (btnCancelKb) btnCancelKb.addEventListener("click", () => { kbModal.style.display = "none"; });

        if (kbForm) {
            kbForm.addEventListener("submit", async (e) => {
                e.preventDefault();
                const payload = {
                    category: kbFormCategory.value,
                    title: kbFormTitle.value,
                    content: kbFormContent.value,
                    keywords: kbFormKeywords.value,
                };
                const id = kbFormId.value;

                try {
                    let res;
                    if (id) {
                        res = await fetch(`/api/whatsapp/knowledge-base/${id}`, {
                            method: "PUT",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify(payload)
                        });
                    } else {
                        res = await fetch("/api/whatsapp/knowledge-base", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify(payload)
                        });
                    }
                    const json = await res.json();
                    if (json.success) {
                        kbModal.style.display = "none";
                        loadKnowledgeBase();
                        showToast("Knowledge article saved.");
                    }
                } catch (err) {
                    console.error("Failed to save KB article", err);
                }
            });
        }

        // Test Message Simulator
        if (btnSimulateMsg) {
            btnSimulateMsg.addEventListener("click", async () => {
                const from = (simFrom.value || "").trim();
                const name = (simName.value || "").trim();
                const text = (simBody.value || "").trim();
                if (!from || !text) return;

                btnSimulateMsg.disabled = true;
                if (simResult) simResult.textContent = "Sending webhook event to server...";

                const mockWebhookPayload = {
                    object: "whatsapp_business_account",
                    entry: [
                        {
                            id: "109823485723901",
                            changes: [
                                {
                                    value: {
                                        messaging_product: "whatsapp",
                                        metadata: {
                                            display_phone_number: "+491234567890",
                                            phone_number_id: "109823485723901"
                                        },
                                        contacts: [
                                            {
                                                profile: { name: name },
                                                wa_id: from
                                            }
                                        ],
                                        messages: [
                                            {
                                                from: from,
                                                id: "wamid.sim." + Date.now(),
                                                timestamp: String(Math.floor(Date.now() / 1000)),
                                                text: { body: text },
                                                type: "text"
                                            }
                                        ]
                                    },
                                    field: "messages"
                                }
                            ]
                        }
                    ]
                };

                try {
                    const res = await fetch("/api/whatsapp/webhook", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(mockWebhookPayload)
                    });
                    const json = await res.json();
                    if (json.status === "received") {
                        if (simResult) simResult.innerHTML = `<span style="color:#34d399;">✓ Webhook delivered successfully. Background AI processing running. Switch to the Support Inbox.</span>`;
                        setTimeout(() => loadConversations(true), 600);
                    }
                } catch (err) {
                    console.error("Simulation error", err);
                    if (simResult) simResult.innerHTML = `<span style="color:#ef4444;">Simulation error</span>`;
                } finally {
                    btnSimulateMsg.disabled = false;
                }
            });
        }

        if (btnSimQuickHuman) {
            btnSimQuickHuman.addEventListener("click", () => {
                if (simBody) simBody.value = "I would urgently like to speak with a human support agent.";
            });
        }

        // Filter chips click
        filterChips.forEach(chip => {
            chip.addEventListener("click", () => {
                filterChips.forEach(c => c.classList.remove("active"));
                chip.classList.add("active");
                activeFilter = chip.getAttribute("data-filter") || "all";
                renderConversationsList();
            });
        });

        if (searchInput) {
            searchInput.addEventListener("input", debounce(() => renderConversationsList(), 200));
        }

        if (btnRefreshConvs) {
            btnRefreshConvs.addEventListener("click", () => loadConversations(false));
        }

        // Utility Helpers
        function getModeBadgeClass(mode) {
            switch (mode) {
                case "AI_ACTIVE": return "mode-ai";
                case "HUMAN_ACTIVE": return "mode-human";
                case "ESCALATED": return "mode-escalated";
                case "AI_PAUSED": return "mode-paused";
                case "CLOSED": return "mode-closed";
                default: return "mode-ai";
            }
        }

        function getModeLabel(mode) {
            switch (mode) {
                case "AI_ACTIVE": return "🤖 AI Active";
                case "HUMAN_ACTIVE": return "👤 Human";
                case "ESCALATED": return "⚠️ Escalated";
                case "AI_PAUSED": return "⏸️ Paused";
                case "CLOSED": return "🔒 Closed";
                default: return mode || "Unknown";
            }
        }

        function getSenderTag(type) {
            switch (type) {
                case "client":
                    return `<span class="wa-sender-tag tag-client">Client</span>`;
                case "ai":
                    return `<span class="wa-sender-tag tag-ai">🤖 AI Assistant</span>`;
                case "human":
                    return `<span class="wa-sender-tag tag-human">👤 Agent</span>`;
                default:
                    return `<span class="wa-sender-tag">${escapeHtml(type)}</span>`;
            }
        }

        function renderDeliveryIcon(status) {
            switch (status) {
                case "read": return `<span class="wa-tick tick-read" title="Read">✓✓</span>`;
                case "delivered": return `<span class="wa-tick tick-delivered" title="Delivered">✓✓</span>`;
                case "sent": return `<span class="wa-tick tick-sent" title="Sent">✓</span>`;
                case "failed": return `<span class="wa-tick tick-failed" title="Failed">⚠️</span>`;
                default: return `<span class="wa-tick">✓</span>`;
            }
        }

        function formatMessageText(text) {
            if (!text) return "";
            return escapeHtml(text).replace(/\n/g, "<br>");
        }

        function formatTime(isoStr) {
            if (!isoStr) return "";
            const d = new Date(isoStr);
            return isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        }

        function formatDateTime(isoStr) {
            if (!isoStr) return "";
            const d = new Date(isoStr);
            return isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-US") + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        }

        function formatRelativeTime(isoStr) {
            if (!isoStr) return "";
            const d = new Date(isoStr);
            if (isNaN(d.getTime())) return "";
            const diffMin = Math.floor((Date.now() - d.getTime()) / 60000);
            if (diffMin < 1) return "Just now";
            if (diffMin < 60) return `${diffMin}m`;
            const diffHours = Math.floor(diffMin / 60);
            if (diffHours < 24) return `${diffHours}h`;
            return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
        }

        function escapeHtml(str) {
            if (!str) return "";
            return String(str)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }

        function debounce(fn, ms) {
            let timer;
            return function (...args) {
                clearTimeout(timer);
                timer = setTimeout(() => fn.apply(this, args), ms);
            };
        }

        function showToast(msg) {
            const toast = document.createElement("div");
            toast.className = "wa-toast";
            toast.textContent = msg;
            document.body.appendChild(toast);
            setTimeout(() => {
                toast.classList.add("visible");
            }, 10);
            setTimeout(() => {
                toast.classList.remove("visible");
                setTimeout(() => toast.remove(), 300);
            }, 3000);
        }

        // Section Lifecycle API
        return {
            show() {
                initSSE();
                loadConversations(true);
                loadCandidatesForLinking();
                loadSettings();
                updateWebhookUrl();
            },
            hide() {
                if (sseSource) {
                    sseSource.close();
                    sseSource = null;
                }
            }
        };
    };
})();

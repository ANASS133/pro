(function () {
    const sections = window.SPASections || {};

    sections.createDashboardSection = function createDashboardSection() {
        const cardsRoot = document.getElementById("dashboard-cards");
        const emptyState = document.getElementById("dashboard-empty");
        const statusNode = document.getElementById("dashboard-status");

        if (!cardsRoot || !emptyState || !statusNode) {
            return {
                show() {},
                hide() {},
            };
        }

        const escapeHtml = window.SPAUtils.escapeHtml;
        const clampPercent = window.SPAUtils.clampPercent;
        const fetchJson = window.SPAUtils.fetchJson;
        const pendingPauseActions = new Map();
        const pendingDeletes = new Set();
        let pollTimer = null;
        let isLoading = false;
        let lastCampaigns = [];

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

        function renderCampaignCard(campaign) {
            const campaignId = String(campaign.id || "");
            const totalRows = Number(campaign.total_rows || 0);
            const sentRows = Number(campaign.sent_rows || 0);
            const remainingRows = Number(campaign.remaining_rows || 0);
            const hasActiveJob = Boolean(campaign.has_active_job && campaign.active_job);
            const activeJob = campaign.active_job || null;
            const jobStatus = String(activeJob && activeJob.status || "");
            const pendingPauseAction = pendingPauseActions.get(campaignId) || "";
            const isPaused = jobStatus === "paused";
            const pauseAction = isPaused ? "continue" : "pause";
            const pauseLabel = pendingPauseAction
                ? (pendingPauseAction === "continue" ? "Continuing..." : "Pausing...")
                : (isPaused ? "Continue" : "Pause");
            const hasAnschreibenData = Boolean(campaign.has_anschreiben_data);
            const canEdit = !hasActiveJob && hasAnschreibenData && String(campaign.mode || "") === "transfer";
            const percent = clampPercent(
                campaign.progress_percent != null
                    ? campaign.progress_percent
                    : (totalRows > 0 ? (sentRows / totalRows) * 100 : 0),
            );
            let statusText = "Bereit";
            let statusClass = "";

            if (campaign.is_sending) {
                statusText = "Versand laeuft";
                statusClass = "sending";
            } else if (campaign.is_paused) {
                statusText = "Pausiert";
                statusClass = "paused";
            } else if (totalRows > 0 && remainingRows === 0) {
                statusText = "Abgeschlossen";
                statusClass = "done";
            }

            const activeJobMessage = hasActiveJob
                ? String(activeJob.message || "").trim()
                : "";
            const runTotal = Number(activeJob && activeJob.total || 0);
            const runProcessed = Number(activeJob && activeJob.processed || 0);
            const runPercent = clampPercent(activeJob && activeJob.percent || 0);
            const runInfo = runTotal > 0
                ? `Lauf ${runProcessed}/${runTotal} (${runPercent.toFixed(1)}%)`
                : "";
            const subtext = hasActiveJob
                ? (activeJobMessage ? (runInfo ? `${runInfo} | ${activeJobMessage}` : activeJobMessage) : (runInfo || `${sentRows}/${totalRows} gesendet, ${remainingRows} offen.`))
                : `${sentRows}/${totalRows} gesendet, ${remainingRows} offen.`;

            return `
                <article class="campaign-card" data-campaign-id="${escapeHtml(campaignId)}">
                    <h3>${escapeHtml(campaign.full_name || campaign.name || "Unnamed campaign")}</h3>
                    <div class="campaign-meta">
                        Modus: <strong>${escapeHtml(campaign.mode || "")}</strong><br>
                        Absender: <span>${escapeHtml(campaign.sender_email || "k. A.")}</span><br>
                        Anhaenge: <span>${escapeHtml(campaign.attachment_count || 0)}</span><br>
                        Aktualisiert: <span>${escapeHtml(campaign.updated_at || "")}</span>
                    </div>

                    <div class="campaign-stats">
                        <div class="campaign-stat">
                            <strong>${totalRows}</strong>
                            <span>Gesamt</span>
                        </div>
                        <div class="campaign-stat">
                            <strong>${sentRows}</strong>
                            <span>Gesendet</span>
                        </div>
                        <div class="campaign-stat">
                            <strong>${remainingRows}</strong>
                            <span>Offen</span>
                        </div>
                    </div>

                    <div class="campaign-actions">
                        <a class="action-btn primary" href="/send-emails?campaign=${encodeURIComponent(campaignId)}">Versand öffnen</a>
                        <a class="action-btn secondary${canEdit ? "" : " disabled"}" href="${canEdit ? `/create-anschreibens?edit_campaign=${encodeURIComponent(campaignId)}` : "#"}">Edit Anschreiben</a>
                        ${hasActiveJob ? `
                            <button
                                type="button"
                                class="action-btn warning dashboard-pause-btn"
                                data-campaign-id="${escapeHtml(campaignId)}"
                                data-job-id="${escapeHtml(activeJob && activeJob.job_id || "")}"
                                data-action="${pauseAction}"
                                ${pendingPauseAction ? "disabled" : ""}
                            >
                                ${pauseLabel}
                            </button>
                        ` : ""}
                        <button
                            type="button"
                            class="action-btn danger dashboard-delete-btn"
                            data-campaign-id="${escapeHtml(campaignId)}"
                            ${hasActiveJob || pendingDeletes.has(campaignId) ? "disabled" : ""}
                        >
                            ${pendingDeletes.has(campaignId) ? "Lösche..." : (hasActiveJob ? "Versand aktiv" : "Löschen")}
                        </button>
                    </div>

                    <div class="campaign-progress-head">
                        <span class="campaign-progress-status ${statusClass}">${statusText}</span>
                        <span>${percent.toFixed(1)}%</span>
                    </div>
                    <div class="campaign-progress-track">
                        <div class="campaign-progress-fill" style="width:${percent.toFixed(2)}%;"></div>
                    </div>
                    <div class="campaign-progress-subtext">${escapeHtml(subtext)}</div>
                </article>
            `;
        }

        function renderDashboard(campaigns) {
            const items = Array.isArray(campaigns) ? campaigns : [];
            lastCampaigns = items;
            emptyState.hidden = items.length > 0;
            cardsRoot.innerHTML = items.map(renderCampaignCard).join("");
        }

        async function loadDashboard() {
            if (isLoading) {
                return;
            }

            isLoading = true;
            try {
                const payload = await fetchJson("/api/dashboard/campaigns");
                if (!payload.success || !Array.isArray(payload.campaigns)) {
                    throw new Error(payload.message || "Dashboard-Daten konnten nicht geladen werden");
                }
                setStatus("", false);
                renderDashboard(payload.campaigns);
            } catch (error) {
                setStatus(error.message || "Dashboard-Daten konnten nicht geladen werden.", true);
            } finally {
                isLoading = false;
            }
        }

        function startPolling() {
            if (pollTimer) {
                return;
            }
            loadDashboard();
            pollTimer = window.setInterval(loadDashboard, 1500);
        }

        function stopPolling() {
            if (pollTimer) {
                window.clearInterval(pollTimer);
                pollTimer = null;
            }
        }

        async function toggleCampaignJob(button) {
            const jobId = String(button.dataset.jobId || "").trim();
            const campaignId = String(button.dataset.campaignId || "").trim();
            const action = String(button.dataset.action || "pause").trim() === "continue"
                ? "continue"
                : "pause";

            if (!jobId || !campaignId) {
                return;
            }

            pendingPauseActions.set(campaignId, action);
            renderDashboard(lastCampaigns);

            try {
                const payload = await fetchJson(`/api/send-bulk/${action}/${encodeURIComponent(jobId)}`, {
                    method: "POST",
                });
                if (!payload.success) {
                    throw new Error(
                        payload.message
                        || (action === "continue"
                            ? "Continue konnte nicht angefordert werden"
                            : "Pause konnte nicht angefordert werden"),
                    );
                }
                setStatus(action === "continue" ? "Continue angefordert." : "Pause angefordert.", false);
            } catch (error) {
                setStatus(error.message || "Aktion konnte nicht angefordert werden.", true);
            } finally {
                pendingPauseActions.delete(campaignId);
                await loadDashboard();
            }
        }

        async function deleteCampaign(button) {
            const campaignId = String(button.dataset.campaignId || "").trim();
            if (!campaignId) {
                return;
            }

            const confirmed = window.confirm("Diese gespeicherte Vorlage löschen? Das kann nicht rückgängig gemacht werden.");
            if (!confirmed) {
                return;
            }

            pendingDeletes.add(campaignId);
            renderDashboard(lastCampaigns);

            try {
                const payload = await fetchJson(`/api/campaign/delete/${encodeURIComponent(campaignId)}`, {
                    method: "POST",
                });
                if (!payload.success) {
                    throw new Error(payload.message || "Kampagne konnte nicht gelöscht werden");
                }
                setStatus("Kampagne gelöscht.", false);
            } catch (error) {
                setStatus(error.message || "Kampagne konnte nicht gelöscht werden.", true);
            } finally {
                pendingDeletes.delete(campaignId);
                await loadDashboard();
            }
        }

        cardsRoot.addEventListener("click", (event) => {
            const pauseButton = event.target.closest(".dashboard-pause-btn");
            if (pauseButton) {
                toggleCampaignJob(pauseButton).catch(() => {});
                return;
            }

            const deleteButton = event.target.closest(".dashboard-delete-btn");
            if (deleteButton) {
                deleteCampaign(deleteButton).catch(() => {});
            }
        });

        window.addEventListener("beforeunload", stopPolling);

        return {
            show() {
                startPolling();
            },
            hide() {
                stopPolling();
            },
        };
    };

    window.SPASections = sections;
})();

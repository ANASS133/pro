/**
 * JobScout AI Settings SPA Section Controller
 * Manages official OpenAI (GPT-6 Luna), Google Gemini, and Offline processing.
 * Strictly adheres to security rules: keys are masked, never stored in localStorage,
 * and connection testing does NOT make paid inference calls.
 */
(function () {
    const sections = window.SPASections || {};

    sections.createAISettingsSection = function createAISettingsSection() {
        const root = document.getElementById("ai-settings-section");
        if (!root) {
            return { show() {}, hide() {} };
        }

        // Provider Radios
        const providerRadios = Array.from(root.querySelectorAll("input[name='ai_primary_provider']"));
        const fallbackToggle = document.getElementById("ai-gemini-fallback-toggle");

        // OpenAI Elements
        const openaiKeyInput = document.getElementById("ai-openai-key-input");
        const openaiToggleBtn = document.getElementById("ai-openai-toggle-key");
        const openaiSaveBtn = document.getElementById("ai-openai-save-btn");
        const openaiTestBtn = document.getElementById("ai-openai-test-btn");
        const openaiModelSelect = document.getElementById("ai-openai-model-select");
        const openaiStatusBadge = document.getElementById("ai-openai-status-badge");
        const openaiStatusMsg = document.getElementById("ai-openai-status-msg");
        const openaiLastTested = document.getElementById("ai-openai-last-tested");
        const openaiKeyBadge = document.getElementById("ai-openai-key-badge");

        // Gemini Elements
        const geminiKeyInput = document.getElementById("ai-gemini-key-input");
        const geminiToggleBtn = document.getElementById("ai-gemini-toggle-key");
        const geminiSaveBtn = document.getElementById("ai-gemini-save-btn");
        const geminiTestBtn = document.getElementById("ai-gemini-test-btn");
        const geminiModelSelect = document.getElementById("ai-gemini-model-select");
        const geminiStatusBadge = document.getElementById("ai-gemini-status-badge");
        const geminiStatusMsg = document.getElementById("ai-gemini-status-msg");
        const geminiLastTested = document.getElementById("ai-gemini-last-tested");
        const geminiKeyBadge = document.getElementById("ai-gemini-key-badge");

        // Usage Dashboard Elements
        const usageProviderEl = document.getElementById("ai-usage-provider");
        const usageModelEl = document.getElementById("ai-usage-model");
        const usageTotalRequestsEl = document.getElementById("ai-usage-total-requests");
        const usageSuccessRequestsEl = document.getElementById("ai-usage-success-requests");
        const usageFailedRequestsEl = document.getElementById("ai-usage-failed-requests");
        const usageInputTokensEl = document.getElementById("ai-usage-input-tokens");
        const usageOutputTokensEl = document.getElementById("ai-usage-output-tokens");
        const usageTotalTokensEl = document.getElementById("ai-usage-total-tokens");
        const usageEstimatedCostEl = document.getElementById("ai-usage-estimated-cost");
        const usageCacheHitsEl = document.getElementById("ai-usage-cache-hits");
        const usageCacheRateEl = document.getElementById("ai-usage-cache-rate");
        const usageDailyTableBody = document.getElementById("ai-usage-daily-body");
        const btnResetCache = document.getElementById("ai-btn-reset-cache");
        const btnRefreshUsage = document.getElementById("ai-btn-refresh-usage");
        const alertBanner = document.getElementById("ai-settings-alert");

        let currentSettings = null;

        function showAlert(msg, isSuccess = true) {
            if (!alertBanner) return;
            alertBanner.textContent = msg;
            alertBanner.className = `ai-alert ${isSuccess ? "ai-alert-success" : "ai-alert-error"}`;
            alertBanner.hidden = false;
            setTimeout(() => {
                if (alertBanner) alertBanner.hidden = true;
            }, 6000);
        }

        async function fetchSettings() {
            try {
                const res = await fetch("/api/ai/settings");
                if (!res.ok) throw new Error("HTTP " + res.status);
                const data = await res.json();
                if (data.success && data.settings) {
                    currentSettings = data.settings;
                    renderSettings(data.settings);
                }
            } catch (err) {
                console.error("Failed to load AI settings:", err);
                showAlert("Fehler beim Laden der AI-Einstellungen.", false);
            }
        }

        function renderSettings(settings) {
            // 1. Primary Provider selection
            providerRadios.forEach(radio => {
                radio.checked = (radio.value === settings.primary_provider);
            });

            if (fallbackToggle) {
                fallbackToggle.checked = Boolean(settings.enable_gemini_fallback);
            }

            // 2. OpenAI Section
            if (openaiKeyInput) {
                openaiKeyInput.value = "";
                openaiKeyInput.placeholder = settings.openai_has_key
                    ? `${settings.openai_masked_key} (Gespeichert)`
                    : "sk-proj-...";
            }
            if (openaiKeyBadge) {
                openaiKeyBadge.textContent = settings.openai_has_key ? "Gespeichert & Aktiv" : "Nicht konfiguriert";
                openaiKeyBadge.className = `ai-status-pill ${settings.openai_has_key ? "pill-active" : "pill-inactive"}`;
            }
            if (openaiModelSelect && settings.openai_model) {
                openaiModelSelect.value = settings.openai_model;
            }
            updateStatusBadge(openaiStatusBadge, settings.openai_status);
            if (openaiLastTested) {
                openaiLastTested.textContent = settings.last_tested_openai
                    ? new Date(settings.last_tested_openai).toLocaleString("de-DE")
                    : "Noch nicht getestet";
            }

            // 3. Gemini Section
            if (geminiKeyInput) {
                geminiKeyInput.value = "";
                geminiKeyInput.placeholder = settings.gemini_has_key
                    ? `${settings.gemini_masked_key} (Gespeichert)`
                    : "AIzaSy...";
            }
            if (geminiKeyBadge) {
                geminiKeyBadge.textContent = settings.gemini_has_key ? "Gespeichert & Aktiv" : "Nicht konfiguriert";
                geminiKeyBadge.className = `ai-status-pill ${settings.gemini_has_key ? "pill-active" : "pill-inactive"}`;
            }
            if (geminiModelSelect && settings.gemini_model) {
                geminiModelSelect.value = settings.gemini_model;
            }
            updateStatusBadge(geminiStatusBadge, settings.gemini_status);
            if (geminiLastTested) {
                geminiLastTested.textContent = settings.last_tested_gemini
                    ? new Date(settings.last_tested_gemini).toLocaleString("de-DE")
                    : "Noch nicht getestet";
            }

            // 4. Update usage summary widget
            if (usageProviderEl) {
                const provLabels = { openai: "Official OpenAI (GPT Luna)", gemini: "Google Gemini", offline: "Lokale Heuristik (Offline)" };
                usageProviderEl.textContent = provLabels[settings.primary_provider] || settings.primary_provider;
            }
            if (usageModelEl) {
                usageModelEl.textContent = settings.primary_provider === "openai" ? settings.openai_model : settings.gemini_model;
            }
        }

        function updateStatusBadge(badgeEl, status) {
            if (!badgeEl) return;
            badgeEl.className = "ai-status-pill";
            if (status === "connected") {
                badgeEl.classList.add("pill-connected");
                badgeEl.textContent = "Verbunden ✓";
            } else if (status === "error") {
                badgeEl.classList.add("pill-error");
                badgeEl.textContent = "Fehler ✕";
            } else {
                badgeEl.classList.add("pill-untested");
                badgeEl.textContent = "Ungetestet";
            }
        }

        async function fetchUsage() {
            try {
                const res = await fetch("/api/ai/usage");
                if (!res.ok) return;
                const data = await res.json();
                if (data.success && data.usage) {
                    renderUsage(data.usage);
                }
            } catch (err) {
                console.error("Failed to load AI usage:", err);
            }
        }

        function renderUsage(usage) {
            if (usageTotalRequestsEl) usageTotalRequestsEl.textContent = (usage.total_requests || 0).toLocaleString();
            if (usageSuccessRequestsEl) usageSuccessRequestsEl.textContent = (usage.successful_requests || 0).toLocaleString();
            if (usageFailedRequestsEl) usageFailedRequestsEl.textContent = (usage.failed_requests || 0).toLocaleString();

            if (usageInputTokensEl) usageInputTokensEl.textContent = (usage.input_tokens || 0).toLocaleString();
            if (usageOutputTokensEl) usageOutputTokensEl.textContent = (usage.output_tokens || 0).toLocaleString();
            if (usageTotalTokensEl) usageTotalTokensEl.textContent = (usage.total_tokens || 0).toLocaleString();

            if (usageEstimatedCostEl) {
                const cost = usage.estimated_cost_usd || 0.0;
                usageEstimatedCostEl.textContent = `$${cost.toFixed(4)} USD`;
            }

            if (usageCacheHitsEl) usageCacheHitsEl.textContent = (usage.cache_hits || 0).toLocaleString();
            if (usageCacheRateEl) {
                const totalReqs = (usage.total_requests || 0) + (usage.cache_hits || 0);
                const rate = totalReqs > 0 ? Math.round(((usage.cache_hits || 0) / totalReqs) * 100) : 0;
                usageCacheRateEl.textContent = `${rate}% (0-Kosten)`;
            }

            // Daily usage breakdown
            if (usageDailyTableBody) {
                const daily = usage.daily_breakdown || {};
                const keys = Object.keys(daily).sort().reverse().slice(0, 7);
                if (keys.length === 0) {
                    usageDailyTableBody.innerHTML = '<tr><td colspan="5" class="ai-table-empty">Noch keine API-Aufrufe verzeichnet.</td></tr>';
                } else {
                    usageDailyTableBody.innerHTML = keys.map(day => {
                        const row = daily[day];
                        const cost = row.estimated_cost_usd || 0.0;
                        return `
                            <tr>
                                <td><strong>${day}</strong></td>
                                <td>${row.requests || 0}</td>
                                <td>${(row.input_tokens || 0).toLocaleString()}</td>
                                <td>${(row.output_tokens || 0).toLocaleString()}</td>
                                <td><span class="ai-cost-tag">$${cost.toFixed(4)}</span></td>
                            </tr>
                        `;
                    }).join("");
                }
            }
        }

        // Toggle Key Visibility for NEW typing
        if (openaiToggleBtn && openaiKeyInput) {
            openaiToggleBtn.addEventListener("click", () => {
                const isPassword = openaiKeyInput.type === "password";
                openaiKeyInput.type = isPassword ? "text" : "password";
                openaiToggleBtn.textContent = isPassword ? "Verbergen" : "Anzeigen";
            });
        }

        if (geminiToggleBtn && geminiKeyInput) {
            geminiToggleBtn.addEventListener("click", () => {
                const isPassword = geminiKeyInput.type === "password";
                geminiKeyInput.type = isPassword ? "text" : "password";
                geminiToggleBtn.textContent = isPassword ? "Verbergen" : "Anzeigen";
            });
        }

        // Save OpenAI Settings
        if (openaiSaveBtn) {
            openaiSaveBtn.addEventListener("click", async () => {
                const newKey = openaiKeyInput ? openaiKeyInput.value.trim() : "";
                const newModel = openaiModelSelect ? openaiModelSelect.value.trim() : "";

                const updates = {};
                if (newKey) updates.openai_api_key = newKey;
                if (newModel) updates.openai_model = newModel;

                try {
                    openaiSaveBtn.disabled = true;
                    openaiSaveBtn.textContent = "Speichern...";
                    const res = await fetch("/api/ai/settings", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(updates)
                    });
                    const data = await res.json();
                    if (data.success) {
                        showAlert("OpenAI-Konfiguration erfolgreich aktualisiert!");
                        if (data.settings) renderSettings(data.settings);
                    } else {
                        showAlert(`Fehler: ${data.error || "Speichern fehlgeschlagen"}`, false);
                    }
                } catch (err) {
                    showAlert(`Netzwerkfehler: ${err.message}`, false);
                } finally {
                    openaiSaveBtn.disabled = false;
                    openaiSaveBtn.textContent = "OpenAI-Einstellungen Speichern";
                }
            });
        }

        // Test OpenAI Connection (Zero Paid Inference Tokens)
        if (openaiTestBtn) {
            openaiTestBtn.addEventListener("click", async () => {
                const testKey = openaiKeyInput && openaiKeyInput.value.trim() ? openaiKeyInput.value.trim() : undefined;
                try {
                    openaiTestBtn.disabled = true;
                    openaiTestBtn.textContent = "Prüfe Verbindung...";
                    if (openaiStatusMsg) openaiStatusMsg.textContent = "Verbindung wird ohne Inferenzkosten getestet...";

                    const res = await fetch("/api/ai/test-connection", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ provider: "openai", api_key: testKey })
                    });
                    const data = await res.json();
                    if (data.success && data.status === "connected") {
                        showAlert("OpenAI-Verbindung erfolgreich hergestellt! (0 Tokens verbraucht)");
                        if (openaiStatusBadge) updateStatusBadge(openaiStatusBadge, "connected");
                        if (openaiStatusMsg) openaiStatusMsg.textContent = data.message || "Verbindung aktiv und einsatzbereit.";
                        if (openaiLastTested) openaiLastTested.textContent = new Date().toLocaleString("de-DE");
                    } else {
                        showAlert(`OpenAI-Verbindungsfehler: ${data.error || "Keine Antwort"}`, false);
                        if (openaiStatusBadge) updateStatusBadge(openaiStatusBadge, "error");
                        if (openaiStatusMsg) openaiStatusMsg.textContent = data.error || "Authentifizierung fehlgeschlagen.";
                    }
                } catch (err) {
                    showAlert(`Test fehlgeschlagen: ${err.message}`, false);
                } finally {
                    openaiTestBtn.disabled = false;
                    openaiTestBtn.textContent = "Verbindung testen (0 Kosten)";
                }
            });
        }

        // Save Gemini Settings
        if (geminiSaveBtn) {
            geminiSaveBtn.addEventListener("click", async () => {
                const newKey = geminiKeyInput ? geminiKeyInput.value.trim() : "";
                const newModel = geminiModelSelect ? geminiModelSelect.value.trim() : "";

                const updates = {};
                if (newKey) updates.gemini_api_key = newKey;
                if (newModel) updates.gemini_model = newModel;

                try {
                    geminiSaveBtn.disabled = true;
                    geminiSaveBtn.textContent = "Speichern...";
                    const res = await fetch("/api/ai/settings", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(updates)
                    });
                    const data = await res.json();
                    if (data.success) {
                        showAlert("Google Gemini-Konfiguration erfolgreich aktualisiert!");
                        if (data.settings) renderSettings(data.settings);
                    } else {
                        showAlert(`Fehler: ${data.error || "Speichern fehlgeschlagen"}`, false);
                    }
                } catch (err) {
                    showAlert(`Netzwerkfehler: ${err.message}`, false);
                } finally {
                    geminiSaveBtn.disabled = false;
                    geminiSaveBtn.textContent = "Gemini-Einstellungen Speichern";
                }
            });
        }

        // Test Gemini Connection
        if (geminiTestBtn) {
            geminiTestBtn.addEventListener("click", async () => {
                const testKey = geminiKeyInput && geminiKeyInput.value.trim() ? geminiKeyInput.value.trim() : undefined;
                try {
                    geminiTestBtn.disabled = true;
                    geminiTestBtn.textContent = "Prüfe Verbindung...";
                    if (geminiStatusMsg) geminiStatusMsg.textContent = "Verbindung wird getestet...";

                    const res = await fetch("/api/ai/test-connection", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ provider: "gemini", api_key: testKey })
                    });
                    const data = await res.json();
                    if (data.success && data.status === "connected") {
                        showAlert("Google Gemini API erfolgreich verbunden!");
                        if (geminiStatusBadge) updateStatusBadge(geminiStatusBadge, "connected");
                        if (geminiStatusMsg) geminiStatusMsg.textContent = data.message || "Verbindung aktiv.";
                        if (geminiLastTested) geminiLastTested.textContent = new Date().toLocaleString("de-DE");
                    } else {
                        showAlert(`Gemini-Verbindungsfehler: ${data.error || "Keine Antwort"}`, false);
                        if (geminiStatusBadge) updateStatusBadge(geminiStatusBadge, "error");
                        if (geminiStatusMsg) geminiStatusMsg.textContent = data.error || "Verbindung fehlgeschlagen.";
                    }
                } catch (err) {
                    showAlert(`Test fehlgeschlagen: ${err.message}`, false);
                } finally {
                    geminiTestBtn.disabled = false;
                    geminiTestBtn.textContent = "Verbindung testen";
                }
            });
        }

        // Provider change listeners
        providerRadios.forEach(radio => {
            radio.addEventListener("change", async () => {
                if (!radio.checked) return;
                const prov = radio.value;
                try {
                    const res = await fetch("/api/ai/settings", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ primary_provider: prov })
                    });
                    const data = await res.json();
                    if (data.success) {
                        showAlert(`Primärer AI-Provider gewechselt auf: ${prov.toUpperCase()}`);
                        if (data.settings) renderSettings(data.settings);
                    }
                } catch (err) {
                    showAlert(`Fehler beim Wechseln: ${err.message}`, false);
                }
            });
        });

        // Fallback toggle listener
        if (fallbackToggle) {
            fallbackToggle.addEventListener("change", async () => {
                try {
                    const res = await fetch("/api/ai/settings", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ enable_gemini_fallback: fallbackToggle.checked })
                    });
                    const data = await res.json();
                    if (data.success) {
                        showAlert(`Gemini-Fallback ${fallbackToggle.checked ? "aktiviert" : "deaktiviert"}.`);
                    }
                } catch (err) {
                    showAlert(`Fehler: ${err.message}`, false);
                }
            });
        }

        // Reset Cache
        if (btnResetCache) {
            btnResetCache.addEventListener("click", async () => {
                if (!confirm("Möchten Sie den Antwort-Cache wirklich leeren? Zukünftige identische Anfragen werden erneut an die API gesendet.")) {
                    return;
                }
                try {
                    const res = await fetch("/api/ai/reset-cache", { method: "POST" });
                    const data = await res.json();
                    if (data.success) {
                        showAlert("KI-Cache erfolgreich geleert!");
                        fetchUsage();
                    }
                } catch (err) {
                    showAlert("Fehler beim Leeren des Caches", false);
                }
            });
        }

        // Refresh Usage
        if (btnRefreshUsage) {
            btnRefreshUsage.addEventListener("click", () => {
                fetchUsage();
                showAlert("Nutzungsdaten aktualisiert.");
            });
        }

        return {
            show() {
                fetchSettings();
                fetchUsage();
            },
            hide() {}
        };
    };

    window.SPASections = sections;
})();

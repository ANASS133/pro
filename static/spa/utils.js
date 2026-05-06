(function () {
    const utils = window.SPAUtils || {};

    utils.escapeHtml = function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    };

    utils.clampPercent = function clampPercent(value) {
        const parsed = Number(value || 0);
        if (!Number.isFinite(parsed)) {
            return 0;
        }
        return Math.max(0, Math.min(100, parsed));
    };

    utils.fetchJson = async function fetchJson(url, options) {
        const response = await fetch(url, options);
        let payload = {};

        try {
            payload = await response.json();
        } catch (_error) {
            payload = {};
        }

        if (!response.ok) {
            const error = new Error(
                payload.message
                || payload.error
                || `Request failed (${response.status})`,
            );
            error.status = response.status;
            error.payload = payload;
            throw error;
        }

        return payload;
    };

    window.SPAUtils = utils;
})();

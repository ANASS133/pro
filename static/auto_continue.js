(function () {
    document.querySelectorAll('[data-auto-continue]').forEach((button) => {
        let timer = null;
        let handled = false;

        function cancelTimer() {
            if (timer !== null) {
                clearTimeout(timer);
                timer = null;
            }
        }

        function isVisible() {
            return button.isConnected && button.getClientRects().length > 0
                && getComputedStyle(button).visibility === 'visible';
        }

        function update() {
            if (!isVisible()) {
                cancelTimer();
                handled = false;
                return;
            }
            if (button.disabled) {
                cancelTimer();
                return;
            }
            // Polling may update the same styles repeatedly; keep the original deadline.
            if (handled || timer !== null) return;
            timer = setTimeout(() => {
                timer = null;
                if (isVisible() && !button.disabled) {
                    handled = true;
                    button.click();
                }
            }, 5000);
        }

        button.addEventListener('click', () => {
            handled = true;
            cancelTimer();
        }, true);

        const observer = new MutationObserver(update);
        // Watch ancestors too: progress panels and SPA sections control visibility.
        for (let element = button; element; element = element.parentElement) {
            observer.observe(element, {
                attributes: true,
                attributeFilter: ['style', 'class', 'hidden', 'disabled'],
            });
        }
        window.addEventListener('resize', update);
        window.addEventListener('pagehide', cancelTimer);
        window.addEventListener('pageshow', update);
        update();
    });
})();

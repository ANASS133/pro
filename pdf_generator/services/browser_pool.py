"""
Persistent Headless Browser Pool for fast HTML-to-PDF rendering and deep crawling.
Eliminates the 3-5s overhead of spawning a new browser process on every document.
"""

import atexit
import base64
import io
import logging
import threading
import time
from contextlib import contextmanager
from typing import Optional, Tuple

from pypdf import PdfReader, PdfWriter
from scraper.browser_driver import find_browser, new_options, start_driver

logger = logging.getLogger(__name__)


class BrowserPool:
    """Thread-safe persistent headless browser manager."""

    def __init__(self, max_uses: int = 75):
        self._lock = threading.Lock()
        self._driver = None
        self._browser_name = None
        self._uses_count = 0
        self._max_uses = max_uses
        self._is_shutting_down = False
        atexit.register(self.shutdown)

    def _create_driver(self):
        """Spawns a new headless browser instance."""
        browser_name, binary = find_browser()
        options = new_options(browser_name)
        if binary:
            options.binary_location = binary
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-sync")
        options.add_argument("--blink-settings=imagesEnabled=true")

        logger.info(f"Launching persistent warm {browser_name} driver for PDF pool...")
        driver = start_driver(browser_name, options)
        driver.set_page_load_timeout(30)
        driver.set_script_timeout(30)
        self._driver = driver
        self._browser_name = browser_name
        self._uses_count = 0
        return driver

    def _is_healthy(self) -> bool:
        if self._driver is None:
            return False
        try:
            # Quick check if CDP connection is still responsive
            _ = self._driver.current_window_handle
            return True
        except Exception:
            return False

    @contextmanager
    def get_driver(self):
        """Context manager that leases the warm browser instance."""
        with self._lock:
            if self._is_shutting_down:
                raise RuntimeError("Browser pool is shutting down")

            if not self._is_healthy() or self._uses_count >= self._max_uses:
                self._recycle()

            if self._driver is None:
                self._create_driver()

            self._uses_count += 1
            try:
                yield self._driver
            except Exception as exc:
                logger.warning(f"Error during browser operation: {exc}; recycling driver.")
                self._recycle()
                raise

    def render_html_to_pdf(self, html_doc_str: str) -> bytes:
        """Renders HTML string directly to PDF bytes via warm browser CDP."""
        with self.get_driver() as driver:
            driver.execute_cdp_cmd("Emulation.setEmulatedMedia", {"media": "print"})
            encoded = base64.b64encode(html_doc_str.encode("utf-8")).decode("ascii")
            driver.get("data:text/html;charset=utf-8;base64," + encoded)

            driver.execute_async_script("""
                const done = arguments[arguments.length - 1];
                Promise.all([
                    document.fonts.ready,
                    ...Array.from(document.images, img =>
                        img.complete ? Promise.resolve() : new Promise(resolve => {
                            img.onload = resolve; img.onerror = resolve;
                        })
                    )
                ]).then(() => done());
            """)

            result = driver.execute_cdp_cmd("Page.printToPDF", {
                "printBackground": True,
                "preferCSSPageSize": True,
                "displayHeaderFooter": False,
                "paperWidth": 210 / 25.4,
                "paperHeight": 297 / 25.4,
                "marginTop": 0,
                "marginBottom": 0,
                "marginLeft": 0,
                "marginRight": 0,
            })

            pdf_data = base64.b64decode(result["data"])
            return pdf_data

    def _recycle(self):
        """Cleanly close and clear existing driver."""
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None
        self._uses_count = 0

    def shutdown(self):
        """Clean shutdown of pooled driver."""
        self._is_shutting_down = True
        with self._lock:
            self._recycle()


# Global singleton instance
browser_pool = BrowserPool()

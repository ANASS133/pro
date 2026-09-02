"""Shared Chrome/Edge discovery and Selenium driver creation."""

import os
from pathlib import Path
from typing import Tuple

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager


def _browser_candidates():
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    return {
        "chrome": [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            local_app_data / "Google" / "Chrome" / "Application" / "chrome.exe",
        ],
        "edge": [
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            local_app_data / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ],
    }


def find_browser() -> Tuple[str, str]:
    """Return an installed browser and its executable path."""
    preference = os.getenv("SELENIUM_BROWSER", "auto").strip().lower()
    if preference not in {"auto", "chrome", "edge"}:
        raise ValueError("SELENIUM_BROWSER must be auto, chrome, or edge")

    candidates = _browser_candidates()
    order = ["chrome", "edge"] if preference == "auto" else [preference]
    for browser_name in order:
        for path in candidates[browser_name]:
            if path.is_file():
                return browser_name, str(path)

    requested = "Chrome or Edge" if preference == "auto" else preference.title()
    raise FileNotFoundError(f"{requested} browser was not found on this computer")


def new_options(browser_name: str):
    if browser_name == "edge":
        return webdriver.EdgeOptions()
    return webdriver.ChromeOptions()


def start_driver(browser_name: str, options):
    if browser_name == "edge":
        return webdriver.Edge(
            service=EdgeService(EdgeChromiumDriverManager().install()),
            options=options,
        )
    return webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=options,
    )

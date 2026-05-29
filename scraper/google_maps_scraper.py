"""
Google Maps Business Scraper
=============================
Uses Selenium to search Google Maps for businesses, extract their details,
and crawl their websites to find email addresses.
"""

import logging
import os as _os_module
import re
import time
import random
import urllib.parse
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

EXCLUDED_EMAIL_DOMAINS = {
    "example.com", "example.org", "example.net",
    "wix.com", "squarespace.com", "wordpress.com",
    "sentry.io", "googleapis.com", "google.com",
    "googlemail.com", "gstatic.com", "w3.org",
    "schema.org", "facebook.com", "twitter.com", "instagram.com",
}

EXCLUDED_EMAIL_PREFIXES = {
    "noreply", "no-reply", "no_reply", "donotreply",
    "mailer-daemon", "postmaster", "hostmaster", "webmaster",
    "abuse", "root", "admin@example",
}

CONTACT_PAGE_PATTERNS = [
    "/kontakt", "/contact", "/impressum", "/imprint",
    "/ueber-uns", "/about", "/about-us", "/team", "/datenschutz",
]

MAPS_URL = "https://www.google.com/maps"

CRAWL_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
CRAWL_TIMEOUT = 15
MAX_CRAWL_PAGES = 6


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_email(value: Optional[str]) -> str:
    if not value:
        return ""
    return str(value).strip().strip(".,;:\"'<>()[]").lower()


def _is_valid_email(email: str) -> bool:
    normalized = _normalize_email(email)
    if not normalized or "@" not in normalized:
        return False
    domain = normalized.split("@", 1)[1]
    if domain in EXCLUDED_EMAIL_DOMAINS:
        return False
    local = normalized.split("@", 1)[0]
    for prefix in EXCLUDED_EMAIL_PREFIXES:
        if local == prefix or normalized.startswith(prefix + "@"):
            return False
    if len(normalized) > 254 or len(local) > 64:
        return False
    return True


def _random_delay(min_s: float = 1.5, max_s: float = 4.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


def _extract_emails_from_text(text: str) -> List[str]:
    if not text:
        return []
    raw_emails = EMAIL_PATTERN.findall(text)
    valid: List[str] = []
    seen: Set[str] = set()
    for email in raw_emails:
        normalized = _normalize_email(email)
        if normalized and normalized not in seen and _is_valid_email(normalized):
            seen.add(normalized)
            valid.append(normalized)
    return valid


def _extract_emails_from_html(html_content: str) -> List[str]:
    """Extract emails from both visible text and mailto: links."""
    if not html_content:
        return []

    emails: Set[str] = set()

    try:
        soup = BeautifulSoup(html_content, "html.parser")

        # Extract from mailto links
        for a_tag in soup.find_all("a", href=True):
            href = (a_tag.get("href") or "").strip()
            if href.startswith("mailto:"):
                addr = href.replace("mailto:", "", 1).split("?")[0].strip()
                normalized = _normalize_email(addr)
                if normalized and _is_valid_email(normalized):
                    emails.add(normalized)

        # Extract from visible text
        text = soup.get_text(separator="\n")
        for email in _extract_emails_from_text(text):
            emails.add(email)

    except Exception as exc:
        logger.debug("Error parsing HTML for emails: %s", exc)

    return sorted(emails)


def _discover_contact_pages(base_url: str, homepage_html: str) -> List[str]:
    """Find contact/impressum pages from homepage links."""
    if not homepage_html:
        return []

    pages: List[str] = []
    seen: Set[str] = set()

    try:
        soup = BeautifulSoup(homepage_html, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            href = (a_tag.get("href") or "").strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            full_url = urljoin(base_url, href)
            if full_url in seen:
                continue
            seen.add(full_url)
            href_lower = href.lower()
            for pattern in CONTACT_PAGE_PATTERNS:
                if pattern in href_lower:
                    pages.append(full_url)
                    break
    except Exception:
        pass

    return pages[:MAX_CRAWL_PAGES]


# ---------------------------------------------------------------------------
# Main Scraper Class
# ---------------------------------------------------------------------------

class GoogleMapsBusinessScraper:
    """Scrapes Google Maps for business listings and extracts emails from their websites."""

    def __init__(self, headless: bool = True):
        self.driver: Optional[webdriver.Chrome] = None
        self.http_session = requests.Session()
        self.http_session.headers.update({"User-Agent": CRAWL_USER_AGENT})
        self.headless = headless
        self.global_emails: Set[str] = set()
        self.stats = {
            "businesses_found": 0,
            "emails_found": 0,
            "no_email": 0,
            "failed": 0,
            "websites_crawled": 0,
        }

    @staticmethod
    def _find_chrome_binary() -> str:
        """Locate Chrome/Chromium browser binary."""
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            _os_module.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for path in candidates:
            if _os_module.path.exists(path):
                return path
        raise FileNotFoundError(
            "Chrome/Chromium browser not found. Install Chrome from https://www.google.com/chrome/"
        )

    def _ensure_driver(self) -> webdriver.Chrome:
        if self.driver is not None:
            return self.driver

        options = webdriver.ChromeOptions()
        options.binary_location = self._find_chrome_binary()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options,
        )
        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = {runtime: {}};
                """
            },
        )
        return self.driver

    def _accept_cookies(self) -> None:
        """Dismiss the Google consent dialog if present."""
        driver = self._ensure_driver()
        consent_selectors = [
            "//button[contains(., 'Alle akzeptieren')]",
            "//button[contains(., 'Accept all')]",
            "//button[contains(., 'Akzeptieren')]",
            "//button[contains(., 'Zustimmen')]",
            "//button[@aria-label='Alle akzeptieren']",
            "//button[@aria-label='Accept all']",
        ]
        for selector in consent_selectors:
            try:
                buttons = driver.find_elements(By.XPATH, selector)
                for btn in buttons:
                    text = (btn.text or "").strip().lower()
                    if any(kw in text for kw in ["akzeptieren", "accept", "zustimmen", "alle"]):
                        btn.click()
                        time.sleep(1.5)
                        return
            except (StaleElementReferenceException, WebDriverException):
                continue

    def search_businesses(
        self,
        query: str,
        max_results: int = 50,
        *,
        stop_check=None,
    ) -> List[Dict]:
        """Search Google Maps for businesses using URL-based navigation."""
        driver = self._ensure_driver()
        businesses: List[Dict] = []
        seen_names: Set[str] = set()

        logger.info("Google Maps search: %r (max %d)", query, max_results)

        encoded_query = urllib.parse.quote(query, safe="")
        search_url = f"https://www.google.com/maps/search/{encoded_query}"
        logger.info("Navigating to: %s", search_url)

        try:
            driver.get(search_url)
            time.sleep(5)
            self._accept_cookies()
            time.sleep(2)

            # Find results container
            container_selectors = [
                "div[role='feed']",
                "div.m6QErb",
                "div[aria-label*='Ergebnisse']",
                "div[aria-label*='Results']",
            ]
            feed = None
            for sel in container_selectors:
                try:
                    feed = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                    )
                    logger.info("Found feed with: %s", sel)
                    break
                except (TimeoutException, NoSuchElementException):
                    continue

            if not feed:
                logger.warning("No feed container found")

            max_scrolls = (max_results // 3) + 30
            scroll_count = 0
            prev_count = 0
            stale_rounds = 0

            while len(businesses) < max_results and scroll_count < max_scrolls:
                if stop_check and stop_check():
                    break

                # Extract all place links currently visible
                links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/maps/place/']")
                for link in links:
                    if len(businesses) >= max_results:
                        break
                    try:
                        biz = self._extract_business_from_link(link)
                        if biz and biz["name"] and biz["name"] not in seen_names:
                            seen_names.add(biz["name"])
                            businesses.append(biz)
                    except (StaleElementReferenceException, WebDriverException):
                        continue

                logger.info("Scroll %d: %d businesses found", scroll_count + 1, len(businesses))

                if len(businesses) == prev_count:
                    stale_rounds += 1
                    if stale_rounds >= 5:
                        logger.info("No new results after %d scrolls, stopping", stale_rounds)
                        break
                else:
                    stale_rounds = 0
                    prev_count = len(businesses)

                if len(businesses) >= max_results:
                    break

                # Scroll down
                try:
                    if feed:
                        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", feed)
                    else:
                        driver.execute_script("window.scrollBy(0, 800);")
                except WebDriverException:
                    pass

                scroll_count += 1
                _random_delay(2.0, 4.0)

        except Exception as exc:
            logger.error("Error during search: %s", exc)

        self.stats["businesses_found"] = len(businesses)
        logger.info("Search done: %d businesses", len(businesses))
        return businesses[:max_results]

    def _extract_business_from_link(self, link_element) -> Optional[Dict]:
        """Extract business info from a Google Maps place link element."""
        try:
            href = (link_element.get_attribute("href") or "").strip()
            aria_label = (link_element.get_attribute("aria-label") or "").strip()

            # Get name from aria-label or text content
            name = ""
            if aria_label:
                name = aria_label
            else:
                name = (link_element.text or "").strip()

            if not name:
                return None

            # Clean up name (remove rating info often appended)
            name = re.sub(r"\s*\d+[.,]\d+\s*\(\d+\)\s*$", "", name).strip()
            name = re.sub(r"\s*Sterne.*$", "", name, flags=re.IGNORECASE).strip()

            if not name or len(name) < 2:
                return None

            # Try to get additional info from parent elements
            address = ""
            category = ""
            rating = ""
            reviews_count = ""

            try:
                # Walk up to find the card container
                card = link_element
                for _ in range(5):
                    if not card:
                        break
                    text = (card.text or "").strip()
                    # Extract rating
                    rating_match = re.search(r"(\d+[.,]\d+)\s*\((\d+)\)", text)
                    if rating_match:
                        rating = rating_match.group(1)
                        reviews_count = rating_match.group(2)
                    card = card.find_element(By.XPATH, "..") if card else None
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            return {
                "name": name,
                "address": address,
                "phone": "",
                "website": "",
                "emails": [],
                "rating": rating,
                "reviews_count": reviews_count,
                "category": category,
                "maps_url": href,
                "status": "pending",
            }

        except (StaleElementReferenceException, WebDriverException):
            return None

    def enrich_business_details(self, business: Dict) -> Dict:
        """Open the business detail page to get phone and website."""
        driver = self._ensure_driver()
        maps_url = business.get("maps_url", "")

        if not maps_url:
            return business

        try:
            driver.get(maps_url)
            time.sleep(3)

            # Extract phone — try multiple selectors
            phone_selectors = [
                "button[data-tooltip*='Phone']",
                "button[aria-label*='Phone']",
                "button[aria-label*='Telefon']",
                "button[data-item-id*='phone']",
                "a[data-tooltip*='Phone']",
                "a[aria-label*='Phone']",
                "a[href^='tel:']",
            ]
            for sel in phone_selectors:
                try:
                    el = driver.find_element(By.CSS_SELECTOR, sel)
                    phone_text = (el.text or el.get_attribute("aria-label") or el.get_attribute("href") or "").strip()
                    if phone_text:
                        phone_text = phone_text.replace("tel:", "").strip()
                        if re.search(r"\d", phone_text):
                            business["phone"] = phone_text
                            break
                except (NoSuchElementException, WebDriverException):
                    continue

            # Extract website
            website_selectors = [
                "a[data-tooltip*='Website']",
                "a[aria-label*='Website']",
                "a[aria-label*='Webseite']",
                "a[data-item-id='authority']",
                "a[href][data-value]",
            ]
            for sel in website_selectors:
                try:
                    el = driver.find_element(By.CSS_SELECTOR, sel)
                    url = (el.get_attribute("href") or "").strip()
                    if url and "google" not in url and not url.startswith("tel:"):
                        if not url.startswith("http"):
                            url = "https://" + url
                        business["website"] = url
                        break
                except (NoSuchElementException, WebDriverException):
                    continue

            # Extract address if missing
            if not business.get("address"):
                try:
                    addr_els = driver.find_elements(By.CSS_SELECTOR, "button[data-item-id='address']")
                    for el in addr_els:
                        addr = (el.text or "").strip()
                        if addr:
                            business["address"] = addr
                            break
                except (NoSuchElementException, WebDriverException):
                    pass

        except Exception as exc:
            logger.debug("Error enriching %s: %s", business.get("name"), exc)

        return business

    def extract_emails_from_website(self, website_url: str) -> List[str]:
        """Crawl a business website to find contact email addresses."""
        if not website_url:
            return []

        all_emails: Set[str] = set()
        crawled_urls: Set[str] = set()

        base_url = website_url.rstrip("/")

        # 1. Fetch homepage
        homepage_html = self._fetch_page(base_url)
        if homepage_html:
            crawled_urls.add(base_url)
            emails = _extract_emails_from_html(homepage_html)
            all_emails.update(emails)
            contact_pages = _discover_contact_pages(base_url, homepage_html)
        else:
            contact_pages = [
                urljoin(base_url, path) for path in CONTACT_PAGE_PATTERNS
            ]

        # 2. Crawl contact pages
        for page_url in contact_pages:
            if page_url in crawled_urls:
                continue
            if len(crawled_urls) >= MAX_CRAWL_PAGES:
                break

            page_html = self._fetch_page(page_url)
            if page_html:
                crawled_urls.add(page_url)
                emails = _extract_emails_from_html(page_html)
                all_emails.update(emails)

            _random_delay(0.5, 1.5)

        self.stats["websites_crawled"] += 1
        return list(all_emails)

    def _fetch_page(self, url: str) -> Optional[str]:
        """Fetch a web page using requests."""
        try:
            response = self.http_session.get(url, timeout=CRAWL_TIMEOUT, allow_redirects=True)
            if response.status_code == 200:
                return response.text
        except Exception as exc:
            logger.debug("Failed to fetch %s: %s", url, exc)
        return None

    def process_business(
        self,
        business: Dict,
        *,
        stop_check=None,
    ) -> Dict:
        """Full processing: enrich details + extract emails."""
        name = business.get("name", "Unknown")

        try:
            if stop_check and stop_check():
                business["status"] = "stopped"
                return business

            self.enrich_business_details(business)
            _random_delay(1.0, 2.0)

            website = business.get("website", "")
            if website:
                emails = self.extract_emails_from_website(website)
                new_emails = []
                for email in emails:
                    normalized = _normalize_email(email)
                    if normalized not in self.global_emails:
                        self.global_emails.add(normalized)
                    new_emails.append(normalized)

                business["emails"] = new_emails

                if new_emails:
                    business["status"] = "success"
                    self.stats["emails_found"] += 1
                    logger.info("Found %d email(s) for %s", len(new_emails), name)
                else:
                    business["status"] = "no_email"
                    self.stats["no_email"] += 1
                    logger.info("No emails for %s", name)
            else:
                business["emails"] = []
                business["status"] = "no_website"
                self.stats["no_email"] += 1
                logger.info("No website for %s", name)

        except Exception as exc:
            logger.error("Error processing %s: %s", name, exc)
            business["status"] = "error"
            business["error"] = str(exc)
            self.stats["failed"] += 1

        return business

    def close(self) -> None:
        """Clean up resources."""
        try:
            if self.driver:
                self.driver.quit()
                self.driver = None
        except Exception:
            pass
        try:
            self.http_session.close()
        except Exception:
            pass

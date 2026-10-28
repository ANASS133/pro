"""
Universal Cookie Banner & Consent Handler for JobScout Web Scraping & Automation.
================================================================================
Automatically dismisses cookie consent dialogues across:
- Job Portals: Arbeitsagentur ("Alle Cookies akzeptieren"), Ausbildung.de, Azubiyo, AUBI-plus, IHK
- Search Engines: Google ("Alle akzeptieren", "Accept all")
- CMP Systems: Usercentrics (including Shadow DOM), OneTrust, Cookiebot, Complianz, Borlabs, Didomi, Klaro
- Arbitrary company & employer websites (German, English, French)
"""

import logging
import time
from typing import Optional
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)

logger = logging.getLogger(__name__)

# Common high-priority XPath selectors for German/English/French cookie acceptance
CONSENT_XPATHS = [
    # 1. Exact German cookie acceptance (Arbeitsagentur, Ausbildung.de, etc.)
    "//button[contains(normalize-space(.), 'Alle Cookies akzeptieren')]",
    "//button[contains(normalize-space(.), 'Cookies akzeptieren')]",
    "//button[contains(normalize-space(.), 'Alle akzeptieren')]",
    "//button[contains(normalize-space(.), 'Alles akzeptieren')]",
    "//button[contains(normalize-space(.), 'Auswahl bestätigen und weiter')]",
    "//button[contains(normalize-space(.), 'Zustimmen und weiter')]",
    "//button[contains(normalize-space(.), 'Zustimmen')]",
    "//button[contains(normalize-space(.), 'Einverstanden')]",
    "//button[contains(normalize-space(.), 'Ich stimme zu')]",
    "//button[contains(normalize-space(.), 'Verstanden')]",
    "//a[contains(normalize-space(.), 'Alle Cookies akzeptieren')]",
    "//a[contains(normalize-space(.), 'Cookies akzeptieren')]",
    "//a[contains(normalize-space(.), 'Alle akzeptieren')]",
    "//a[contains(normalize-space(.), 'Zustimmen')]",

    # 2. English consent buttons
    "//button[contains(normalize-space(.), 'Accept all cookies')]",
    "//button[contains(normalize-space(.), 'Accept All Cookies')]",
    "//button[contains(normalize-space(.), 'Accept all')]",
    "//button[contains(normalize-space(.), 'Accept All')]",
    "//button[contains(normalize-space(.), 'Accept cookies')]",
    "//button[contains(normalize-space(.), 'I accept')]",
    "//button[contains(normalize-space(.), 'Agree and continue')]",

    # 3. French consent buttons
    "//button[contains(normalize-space(.), 'Tout accepter')]",
    "//button[contains(normalize-space(.), 'Accepter tout')]",
    "//button[contains(normalize-space(.), 'J\'accepte')]",

    # 4. Standard Consent Management Platform (CMP) IDs & Classes
    "//button[@id='onetrust-accept-btn-handler']",
    "//button[@id='CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll']",
    "//button[@id='CybotCookiebotDialogBodyButtonAccept']",
    "//button[@id='uc-btn-accept-all']",
    "//button[@data-testid='uc-accept-all-button']",
    "//button[@id='didomi-notice-agree-button']",
    "//button[contains(@class, 'cmplz-accept')]",
    "//button[contains(@class, 'cookie-box-btn-accept-all')]",
    "//button[@aria-label='Alle Cookies akzeptieren']",
    "//button[@aria-label='Alle akzeptieren']",
    "//button[@aria-label='Accept all']",
]

JS_CONSENT_CLICKER = """
function clickConsent() {
    const ACCEPT_KEYWORDS = [
        'alle cookies akzeptieren',
        'cookies akzeptieren',
        'alle akzeptieren',
        'alles akzeptieren',
        'zustimmen und weiter',
        'zustimmen',
        'einverstanden',
        'verstanden',
        'ich stimme zu',
        'accept all cookies',
        'accept all',
        'accept cookies',
        'i accept',
        'tout accepter',
        'accepter tout',
        'j\\'accepte'
    ];

    const CMP_SELECTORS = [
        '#onetrust-accept-btn-handler',
        '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
        '#CybotCookiebotDialogBodyButtonAccept',
        '#uc-btn-accept-all',
        'button[data-testid="uc-accept-all-button"]',
        '#didomi-notice-agree-button',
        '.cmplz-accept',
        '.cookie-box-btn-accept-all',
        'button[data-action="accept-all"]',
        'button[data-cookiefirst-action="accept"]',
        'button[id*="cookie" i][id*="accept" i]',
        'button[class*="cookie" i][class*="accept" i]',
        'button[class*="consent" i][class*="accept" i]'
    ];

    // 1. Try known CMP selectors
    for (const sel of CMP_SELECTORS) {
        try {
            const el = document.querySelector(sel);
            if (el && (el.offsetParent !== null || el.offsetWidth > 0 || el.offsetHeight > 0)) {
                el.click();
                return { success: true, method: 'cmp_selector', detail: sel };
            }
        } catch (e) {}
    }

    // 2. Search Shadow DOM roots (e.g. Usercentrics v2)
    const shadowHosts = document.querySelectorAll('#usercentrics-root, #cmp-root, [id*="consent" i]');
    for (const host of shadowHosts) {
        if (host && host.shadowRoot) {
            try {
                const btn = host.shadowRoot.querySelector('button[data-testid="uc-accept-all-button"], button[data-testid*="accept"], button');
                if (btn) {
                    const txt = (btn.innerText || btn.textContent || '').trim().toLowerCase();
                    if (ACCEPT_KEYWORDS.some(kw => txt.includes(kw))) {
                        btn.click();
                        return { success: true, method: 'shadow_root', detail: txt };
                    }
                }
            } catch (e) {}
        }
    }

    // 3. Scan all candidate clickable elements
    const candidates = document.querySelectorAll('button, a[role="button"], input[type="button"], input[type="submit"], div[role="button"]');
    for (const el of candidates) {
        if (!el || (el.offsetParent === null && el.offsetWidth === 0 && el.offsetHeight === 0)) continue;
        const text = (el.innerText || el.textContent || el.value || '').trim().toLowerCase();
        if (!text) continue;

        // Skip rejection buttons
        if (text.includes('ablehnen') || text.includes('reject') || text.includes('decline') || text.includes('nicht zustimmen')) {
            continue;
        }

        for (const kw of ACCEPT_KEYWORDS) {
            if (text === kw || text.includes(kw)) {
                el.click();
                return { success: true, method: 'text_match', detail: text };
            }
        }
    }

    return { success: false };
}
return clickConsent();
"""


def accept_cookies(driver, wait_after_click: float = 0.5) -> bool:
    """
    Universally detects and clicks 'Cookies akzeptieren' or 'Alle akzeptieren'
    on the currently active page in Selenium.

    Returns True if a cookie consent dialog was found and clicked, False otherwise.
    Never throws an exception.
    """
    if driver is None:
        return False

    try:
        # Strategy 1: Fast JavaScript DOM & Shadow-DOM walker
        try:
            res = driver.execute_script(JS_CONSENT_CLICKER)
            if isinstance(res, dict) and res.get("success"):
                logger.info(
                    "Cookie banner accepted via JS [%s: %s]",
                    res.get("method"),
                    res.get("detail"),
                )
                if wait_after_click > 0:
                    time.sleep(wait_after_click)
                return True
        except Exception as js_err:
            logger.debug("JS cookie clicker error: %s", js_err)

        # Strategy 2: Direct WebDriver XPath Selectors
        for xpath in CONSENT_XPATHS:
            try:
                elements = driver.find_elements(By.XPATH, xpath)
                for el in elements:
                    if el.is_displayed():
                        text = (el.text or "").strip()
                        # Avoid clicking rejection buttons
                        text_lower = text.lower()
                        if any(neg in text_lower for neg in ["ablehnen", "reject", "decline"]):
                            continue

                        try:
                            el.click()
                        except ElementClickInterceptedException:
                            driver.execute_script("arguments[0].click();", el)

                        logger.info("Cookie banner accepted via XPath: '%s'", text)
                        if wait_after_click > 0:
                            time.sleep(wait_after_click)
                        return True
            except (NoSuchElementException, StaleElementReferenceException, WebDriverException):
                continue

        # Strategy 3: Check iFrames for embedded consent dialogues
        try:
            iframes = driver.find_elements(By.XPATH, "//iframe[contains(@id, 'consent') or contains(@id, 'cmp') or contains(@src, 'consent') or contains(@title, 'consent') or contains(@title, 'Cookie')]")
            for frame in iframes[:2]:
                try:
                    driver.switch_to.frame(frame)
                    res = driver.execute_script(JS_CONSENT_CLICKER)
                    driver.switch_to.default_content()
                    if isinstance(res, dict) and res.get("success"):
                        logger.info("Cookie banner accepted inside iframe [%s]", res.get("method"))
                        if wait_after_click > 0:
                            time.sleep(wait_after_click)
                        return True
                except Exception:
                    driver.switch_to.default_content()
        except Exception:
            driver.switch_to.default_content()

    except Exception as exc:
        logger.debug("accept_cookies encountered non-fatal error: %s", exc)

    return False

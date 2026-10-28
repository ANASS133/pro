"""
Unit tests for JobScout universal cookie acceptance handler.
Verifies:
- Detection and clicking of "Alle Cookies akzeptieren", "Cookies akzeptieren", etc.
- Safe handling of None driver and driver exceptions.
- Exclusion of rejection buttons ("Alle Cookies ablehnen").
- Integration with WorkingEmailExtractor.
"""

import unittest
from unittest.mock import MagicMock
from scraper.cookie_handler import accept_cookies
from scraper.working_email_extractor import WorkingEmailExtractor


class TestCookieHandler(unittest.TestCase):
    def test_none_driver(self):
        # Should gracefully return False without raising an error
        self.assertFalse(accept_cookies(None))

    def test_js_click_success(self):
        mock_driver = MagicMock()
        mock_driver.execute_script.return_value = {
            "success": True,
            "method": "text_match",
            "detail": "alle cookies akzeptieren",
        }

        result = accept_cookies(mock_driver, wait_after_click=0)
        self.assertTrue(result)
        mock_driver.execute_script.assert_called_once()

    def test_xpath_fallback_click(self):
        mock_driver = MagicMock()
        # JS returns failure
        mock_driver.execute_script.return_value = {"success": False}

        mock_button = MagicMock()
        mock_button.is_displayed.return_value = True
        mock_button.text = "Alle Cookies akzeptieren"

        def find_elements_side_effect(by, xpath):
            if "Alle Cookies akzeptieren" in xpath:
                return [mock_button]
            return []

        mock_driver.find_elements.side_effect = find_elements_side_effect

        result = accept_cookies(mock_driver, wait_after_click=0)
        self.assertTrue(result)
        mock_button.click.assert_called_once()

    def test_reject_button_ignored(self):
        mock_driver = MagicMock()
        mock_driver.execute_script.return_value = {"success": False}

        mock_reject_btn = MagicMock()
        mock_reject_btn.is_displayed.return_value = True
        mock_reject_btn.text = "Alle Cookies ablehnen"

        mock_driver.find_elements.return_value = [mock_reject_btn]

        result = accept_cookies(mock_driver, wait_after_click=0)
        # Reject button must NOT be clicked
        self.assertFalse(mock_reject_btn.click.called)

    def test_working_email_extractor_accept_cookies_hook(self):
        # Verify WorkingEmailExtractor has accept_cookies method and calls handler
        extractor = MagicMock(spec=WorkingEmailExtractor)
        extractor.driver = MagicMock()
        extractor.driver.execute_script.return_value = {"success": True}

        # Call the actual accept_cookies implementation on the mock
        res = WorkingEmailExtractor.accept_cookies(extractor)
        self.assertTrue(res)


if __name__ == "__main__":
    unittest.main()

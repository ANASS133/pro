import base64
import io
import unittest
from unittest.mock import MagicMock, patch

from PIL import Image, ImageDraw
from services.manual_captcha_service import capture_loaded_captcha
from scraper.working_email_extractor import WorkingEmailExtractor


def fixture(blank=False):
    image = Image.new('RGB', (120, 40), 'white')
    if not blank:
        ImageDraw.Draw(image).text((5, 5), 'fixture', fill='black')
    output = io.BytesIO()
    image.save(output, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()


class CaptchaBrowserImageTests(unittest.TestCase):
    def test_worker_browser_allows_real_images(self):
        extractor = WorkingEmailExtractor.__new__(WorkingEmailExtractor)
        extractor.network_profile = None
        options = MagicMock()
        with patch('scraper.working_email_extractor.find_browser', return_value=('chrome', 'chrome')), patch('scraper.working_email_extractor.new_options', return_value=options), patch('scraper.working_email_extractor.start_driver'):
            extractor.setup_driver(True)
        args = [call.args[0] for call in options.add_argument.call_args_list]
        self.assertNotIn('--blink-settings=imagesEnabled=false', args)
        prefs = options.add_experimental_option.call_args.args[1]
        self.assertEqual(prefs['profile.managed_default_content_settings.images'], 1)

    def test_valid_element_capture_cannot_be_overwritten_by_blank_canvas(self):
        driver, element = MagicMock(), MagicMock()
        driver.execute_script.return_value = True
        element.screenshot_as_base64 = fixture().split(',', 1)[1]
        result, error = capture_loaded_captcha(driver, element)
        self.assertEqual(result, fixture())
        self.assertEqual(error, '')
        self.assertEqual(driver.execute_script.call_count, 1)
        driver.get_screenshot_as_base64.assert_not_called()

    def test_blank_element_capture_tries_valid_fallback(self):
        driver, element = MagicMock(), MagicMock()
        element.screenshot_as_base64 = fixture(True).split(',', 1)[1]
        driver.execute_script.side_effect = [True, fixture()]
        self.assertEqual(capture_loaded_captcha(driver, element), (fixture(), ''))

    def test_unloaded_image_never_becomes_a_placeholder_screenshot(self):
        driver, element = MagicMock(), MagicMock()
        driver.execute_script.return_value = False
        image, error = capture_loaded_captcha(driver, element, timeout=0)
        self.assertEqual(image, '')
        self.assertIn('did not load', error)
        element.get_attribute.assert_not_called()

    def test_workers_capture_their_own_images(self):
        first, second = MagicMock(), MagicMock()
        first.execute_script.return_value = second.execute_script.return_value = True
        good, blank = MagicMock(), MagicMock()
        good.screenshot_as_base64 = fixture().split(',', 1)[1]
        blank.screenshot_as_base64 = fixture(True).split(',', 1)[1]
        blank.get_attribute.return_value = ''
        self.assertTrue(capture_loaded_captcha(first, good)[0])
        self.assertFalse(capture_loaded_captcha(second, blank)[0])


if __name__ == '__main__':
    unittest.main()

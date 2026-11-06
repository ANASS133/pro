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
        extractor.worker_id = 1
        extractor.network_profile = None
        options = MagicMock()
        with patch('scraper.working_email_extractor.find_browser', return_value=('chrome', 'chrome')), patch('scraper.working_email_extractor.new_options', return_value=options), patch('scraper.working_email_extractor.start_driver'):
            extractor.setup_driver(True)
        args = [call.args[0] for call in options.add_argument.call_args_list]
        self.assertNotIn('--blink-settings=imagesEnabled=false', args)
        self.assertIn('--window-size=1920,1080', args)
        prefs = options.add_experimental_option.call_args.args[1]
        self.assertEqual(prefs['profile.managed_default_content_settings.images'], 1)

    def test_capture_scrolls_and_stabilizes_layout_before_element_screenshot(self):
        events = []

        class RecordingElement:
            def get_attribute(self, _name):
                return ''

            @property
            def screenshot_as_base64(self):
                events.append('screenshot')
                return fixture().split(',', 1)[1]

        driver = MagicMock()

        def execute(script, *_args):
            if 'scrollIntoView' in script:
                events.append('scroll')
                return None
            if 'getBoundingClientRect' in script or 'requestAnimationFrame' in script:
                events.append('stabilize')
                return True
            return True

        driver.execute_script.side_effect = execute
        image, error = capture_loaded_captcha(driver, RecordingElement())

        self.assertTrue(image)
        self.assertEqual(error, '')
        self.assertIn('scroll', events)
        self.assertIn('stabilize', events)
        self.assertLess(events.index('scroll'), events.index('screenshot'))
        self.assertLess(events.index('stabilize'), events.index('screenshot'))

    def test_capture_does_not_export_image_through_canvas(self):
        driver, element = MagicMock(), MagicMock()
        element.get_attribute.return_value = ''
        element.screenshot_as_base64 = fixture(True).split(',', 1)[1]
        driver.execute_script.side_effect = lambda script, *_args: fixture() if 'canvas' in script else True

        capture_loaded_captcha(driver, element)

        scripts = [call.args[0] for call in driver.execute_script.call_args_list]
        self.assertFalse(any('canvas' in script for script in scripts))

    def test_valid_element_capture_cannot_be_overwritten_by_blank_canvas(self):
        driver, element = MagicMock(), MagicMock()
        driver.execute_script.return_value = True
        element.screenshot_as_base64 = fixture().split(',', 1)[1]
        result, error = capture_loaded_captcha(driver, element)
        self.assertEqual(result, fixture())
        self.assertEqual(error, '')
        scripts = [call.args[0] for call in driver.execute_script.call_args_list]
        self.assertFalse(any('canvas' in script for script in scripts))
        driver.get_screenshot_as_base64.assert_not_called()

    def test_blank_base64_capture_tries_element_png_fallback(self):
        driver, element = MagicMock(), MagicMock()
        element.screenshot_as_base64 = fixture(True).split(',', 1)[1]
        element.screenshot_as_png = base64.b64decode(fixture().split(',', 1)[1])
        driver.execute_script.return_value = True
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

    def test_refresh_waits_for_captcha_src_to_change_without_fixed_sleep(self):
        from services.manual_captcha_service import ManualCaptchaChallenge

        reload_button = MagicMock()
        image = MagicMock()
        image.size = {'width': 120, 'height': 40}
        image.get_attribute.side_effect = ['old-src', 'old-src', 'new-src']
        driver = MagicMock()
        driver.find_elements.side_effect = lambda by, selector: (
            [reload_button] if selector == '#kontaktdaten-captcha-reload-button' else [image]
        )
        challenge = ManualCaptchaChallenge(
            challenge_id='mch_src_wait', job_id='job', search_run_id='run', job_index=0,
            worker_id=1, platform='ihk.de', job_title='Role', employer='Employer',
            source_url='https://example.test', challenge_type='image_text',
            captcha_image_base64=fixture(), driver_ref=driver,
        )

        with patch('services.manual_captcha_service.capture_loaded_captcha', return_value=(fixture(), '')) as capture, \
             patch('services.manual_captcha_service.time.sleep') as sleep:
            result = challenge.refresh_image()

        self.assertEqual(result, fixture())
        reload_button.click.assert_called_once()
        self.assertGreaterEqual(image.get_attribute.call_count, 3)
        self.assertNotIn(0.4, [call.args[0] for call in sleep.call_args_list])
        capture.assert_called_once_with(driver, image)


if __name__ == '__main__':
    unittest.main()

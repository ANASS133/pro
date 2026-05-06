import unittest

from scraper.true_captcha_solver import TrueCaptchaSolver


class TrueCaptchaSolverTests(unittest.TestCase):
    def test_solver_returns_none_without_credentials(self):
        solver = TrueCaptchaSolver(userid="", apikey="")

        self.assertIsNone(solver.solve_captcha(b"fake-image"))

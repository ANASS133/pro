"""
Comprehensive Regression Test Suite for Cross-Employer Contact Contamination
Across All 5 JobScout Platforms (Arbeitsagentur, Ausbildung.de, IHK, Azubiyo, AUBI-plus).
"""

import concurrent.futures
import unittest
from unittest.mock import MagicMock, patch

import bs4

import app as app_module
from scraper.application_form_discovery import normalize_job_opportunity_row
from scraper.arbeitsagentur_extractor import ArbeitsagenturDetailExtractor
from scraper.ausbildung_de_detail_extractor import AusbildungDeDetailExtractor
from scraper.azubiyo_scraper import AzubiyoScraper
from scraper.working_email_extractor import WorkingEmailExtractor
from services.contamination_detector import (
    attach_contact_provenance,
    classify_extraction_outcome,
    detect_and_clean_cross_employer_contamination,
    is_email_compatible_with_employer,
    is_url_compatible_with_job,
)
from services.employer_cache import (
    EmployerDomainCache,
    JobResultCache,
    PlatformConfigCache,
    get_employer_cache,
    is_portal_domain,
    is_shortener_domain,
)


class TestCrossPlatformContamination(unittest.TestCase):
    def setUp(self):
        get_employer_cache().clear()

    def tearDown(self):
        get_employer_cache().clear()

    # =========================================================================
    # 1. THREE-TIER CACHE ARCHITECTURE TESTS
    # =========================================================================

    def test_three_tier_cache_isolation_and_portal_rejection(self):
        """Verify JobResultCache, EmployerDomainCache, and PlatformConfigCache separation."""
        cache = EmployerDomainCache()

        # Portal & shortener domains must NEVER be accepted as employer domain keys
        for bad_domain in (
            "https://www.ausbildung.de/stellen/123",
            "https://www.azubiyo.de/stellenanzeigen/abc",
            "https://www.aubi-plus.de/stellenangebot/xyz",
            "https://jobs.meine-ausbildung-in-deutschland.de/klick_zaehler.cfm?anzeige=1",
            "https://ihk-azubi-stellenmarkt.indexinternet.de/something",
            "https://short.sg/a/66030513",
            "https://jobs.hogapage.de",
        ):
            self.assertEqual(cache.normalize_domain(bad_domain), "", f"Domain should be rejected: {bad_domain}")

        # PlatformConfigCache must forbid contact fields
        plat_cache = PlatformConfigCache()
        with self.assertRaises(ValueError):
            plat_cache.put("ausbildung.de", {"email": "claudia.guenther@nordwasser.de"})

        # JobResultCache must isolate by canonical job URL and verify company compatibility
        job_cache = JobResultCache()
        job_cache.put(
            "https://www.ausbildung.de/stellen/nordwasser-1",
            {"email": "claudia.guenther@nordwasser.de"},
            company="Nordwasser GmbH",
        )
        self.assertIsNotNone(
            job_cache.get("https://www.ausbildung.de/stellen/nordwasser-1", company="Nordwasser GmbH")
        )
        self.assertIsNone(
            job_cache.get("https://www.ausbildung.de/stellen/codan-2", company="CODAN Medizinische Geräte GmbH")
        )
        # Mismatched company on same URL must also be rejected
        self.assertIsNone(
            job_cache.get("https://www.ausbildung.de/stellen/nordwasser-1", company="CODAN Medizinische Geräte GmbH")
        )

    # =========================================================================
    # 2. AUSBILDUNG.DE REGRESSION TESTS
    # =========================================================================

    def test_ausbildung_de_codan_vs_nordwasser_and_form_fallback(self):
        """
        Ausbildung.de:
        - Nordwasser extracts claudia.guenther@nordwasser.de
        - CODAN extracts personal@codan.de (never Nordwasser's email)
        - Unrelated employer without email extracts Jetzt bewerben form URL
        - Job without email or form is marked manual_review_required
        """
        ext = AusbildungDeDetailExtractor()

        # 1. Nordwasser
        nord_job = {
            "title": "Ausbildung Kaufmann für Büromanagement (m/w/d)",
            "company": "Nordwasser GmbH",
            "city": "Rostock",
            "url": "https://www.ausbildung.de/stellen/nordwasser-kaufmann-1/",
            "source": "ausbildung.de",
        }
        nord_html = r'<html><body><script>self.__next_f.push([1,"\"applicationOptions\":{\"email\":\"claudia.guenther@nordwasser.de\",\"url\":null}"])</script></body></html>'

        # 2. CODAN
        codan_job = {
            "title": "Ausbildung zum Fachinformatiker Anwendungsentwicklung (m/w/d) 2027",
            "company": "CODAN Medizinische Geräte GmbH",
            "city": "Lensahn",
            "url": "https://www.ausbildung.de/stellen/codan-fachinformatiker-2/",
            "source": "ausbildung.de",
        }
        codan_html = r'<html><body><script>self.__next_f.push([1,"\"applicationOptions\":{\"email\":\"personal@codan.de\",\"url\":\"https://www.codancompanies.com/karriere\"}"])</script></body></html>'

        # 3. Form-only job
        form_job = {
            "title": "Ausbildung Fachinformatiker Systemintegration (m/w/d)",
            "company": "DATEV eG",
            "city": "Nürnberg",
            "url": "https://www.ausbildung.de/stellen/datev-fisi-3/",
            "source": "ausbildung.de",
        }
        form_html = r'<html><body><script>self.__next_f.push([1,"\"applicationOptions\":{\"email\":null,\"url\":\"https://karriere.datev.de/apply/fisi-2027\"}"])</script></body></html>'

        # 4. No email and no form
        empty_job = {
            "title": "Ausbildung Koch (m/w/d)",
            "company": "Landgasthof Krone",
            "city": "bayern",
            "url": "https://www.ausbildung.de/stellen/krone-koch-4/",
            "source": "ausbildung.de",
        }
        empty_html = "<html><body><h1>Ausbildung Koch</h1><p>Bewerbung vor Ort.</p></body></html>"

        def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.url = url
            if "nordwasser" in url:
                resp.text = nord_html
            elif "codan" in url:
                resp.text = codan_html
            elif "datev" in url:
                resp.text = form_html
            else:
                resp.text = empty_html
            return resp

        mock_sess = MagicMock()
        mock_sess.get.side_effect = mock_get

        r_nord = ext.extract_vacancy(nord_job, driver=None, session=mock_sess)
        r_codan = ext.extract_vacancy(codan_job, driver=None, session=mock_sess)
        r_form = ext.extract_vacancy(form_job, driver=None, session=mock_sess)
        r_empty = ext.extract_vacancy(empty_job, driver=None, session=mock_sess)

        self.assertEqual(r_nord["email"], "claudia.guenther@nordwasser.de")
        self.assertEqual(r_codan["email"], "personal@codan.de")
        self.assertNotEqual(r_codan["email"], "claudia.guenther@nordwasser.de")

        self.assertEqual(r_form["email"], "")
        self.assertTrue(r_form["has_form"])
        self.assertEqual(r_form["form_link"], "https://karriere.datev.de/apply/fisi-2027")

        self.assertEqual(r_empty["email"], "")
        self.assertFalse(r_empty["has_form"])
        self.assertTrue(r_empty["manual_review_required"])

    # =========================================================================
    # 3. IHK REGRESSION TESTS
    # =========================================================================

    def test_ihk_redirects_isolate_per_job_and_never_share_soliver_or_dentsply(self):
        """
        IHK:
        - Multiple unrelated IHK jobs using klick_zaehler.cfm redirects must NOT share
          s.Oliver or Dentsply Sirona application URLs.
        - Each job resolves its own redirect destination independently.
        """
        with patch.object(WorkingEmailExtractor, "setup_driver"):
            worker = WorkingEmailExtractor("u", "k", headless=True)

            ihk_jobs = [
                {
                    "title": "Fachinformatiker (m/w/d)",
                    "company": "s.Oliver Bernd Freier GmbH & Co. KG",
                    "city": "Rottendorf",
                    "url": "https://jobs.meine-ausbildung-in-deutschland.de/klick_zaehler.cfm?anzeige=101&mid=43",
                    "source": "IHK Lehrstellenbörse",
                },
                {
                    "title": "Fachinformatiker (m/w/d)",
                    "company": "Giesecke+Devrient GmbH",
                    "city": "München",
                    "url": "https://jobs.meine-ausbildung-in-deutschland.de/klick_zaehler.cfm?anzeige=102&mid=43",
                    "source": "IHK Lehrstellenbörse",
                },
                {
                    "title": "Koch / Köchin (m/w/d)",
                    "company": "Dentsply Sirona Deutschland GmbH",
                    "city": "Bensheim",
                    "url": "https://jobs.meine-ausbildung-in-deutschland.de/klick_zaehler.cfm?anzeige=103&mid=43",
                    "source": "IHK Lehrstellenbörse",
                },
                {
                    "title": "Koch / Köchin (m/w/d)",
                    "company": "Maritim Hotelgesellschaft mbH",
                    "city": "Frankfurt",
                    "url": "https://jobs.meine-ausbildung-in-deutschland.de/klick_zaehler.cfm?anzeige=104&mid=43",
                    "source": "IHK Lehrstellenbörse",
                },
            ]

            def mock_session_get(url, **kwargs):
                resp = MagicMock()
                resp.status_code = 200
                if "anzeige=101" in url:
                    resp.url = "https://jobs.soliver-group.com/talentcommunity/apply/1449346633/?locale=de_DE"
                    resp.text = '<html><body><form><input type="file" name="cv"/></form></body></html>'
                elif "anzeige=102" in url:
                    resp.url = "https://karriere.gi-de.com/stellenangebot/fisi-2027"
                    resp.text = '<html><body><a href="mailto:ausbildung@gi-de.com">Bewerben</a></body></html>'
                elif "anzeige=103" in url:
                    resp.url = "https://careers.dentsplysirona.com/talentcommunity/apply/993391401/?locale=de_DE"
                    resp.text = '<html><body><form><input type="file" name="cv"/></form></body></html>'
                elif "anzeige=104" in url:
                    resp.url = "https://karriere.maritim.de/apply/koch-frankfurt-104"
                    resp.text = '<html><body><form><input type="file" name="resume"/></form></body></html>'
                return resp

            with patch.object(worker.session, "get", side_effect=mock_session_get):
                results = [worker.extract_via_fast_http(j) for j in ihk_jobs]

            self.assertEqual(
                results[0]["direct_application_url"],
                "https://jobs.soliver-group.com/talentcommunity/apply/1449346633/?locale=de_DE",
            )
            self.assertEqual(results[1]["email"], "ausbildung@gi-de.com")
            self.assertNotIn("soliver", results[1].get("direct_application_url", ""))
            self.assertEqual(
                results[2]["direct_application_url"],
                "https://careers.dentsplysirona.com/talentcommunity/apply/993391401/?locale=de_DE",
            )
            self.assertEqual(
                results[3]["direct_application_url"],
                "https://karriere.maritim.de/apply/koch-frankfurt-104",
            )
            self.assertNotIn("dentsplysirona", results[3].get("direct_application_url", ""))

    # =========================================================================
    # 4. AZUBIYO REGRESSION TESTS
    # =========================================================================

    def test_azubiyo_rejects_unterrichtsmaterial_and_macromedia_cross_contamination(self):
        """
        Azubiyo:
        - Card parser skips 1-letter initial badge 'M' and extracts 'Macromedia Akademie'
        - Educational material URL (/unterrichtsmaterial/arbeitshefte/berufswahl-bewerbung/) is rejected
        - bildungsberatungstuttgart@macromedia.de is accepted ONLY for Macromedia and rejected for unrelated employers
        - External JS application target (/bewerben/ -> validateAndTrackAndOpen) is extracted per job
        """
        # 4a. Test Azubiyo card parser skips 1-letter initial span "M"
        card_html = """
        <article class="job-offer-teaser">
            <span class="badge text-secondary">M</span>
            <span class="company-name text-secondary">Macromedia Akademie</span>
            <a href="/stellenanzeigen/fachinformatiker_macromedia_123/">
                <span class="h3">Ausbildung Fachinformatiker (m/w/d)</span>
            </a>
        </article>
        """
        soup = bs4.BeautifulSoup(card_html, "html.parser")
        scraper = AzubiyoScraper()
        parsed_cards = scraper._parse_cards(soup.find_all("article"))
        self.assertEqual(len(parsed_cards), 1)
        self.assertEqual(parsed_cards[0]["company"], "Macromedia Akademie")

        # 4b. Test educational URL and Macromedia email validation rules
        ok_edu, _ = is_url_compatible_with_job(
            "https://www.azubiyo.de/unterrichtsmaterial/arbeitshefte/berufswahl-bewerbung/",
            company="Steigenberger Hotels GmbH",
        )
        self.assertFalse(ok_edu)

        ok_macro_self, _ = is_email_compatible_with_employer(
            "bildungsberatungstuttgart@macromedia.de",
            "Macromedia Akademie",
        )
        self.assertTrue(ok_macro_self)

        ok_macro_other, _ = is_email_compatible_with_employer(
            "bildungsberatungstuttgart@macromedia.de",
            "Deutsche Telekom AG",
        )
        self.assertFalse(ok_macro_other)

        # 4c. Test Azubiyo /bewerben/ JS target extraction and navbar noise filtering
        with patch.object(WorkingEmailExtractor, "setup_driver"):
            worker = WorkingEmailExtractor("u", "k", headless=True)
            az_job = {
                "title": "Ausbildung zum Koch (m/w/d)",
                "company": "Biohotel Sturm",
                "city": "Mellrichstadt",
                "url": "https://www.azubiyo.de/stellenanzeigen/ausbildung-zum-koch_biohotel-sturm_999/",
                "source": "Azubiyo",
            }
            main_html = """
            <html><body>
                <nav>
                    <a href="https://www.azubiyo.de/unterrichtsmaterial/arbeitshefte/berufswahl-bewerbung/">Orientieren und Bewerben</a>
                </nav>
                <main>
                    <h1>Ausbildung zum Koch (m/w/d)</h1>
                    <a href="/stellenanzeigen/ausbildung-zum-koch_biohotel-sturm_999/bewerben/">Auf Arbeitgeber-Webseite bewerben</a>
                </main>
                <footer>
                    <a href="tel:+498941614100">+49 89 41614100</a>
                </footer>
            </body></html>
            """
            bewerben_html = """
            <html><body>
                <script>
                    validateAndTrackAndOpen(1, "https://www.biohotel-sturm.de/karriere/bewerbung-koch");
                </script>
            </body></html>
            """

            def mock_az_get(url, **kwargs):
                r = MagicMock()
                r.status_code = 200
                r.url = url
                r.text = bewerben_html if url.endswith("/bewerben/") else main_html
                return r

            with patch.object(worker.session, "get", side_effect=mock_az_get):
                res = worker.extract_via_fast_http(az_job)

            self.assertIsNotNone(res)
            self.assertEqual(res["direct_application_url"], "https://www.biohotel-sturm.de/karriere/bewerbung-koch")
            self.assertEqual(res["form_link"], "https://www.biohotel-sturm.de/karriere/bewerbung-koch")
            self.assertEqual(res["phone"], "")  # Portal footer hotline +498941614100 must be filtered out

    # =========================================================================
    # 5. AUBI-PLUS REGRESSION TESTS
    # =========================================================================

    def test_aubi_plus_resolves_short_sg_per_job_and_prevents_reuse(self):
        """
        AUBI-plus:
        - Resolves short.sg URLs per job to the real employer ATS URL
        - Ignores footer bewerbung2go.de and empty mailto:?body=... share links
        - Never reuses Madeleine Kröger or +49577249345 across unrelated AUBI-plus jobs
        """
        with patch.object(WorkingEmailExtractor, "setup_driver"):
            worker = WorkingEmailExtractor("u", "k", headless=True)

            job1 = {
                "title": "Fachinformatiker Systemintegration (m/w/d)",
                "company": "adp MERKUR GmbH",
                "city": "Lübbecke",
                "url": "https://www.aubi-plus.de/stellenangebot/adp-merkur-111/",
                "source": "AUBI-plus",
            }
            job2 = {
                "title": "Fachinformatiker Anwendungsentwicklung (m/w/d)",
                "company": "steute Technologies GmbH & Co. KG",
                "city": "Löhne",
                "url": "https://www.aubi-plus.de/stellenangebot/steute-222/",
                "source": "AUBI-plus",
            }

            html1 = """
            <html><body>
                <main>
                    <a href="https://short.sg/a/66030513">Online-Bewerbung starten</a>
                    <p>Ansprechpartner: Frau Madeleine Kröger</p>
                    <a href="tel:+49577249345">05772 49345</a>
                </main>
                <footer>
                    <a href="mailto:?body=https://www.aubi-plus.de/stellenangebot/adp-merkur-111/">Teilen</a>
                    <a href="https://www.bewerbung2go.de/">Bewerbungsvorlagen</a>
                </footer>
            </body></html>
            """
            html2 = """
            <html><body>
                <main>
                    <a href="https://short.sg/a/99887766">Online-Bewerbung starten</a>
                    <p>Ansprechpartner: Herr Thomas Meyer</p>
                    <a href="tel:+4957317450">05731 7450</a>
                </main>
                <footer>
                    <a href="https://www.bewerbung2go.de/">Bewerbungsvorlagen</a>
                </footer>
            </body></html>
            """

            def mock_aubi_get(url, **kwargs):
                r = MagicMock()
                r.status_code = 200
                if "66030513" in url:
                    r.url = "https://gauselmann.softgarden.io/job/66030513?l=de"
                    r.text = ""
                elif "99887766" in url:
                    r.url = "https://steute.softgarden.io/job/99887766?l=de"
                    r.text = ""
                elif "adp-merkur" in url:
                    r.url = url
                    r.text = html1
                else:
                    r.url = url
                    r.text = html2
                return r

            with patch.object(worker.session, "get", side_effect=mock_aubi_get):
                res1 = worker.extract_via_fast_http(job1)
                res2 = worker.extract_via_fast_http(job2)

            self.assertEqual(res1["direct_application_url"], "https://gauselmann.softgarden.io/job/66030513?l=de")
            self.assertEqual(res1["contact_person"], "Frau Madeleine Kröger")
            self.assertEqual(res1["phone"], "+49577249345")

            self.assertEqual(res2["direct_application_url"], "https://steute.softgarden.io/job/99887766?l=de")
            self.assertEqual(res2["contact_person"], "Herr Thomas Meyer")
            self.assertEqual(res2["phone"], "+4957317450")
            self.assertNotEqual(res2["direct_application_url"], res1["direct_application_url"])

    # =========================================================================
    # 6. ARBEITSAGENTUR REGRESSION TESTS
    # =========================================================================

    def test_arbeitsagentur_externe_url_and_portal_homepage_rejection(self):
        """
        Arbeitsagentur:
        - Extracts specific externeURL from SSR JSON and normalizes missing-scheme allianzpartnerUrl
        - Rejects bare generic portal roots like https://jobs.hogapage.de as application forms
        - Does not capture prose sentences after 'Ansprechpartnerin' without a colon
        """
        aa_ext = ArbeitsagenturDetailExtractor()

        ssr_html = """
        <html><body>
            <div class="ba-copytext">
                <p>Deine Ansprechpartnerin und das Team stehen dir mit Rat und Tat zur Seite.</p>
            </div>
            <script id="from-ssr">
                {"jobdetail": {
                    "firma": "WM SE",
                    "externeURL": "https://www.stellenanzeigen.de/job/9289558/?campaign=ba",
                    "allianzpartnerUrl": "https://jobs.hogapage.de"
                }}
            </script>
        </body></html>
        """
        parsed = aa_ext.parse_application_section(
            ssr_html,
            source_url="https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-11111-S",
        )
        # Prose sentence must NOT be captured as contact_person
        self.assertEqual(parsed["contact_person"], "")
        # Specific externeURL must be chosen over bare generic portal root https://jobs.hogapage.de
        self.assertEqual(
            parsed["direct_application_url"],
            "https://www.stellenanzeigen.de/job/9289558/?campaign=ba",
        )

    # =========================================================================
    # 7. MULTI-WORKER CONCURRENCY & CROSS-EMPLOYER CONTAMINATION DETECTOR
    # =========================================================================

    def test_four_concurrent_workers_across_mixed_platforms_zero_contamination(self):
        """Run 4 concurrent workers across mixed platforms and verify zero cross-employer leakage."""
        jobs = [
            {
                "id": f"job_{i}",
                "title": f"Ausbildung Position {i}",
                "company": f"UniqueEmployer_{i} GmbH",
                "city": "Berlin",
                "url": f"https://www.ausbildung.de/stellen/unique-job-{i}/",
                "source": "ausbildung.de",
            }
            for i in range(16)
        ]

        def worker_run(job_item):
            idx = int(job_item["id"].split("_")[1])
            s = MagicMock()
            r = MagicMock()
            r.status_code = 200
            r.url = job_item["url"]
            r.text = f'<html><body><a href="mailto:bewerbung@unique-employer-{idx}.de">Mail</a></body></html>'
            s.get.return_value = r
            ext = AusbildungDeDetailExtractor(session=s)
            return ext.extract_vacancy(job_item, driver=None, session=s, worker_id=(idx % 4) + 1)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(worker_run, jobs))

        cleaned, report = detect_and_clean_cross_employer_contamination(results)
        self.assertEqual(report["contaminated_rows_cleaned"], 0)
        for idx, res in enumerate(cleaned):
            self.assertEqual(res["email"], f"bewerbung@unique-employer-{idx}.de")
            self.assertEqual(res["validation_status"], "verified")

    def test_contamination_detector_cleans_poisoned_batch_before_excel_export(self):
        """
        Verify that if a batch contains cross-employer duplicated emails, URLs, phones, or contacts,
        detect_and_clean_cross_employer_contamination and _build_excel_export_dataframe strip the
        contaminated values while keeping the legitimate owner's contact intact.
        """
        poisoned_batch = [
            {
                "title": "Kaufmann Büromanagement",
                "company": "Nordwasser GmbH",
                "city": "Rostock",
                "source": "ausbildung.de",
                "job_listing_url": "https://www.ausbildung.de/stellen/nordwasser-1",
                "email": "claudia.guenther@nordwasser.de",
            },
            {
                "title": "Fachinformatiker",
                "company": "CODAN Medizinische Geräte GmbH",
                "city": "Lensahn",
                "source": "ausbildung.de",
                "job_listing_url": "https://www.ausbildung.de/stellen/codan-2",
                "email": "claudia.guenther@nordwasser.de",
            },
            {
                "title": "Fachinformatiker",
                "company": "Siemens AG",
                "city": "München",
                "source": "ausbildung.de",
                "job_listing_url": "https://www.ausbildung.de/stellen/siemens-3",
                "email": "claudia.guenther@nordwasser.de",
            },
        ]

        df = app_module._build_excel_export_dataframe(poisoned_batch)
        # Row 0 (Nordwasser GmbH) keeps its legitimate email!
        self.assertEqual(df.iloc[0]["email"], "claudia.guenther@nordwasser.de")
        # Rows 1 & 2 (CODAN and Siemens) have the contaminated Nordwasser email stripped!
        self.assertEqual(df.iloc[1]["email"], "")
        self.assertEqual(df.iloc[2]["email"], "")


if __name__ == "__main__":
    unittest.main()

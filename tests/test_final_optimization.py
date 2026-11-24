"""
Comprehensive regression tests for JobScout Final Optimization:
Part 1 — Application URL Classification, Validation & Career Crawl
Part 2 — Occupation Normalization, Relevance Scoring & Two-Stage Filtering
Part 3 — IHK 5-Step Contact Extraction, TYPO3 Decoding & Corporate Group Isolation
"""

import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from services.application_url_validator import (
    ApplicationDestinationType,
    classify_and_validate_destination,
    decode_typo3_mailto,
    extract_all_emails_including_obfuscated,
    follow_generic_employer_website,
    is_structural_generic_homepage,
)
from services.contamination_detector import (
    attach_contact_provenance,
    detect_and_clean_cross_employer_contamination,
)
from services.data_validator import validate_application_url
from scraper.search_filter_engine import (
    filter_and_deduplicate_jobs_with_audit,
    normalize_occupation_term,
    score_occupation_relevance,
    verify_ambiguous_job_relevance,
)
from scraper.application_form_discovery import normalize_job_opportunity_row
from scraper.working_email_extractor import WorkingEmailExtractor
from app import _build_excel_export_dataframe


class ApplicationUrlValidationTestCase(unittest.TestCase):
    """Part 1: Application URL classification, validation, and generic homepage rejection."""

    def test_generic_employer_homepages_rejected_as_application_urls(self):
        generic_urls = [
            ("https://www.deimann.de", "Hotel Deimann GmbH & Co. KG"),
            ("https://www.bmas.de", "Bundesministerium für Arbeit und Soziales"),
            ("https://www.boehringer-ingelheim.com", "Boehringer Ingelheim Pharma GmbH & Co. KG"),
            ("https://jobs.umg-gastronomie.de/", "UMG Gastronomie GmbH"),
            ("https://www.lokschuppen-marburg.com", "Lokschuppen Marburg GmbH"),
            ("http://www.hohe-wacht.de", "Ostsee Resort Hohe Wacht"),
            ("http://www.pa.polizei-nds.de", "Polizeiakademie Niedersachsen"),
            ("https://www.ludwigsburg.de/start.html", "Stadt Ludwigsburg"),
        ]
        for url, company in generic_urls:
            self.assertTrue(
                is_structural_generic_homepage(url),
                f"Expected {url} to be detected as structural generic homepage/career root",
            )
            ok, _, _ = validate_application_url(url)
            self.assertFalse(ok, f"Expected validate_application_url({url}) to return False")

            cls = classify_and_validate_destination(
                url,
                company=company,
                job_title="Ausbildung zum Koch (m/w/d)",
                fetch_if_needed=False,
            )
            self.assertFalse(cls["application_url_verified"], f"{url} must NOT be verified")
            self.assertIn(
                cls["application_url_type"],
                {
                    ApplicationDestinationType.GENERIC_EMPLOYER_WEBSITE.value,
                    ApplicationDestinationType.EMPLOYER_CAREERS_PAGE.value,
                },
            )
            self.assertEqual(cls["employer_website_url"], url)

    def test_generic_homepage_demoted_to_employer_website_in_excel_export(self):
        records = [
            {
                "source": "Arbeitsagentur",
                "title": "Ausbildung zum Koch (m/w/d)",
                "company": "Hotel Deimann GmbH & Co. KG",
                "city": "Schmallenberg",
                "job_listing_url": "https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-deimann",
                "direct_application_url": "https://www.deimann.de",
                "bewerbung_link": "https://www.deimann.de",
                "application_method": "external_link",
            }
        ]
        df = _build_excel_export_dataframe(records)
        self.assertEqual(len(df), 1)
        row = df.iloc[0]
        self.assertEqual(row["direct_application_url"], "")
        self.assertEqual(row["employer_website"], "https://www.deimann.de")

    def test_direct_application_form_and_ats_classified_as_verified(self):
        # 1. External ATS portal (Softgarden / Personio / Workday)
        ats_url = "https://dentsplysirona.com/talentcommunity/apply/987654/?locale=de_DE"
        cls_ats = classify_and_validate_destination(
            ats_url,
            company="Dentsply Sirona Deutschland GmbH",
            job_title="Ausbildung zum Koch (m/w/d)",
        )
        self.assertTrue(cls_ats["application_url_verified"])
        self.assertIn(
            cls_ats["application_url_type"],
            {
                ApplicationDestinationType.DIRECT_APPLICATION_FORM.value,
                ApplicationDestinationType.RECRUITMENT_PORTAL.value,
            },
        )

        # 2. Direct application form with HTML evidence
        form_html = """
        <html><head><title>Bewerbung Ausbildung Koch (m/w/d) - Hotel Deimann</title></head>
        <body>
          <h1>Online-Bewerbung: Ausbildung zum Koch (m/w/d)</h1>
          <form action="/apply/submit" method="post">
            <input type="text" name="vorname" />
            <input type="text" name="nachname" />
            <input type="file" name="lebenslauf" />
            <button type="submit">Bewerbung absenden</button>
          </form>
        </body></html>
        """
        cls_form = classify_and_validate_destination(
            "https://www.deimann.de/karriere/ausbildung-koch-bewerbung",
            company="Hotel Deimann",
            job_title="Ausbildung zum Koch (m/w/d)",
            html_override=form_html,
        )
        self.assertTrue(cls_form["application_url_verified"])
        self.assertEqual(
            cls_form["application_url_type"],
            ApplicationDestinationType.DIRECT_APPLICATION_FORM.value,
        )
        self.assertTrue(cls_form["application_url_job_match"])
        self.assertTrue(cls_form["application_url_employer_match"])

    def test_job_specific_application_page_classified_as_verified(self):
        job_html = """
        <html><head><title>Ausbildung als Koch / Köchin (m/w/d) - DSR Hotel Holding</title></head>
        <body>
          <h1>Ausbildung als Koch / Köchin (m/w/d) für 2027</h1>
          <p>DSR Hotel Holding GmbH sucht Auszubildende in der Küche.</p>
          <a href="/jobs/apply/1136" class="btn">Jetzt bewerben</a>
        </body></html>
        """
        cls_page = classify_and_validate_destination(
            "https://www.dsr-hotelholding.de/jobs/ausbildung-als-koch-koechin-m-w-d-fuer-2027-1136/",
            company="DSR Hotel Holding GmbH",
            job_title="Ausbildung als Koch/Köchin",
            html_override=job_html,
        )
        self.assertTrue(cls_page["application_url_verified"])
        self.assertEqual(
            cls_page["application_url_type"],
            ApplicationDestinationType.JOB_SPECIFIC_APPLICATION_PAGE.value,
        )

    def test_login_required_and_broken_url_classification(self):
        # Login required (Arbeitsagentur bewerbungVerwalten.html)
        cls_login = classify_and_validate_destination(
            "https://www.arbeitsagentur.de/eservices-bewerbung/bewerbungVerwalten.html?id=123",
            company="Test GmbH",
            job_title="Koch",
        )
        self.assertFalse(cls_login["application_url_verified"])
        self.assertEqual(
            cls_login["application_url_type"],
            ApplicationDestinationType.LOGIN_REQUIRED.value,
        )

        # Broken URL (HTTP 404 on fetch)
        mock_sess = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.url = "https://www.example-hotel.de/missing-job"
        mock_resp.text = "<html><body>404 Not Found</body></html>"
        mock_resp.history = []
        mock_sess.get.return_value = mock_resp

        cls_broken = classify_and_validate_destination(
            "https://www.example-hotel.de/missing-job",
            company="Example Hotel",
            job_title="Koch",
            session=mock_sess,
            fetch_if_needed=True,
        )
        self.assertFalse(cls_broken["application_url_verified"])
        self.assertEqual(
            cls_broken["application_url_type"],
            ApplicationDestinationType.BROKEN_URL.value,
        )

    def test_follow_generic_employer_website_discovers_job_page_and_email(self):
        mock_sess = MagicMock()

        def fake_get(url, timeout=5, allow_redirects=True):
            r = MagicMock()
            r.status_code = 200
            r.url = url
            if url.rstrip("/") == "https://www.lokschuppen-marburg.com":
                r.text = '<html><body><a href="/karriere/ausbildung">Karriere & Ausbildung</a></body></html>'
            elif "/karriere/ausbildung" in url and "koch" not in url:
                r.text = '<html><body><a href="/karriere/ausbildung-koch">Ausbildung zum Koch (m/w/d)</a></body></html>'
            elif "ausbildung-koch" in url:
                r.text = """
                <html><head><title>Ausbildung zum Koch (m/w/d) - Lokschuppen Marburg</title></head>
                <body>
                  <h1>Ausbildung zum Koch (m/w/d)</h1>
                  <p>Bewerbung per E-Mail an <a href="mailto:karriere@lokschuppen-marburg.com">karriere@lokschuppen-marburg.com</a></p>
                  <a href="/apply/koch">Jetzt bewerben</a>
                </body></html>
                """
            else:
                r.status_code = 404
                r.text = ""
            return r

        mock_sess.get.side_effect = fake_get
        crawl = follow_generic_employer_website(
            start_url="https://www.lokschuppen-marburg.com",
            company="Lokschuppen Marburg",
            job_title="Ausbildung zum Koch (m/w/d)",
            session=mock_sess,
            max_requests=4,
        )
        self.assertEqual(crawl["discovered_email"], "karriere@lokschuppen-marburg.com")
        self.assertEqual(
            crawl["resolved_application_url"],
            "https://www.lokschuppen-marburg.com/karriere/ausbildung-koch",
        )


class SearchRelevanceFilteringOptimizationTestCase(unittest.TestCase):
    """Part 2: Occupation normalization, 5-tier relevance scoring, and two-stage filtering."""

    def test_occupation_normalization_across_professions(self):
        self.assertEqual(normalize_occupation_term("Ausbildung zum Koch (m/w/d) 2027"), "koch")
        self.assertEqual(normalize_occupation_term("Ausbildungsplatz als Köchin [w/m/d]"), "köchin")
        self.assertEqual(
            normalize_occupation_term("Ausbildung zum Fachinformatiker für Systemintegration (m/w/d)"),
            "fachinformatiker systemintegration",
        )
        self.assertEqual(
            normalize_occupation_term("Ausbildung Kaufmann für Büromanagement (gn)"),
            "kaufmann büromanagement",
        )

    def test_stage_a_relevance_scoring_categories(self):
        query = "Ausbildung als Koch"

        # 1. exact_match
        j_exact = {"title": "Ausbildung zum Koch (m/w/d)", "company": "Hotel A"}
        s1 = score_occupation_relevance(j_exact, query)
        self.assertEqual(s1["occupation_match_type"], "exact_match")
        self.assertEqual(s1["relevance_score"], 1.0)

        # 2. equivalent_occupation (Köchin / Beikoch)
        j_equiv = {"title": "Ausbildung als Köchin (w/m/d)", "company": "Hotel B"}
        s2 = score_occupation_relevance(j_equiv, query)
        self.assertEqual(s2["occupation_match_type"], "equivalent_occupation")
        self.assertEqual(s2["relevance_score"], 0.95)

        # 3. probable_match (generic title 'Ausbildung 2027' with hauptberuf='Koch/Köchin')
        j_prob = {"title": "Ausbildung 2027", "hauptberuf": "Koch/Köchin", "company": "Hotel C"}
        s3 = score_occupation_relevance(j_prob, query)
        self.assertEqual(s3["occupation_match_type"], "probable_match")
        self.assertEqual(s3["relevance_score"], 0.85)
        self.assertIn("Koch/Köchin", j_prob["title"])

        # 4. uncertain (generic title 'Ausbildung 2027' with no metadata yet)
        j_unc = {"title": "Ausbildung 2027 - Praktikum möglich", "company": "Hotel D"}
        s4 = score_occupation_relevance(j_unc, query)
        self.assertEqual(s4["occupation_match_type"], "uncertain")
        self.assertEqual(s4["relevance_score"], 0.50)

        # 5. irrelevant (conflicting occupation: Kaufmann für Versicherungen / Hotelfachmann)
        j_irr1 = {
            "title": "Kaufmann/-frau für Versicherungen und Finanzanlagen",
            "company": "Allianz",
        }
        s5 = score_occupation_relevance(j_irr1, query)
        self.assertEqual(s5["occupation_match_type"], "irrelevant")
        self.assertEqual(s5["relevance_score"], 0.0)

        j_irr2 = {"title": "Ausbildung Hotelfachmann/-frau (m/w/d)", "company": "Hotel E"}
        s6 = score_occupation_relevance(j_irr2, query)
        self.assertEqual(s6["occupation_match_type"], "irrelevant")

    def test_stage_b_detail_verification_accepts_confirmed_and_rejects_unconfirmed(self):
        query = "Ausbildung als Koch"

        # Uncertain card confirmed by detail page HTML
        j_confirm = {
            "title": "Ausbildung 2027",
            "company": "Restaurant Waldblick",
            "url": "https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-waldblick",
        }
        mock_sess = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '<html><body><script id="ng-state">{"hauptberuf":"Koch/Köchin"}</script></body></html>'
        mock_sess.get.return_value = mock_resp

        res_ok = verify_ambiguous_job_relevance(j_confirm, query, session=mock_sess)
        self.assertEqual(res_ok["occupation_match_type"], "probable_match")
        self.assertIn("Koch/Köchin", j_confirm["title"])

        # Uncertain card with non-matching detail page -> rejected as irrelevant
        j_reject = {
            "title": "Ausbildung 2027",
            "company": "Büro Service GmbH",
            "url": "https://www.example.com/job/buero",
        }
        mock_resp_bad = MagicMock()
        mock_resp_bad.status_code = 200
        mock_resp_bad.text = "<html><body><h1>Ausbildung Kaufmann für Büromanagement</h1></body></html>"
        mock_sess.get.return_value = mock_resp_bad

        res_bad = verify_ambiguous_job_relevance(j_reject, query, session=mock_sess)
        self.assertEqual(res_bad["occupation_match_type"], "irrelevant")
        self.assertEqual(res_bad["relevance_score"], 0.0)

    def test_two_stage_pipeline_audit_summary(self):
        jobs = [
            {"title": "Ausbildung zum Koch (m/w/d)", "company": "A", "source": "ausbildung.de"},
            {"title": "Ausbildung zur Köchin (w/m/d)", "company": "B", "source": "azubiyo.de"},
            {"title": "Ausbildung 2027", "hauptberuf": "Koch/Köchin", "company": "C", "source": "Arbeitsagentur"},
            {"title": "Kaufmann/-frau für Versicherungen und Finanzanlagen", "company": "D", "source": "Arbeitsagentur"},
            {"title": "Ausbildung 2026", "company": "E", "source": "ihk.de"},  # uncertain with no URL -> rejected in Stage B
        ]
        filtered, audit = filter_and_deduplicate_jobs_with_audit(jobs, keyword="Ausbildung als Koch")
        self.assertEqual(len(filtered), 3)
        rel = audit["relevance_summary"]
        self.assertEqual(rel["exact_matches"], 1)
        self.assertEqual(rel["equivalent_occupation_matches"], 1)
        self.assertEqual(rel["probable_matches"], 1)
        self.assertEqual(rel["uncertain_results"], 1)
        self.assertEqual(rel["irrelevant_results_rejected"], 2)

    def test_erzieherin_and_gender_inclusive_german_variants(self):
        query = "Erzieherin"
        valid_titles = [
            "Ausbildung Erzieher (m/w/d)",
            "Ausbildung Erzieher/in",
            "Ausbildung zum/r staatlich anerkannten Erzieher*in",
            "Praxisintegrierte Ausbildung zum Erzieher",
            "Ausbildung Erzieher:in",
            "Ausbildung Erzieher_in",
            "Ausbildung ErzieherIn (w/m/d)",
            "Ausbildung Erzieher/-in",
        ]
        for title in valid_titles:
            scored = score_occupation_relevance({"title": title}, query)
            self.assertIn(
                scored["occupation_match_type"],
                {"exact_match", "equivalent_occupation"},
                f"Expected '{title}' to match '{query}', got {scored}",
            )
            self.assertGreaterEqual(scored["relevance_score"], 0.95)

        # Also verify feminine query for -frau/-in professions matches masculine/gender-inclusive titles
        for fem_query, valid_masc_title in [
            ("Pflegefachfrau", "Ausbildung Pflegefachmann/-frau (m/w/d)"),
            ("Kauffrau", "Ausbildung Kaufmann im Einzelhandel (m/w/d)"),
            ("Fachinformatikerin", "Ausbildung zum Fachinformatiker*in Anwendungsentwicklung"),
            ("Köchin", "Ausbildung Koch/Köchin (m/w/d)"),
            ("Verkäuferin", "Ausbildung Verkäufer:in (m/w/d)"),
        ]:
            scored_f = score_occupation_relevance({"title": valid_masc_title}, fem_query)
            self.assertIn(
                scored_f["occupation_match_type"],
                {"exact_match", "equivalent_occupation"},
                f"Expected '{valid_masc_title}' to match '{fem_query}', got {scored_f}",
            )


class IHKExtractionAndTypo3TestCase(unittest.TestCase):
    """Part 3: IHK 5-step extraction, TYPO3 decoding, Azubiyo entity unescaping, and corporate group isolation."""

    def test_typo3_caesar_cipher_email_decoding(self):
        # Real token from Sächsisches Staatsweingut GmbH Schloss Wackerbarth
        token = "ocknvq,dgygtdwpiBuejnquu/ycemgtdctvj0fg"
        decoded = decode_typo3_mailto(token, vector=2)
        self.assertEqual(decoded, "bewerbung@schloss-wackerbarth.de")

        html_sample = f'<a href="#" data-mailto-token="{token}" data-mailto-vector="2">bewerbung(at)schloss-wackerbarth.de</a>'
        emails = extract_all_emails_including_obfuscated(html_sample)
        self.assertIn("bewerbung@schloss-wackerbarth.de", emails)

    def test_ihk_redirect_to_404_recovers_via_career_crawl_and_typo3(self):
        with patch.object(WorkingEmailExtractor, "setup_driver"):
            ext = WorkingEmailExtractor("", "", headless=True)
        mock_sess = MagicMock()

        def fake_get(url, timeout=6, allow_redirects=True):
            r = MagicMock()
            if "klick_zaehler.cfm?anzeige=2461973735" in url:
                r.status_code = 404
                r.url = "https://www.schloss-wackerbarth.de/jobs-karriere/ausbildung/koch?utm_source=meine-ausbildung-in-deutschland"
                h1 = MagicMock()
                h1.url = url
                r.history = [h1]
                r.text = '<html><body><a href="/jobs-und-karriere/ausbildung">Ausbildung</a></body></html>'
            elif url.endswith("/jobs-und-karriere/ausbildung"):
                r.status_code = 200
                r.url = url
                r.history = []
                r.text = '<html><body><a href="/jobs-und-karriere/ausbildung/koch">Koch (m/w/d)</a></body></html>'
            elif url.endswith("/jobs-und-karriere/ausbildung/koch"):
                r.status_code = 200
                r.url = url
                r.history = []
                r.text = """
                <html><head><title>Ausbildung Koch (m/w/d) - Schloss Wackerbarth</title></head>
                <body>
                  <h1>Ausbildung Koch (m/w/d)</h1>
                  <a data-mailto-token="ocknvq,dgygtdwpiBuejnquu/ycemgtdctvj0fg" data-mailto-vector="2">E-Mail</a>
                </body></html>
                """
            else:
                r.status_code = 404
                r.url = url
                r.history = []
                r.text = ""
            return r

        mock_sess.get.side_effect = fake_get
        ext.session = mock_sess

        ihk_job = {
            "source": "ihk.de",
            "title": "Ausbildung Koch / Köchin (m/w/d)",
            "company": "Sächsisches Staatsweingut GmbH Schloss Wackerbarth",
            "city": "Radebeul",
            "url": "https://jobs.meine-ausbildung-in-deutschland.de/klick_zaehler.cfm?anzeige=2461973735&mid=43",
            "apply_url": "https://jobs.meine-ausbildung-in-deutschland.de/klick_zaehler.cfm?anzeige=2461973735&mid=43",
        }
        res = ext.extract_via_fast_http(ihk_job)
        self.assertIsNotNone(res)
        self.assertEqual(res["email"], "bewerbung@schloss-wackerbarth.de")
        self.assertEqual(
            res["job_listing_url"],
            "https://jobs.meine-ausbildung-in-deutschland.de/klick_zaehler.cfm?anzeige=2461973735&mid=43",
        )

    def test_azubiyo_escaped_setapplication_extracts_real_employer_url(self):
        with patch.object(WorkingEmailExtractor, "setup_driver"):
            ext = WorkingEmailExtractor("", "", headless=True)
        mock_sess = MagicMock()

        main_html = """
        <html><body>
          <script type="application/ld+json">{"@type":"JobPosting","hiringOrganization":{"name":"Netto Marken-Discount"}}</script>
          <a href="/stellenanzeigen/8B32D563/bewerben/">Jetzt bewerben</a>
        </body></html>
        """
        sub_html = """
        <html><body>
          <a onclick="setApplication(2, &quot;https://www.netto-online.de/karriere/Ausbildung-Koch-mwd.chtm&quot;, false)">Weiter zur Bewerbung</a>
        </body></html>
        """

        def fake_get(url, timeout=4, allow_redirects=True):
            r = MagicMock()
            r.status_code = 200
            r.url = url
            r.text = sub_html if "/bewerben" in url else main_html
            return r

        mock_sess.get.side_effect = fake_get
        ext.session = mock_sess

        job = {
            "source": "azubiyo.de",
            "title": "Ausbildung zum Koch (m/w/d)",
            "company": "Netto Marken-Discount",
            "city": "Maxhütte-Haidhof",
            "url": "https://www.azubiyo.de/stellenanzeigen/koch-netto-8B32D563/",
        }
        res = ext._extract_azubiyo_fast(
            job,
            main_html,
            "https://www.azubiyo.de/stellenanzeigen/koch-netto-8B32D563/",
        )
        self.assertIsNotNone(res)
        self.assertEqual(
            res["direct_application_url"],
            "https://www.netto-online.de/karriere/Ausbildung-Koch-mwd.chtm",
        )
        self.assertNotIn("azubiyo.de", res["direct_application_url"])

    def test_corporate_group_shared_emails_preserved_without_false_contamination(self):
        # DSR Hotel Holding GmbH & A-ROSA Hotels share c.bentz@a-rosa.de
        # Smartig - die Gastgeber GmbH & hôtel schloss romrod share bewerbung@schlossromrod-villaraab.team
        records = [
            {
                "source": "ihk.de",
                "title": "Ausbildung als Koch/Köchin",
                "company": "A-ROSA Hotels",
                "email": "c.bentz@a-rosa.de",
                "job_listing_url": "https://jobs.meine-ausbildung-in-deutschland.de/klick_zaehler.cfm?anzeige=1",
            },
            {
                "source": "ihk.de",
                "title": "Ausbildung als Koch/Köchin",
                "company": "DSR Hotel Holding GmbH",
                "email": "c.bentz@a-rosa.de",
                "job_listing_url": "https://jobs.meine-ausbildung-in-deutschland.de/klick_zaehler.cfm?anzeige=2",
            },
            {
                "source": "ihk.de",
                "title": "Ausbildung zum Koch (m/w/d)",
                "company": "Smartig - die Gastgeber GmbH",
                "email": "bewerbung@schlossromrod-villaraab.team",
                "job_listing_url": "https://jobs.meine-ausbildung-in-deutschland.de/klick_zaehler.cfm?anzeige=3",
            },
            {
                "source": "ihk.de",
                "title": "Ausbildung zum Koch (m/w/d)",
                "company": "hôtel schloss romrod",
                "email": "bewerbung@schlossromrod-villaraab.team",
                "job_listing_url": "https://jobs.meine-ausbildung-in-deutschland.de/klick_zaehler.cfm?anzeige=4",
            },
        ]
        cleaned, report = detect_and_clean_cross_employer_contamination(records)
        self.assertEqual(len(report.get("email", [])), 0)
        for r in cleaned:
            self.assertTrue(r["email"], f"Expected email for {r['company']} to be preserved")

    def test_concurrent_multi_worker_ihk_extraction_isolation(self):
        def run_worker(idx: int):
            ext = WorkingEmailExtractor(headless=True, worker_id=idx)
            mock_sess = MagicMock()
            r = MagicMock()
            r.status_code = 200
            r.url = f"https://www.hotel-employer-{idx}.de/karriere/ausbildung-koch-{idx}"
            r.history = []
            r.text = f"""
            <html><head><title>Ausbildung Koch - Hotel Employer {idx}</title></head>
            <body>
              <h1>Ausbildung zum Koch (m/w/d)</h1>
              <a href="mailto:bewerbung@hotel-employer-{idx}.de">bewerbung@hotel-employer-{idx}.de</a>
            </body></html>
            """
            mock_sess.get.return_value = r
            ext.session = mock_sess
            job = {
                "source": "ihk.de",
                "title": "Ausbildung zum Koch (m/w/d)",
                "company": f"Hotel Employer {idx} GmbH",
                "city": "Berlin",
                "url": f"https://jobs.meine-ausbildung-in-deutschland.de/klick_zaehler.cfm?anzeige=900{idx}&mid=43",
                "apply_url": f"https://jobs.meine-ausbildung-in-deutschland.de/klick_zaehler.cfm?anzeige=900{idx}&mid=43",
            }
            return ext.extract_via_fast_http(job)

        with patch.object(WorkingEmailExtractor, "setup_driver"):
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(run_worker, range(1, 9)))

        for idx, res in enumerate(results, start=1):
            self.assertIsNotNone(res)
            self.assertEqual(res["email"], f"bewerbung@hotel-employer-{idx}.de")
            self.assertEqual(res["company"], f"Hotel Employer {idx} GmbH")


if __name__ == "__main__":
    unittest.main()

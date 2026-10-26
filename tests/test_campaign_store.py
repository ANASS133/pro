import unittest
import tempfile
import shutil
from pathlib import Path
from services.campaign_store import CampaignStore

class TestCampaignStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_campaigns.db"
        self.assets_dir = Path(self.temp_dir) / "test_assets"
        self.store = CampaignStore(db_path=self.db_path, assets_dir=self.assets_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_and_retrieve_campaign(self):
        camp = {
            "id": "camp-123",
            "name": "Ausbildung 2026",
            "mode": "transfer",
            "rows": [{"company": "Test GmbH", "recipient": "bewerbung@test.de"}],
            "anschreiben": {"template": "Sehr geehrte Damen und Herren"},
            "attachments": [
                {
                    "filename": "cv.pdf",
                    "content_b64": "JVBERi0xLjQgVGVzdCBQREYgQnl0ZXM=",
                    "mimetype": "application/pdf"
                }
            ]
        }
        saved = self.store.save_campaign(camp)
        self.assertEqual(saved["id"], "camp-123")
        self.assertEqual(saved["name"], "Ausbildung 2026")
        self.assertEqual(len(saved["rows"]), 1)
        self.assertEqual(len(saved["attachments"]), 1)
        self.assertTrue(Path(saved["attachments"][0]["file_path"]).exists())

        # Test listing
        all_camps = self.store.list_campaigns()
        self.assertEqual(len(all_camps), 1)

        # Test deletion
        self.store.delete_campaign("camp-123")
        self.assertIsNone(self.store.get_campaign("camp-123"))

if __name__ == "__main__":
    unittest.main()

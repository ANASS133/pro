import os
import unittest
from pathlib import Path
import pandas as pd

from app import app, AUTO_EXTRACTION_EXPORT_DIR, _list_auto_extraction_export_files, _invalidate_export_files_cache


class TestAusbildungenDeletion(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        AUTO_EXTRACTION_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        self.created_temp_files = []

    def tearDown(self):
        # Cleanup any remaining test files
        for p in self.created_temp_files:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        _invalidate_export_files_cache()

    def _create_temp_dataset(self, filename: str, rows=2) -> Path:
        target = AUTO_EXTRACTION_EXPORT_DIR / filename
        data = [
            {"title": f"Dev {i}", "company": f"Corp {i}", "email": f"corp{i}@test.de", "location": "Berlin"}
            for i in range(rows)
        ]
        df = pd.DataFrame(data)
        df.to_excel(target, index=False)
        self.created_temp_files.append(target)
        _invalidate_export_files_cache()
        return target

    def test_first_deletion_removes_file_and_invalidates_cache(self):
        test_file = self._create_temp_dataset("test_delete_fixture_1.xlsx", rows=3)
        self.assertTrue(test_file.exists())

        # Warm the 3-second cache
        initial_list = _list_auto_extraction_export_files()
        filenames_initial = [f["filename"] for f in initial_list]
        self.assertIn("test_delete_fixture_1.xlsx", filenames_initial)

        # Call delete endpoint
        resp = self.client.post("/api/ausbildungen/file/test_delete_fixture_1.xlsx/delete")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("deleted successfully", data.get("message", "").lower())

        # Verify file is removed from disk
        self.assertFalse(test_file.exists())

        # Verify cache was invalidated: immediate GET returns fresh list without deleted file
        fresh_api_resp = self.client.get("/api/ausbildungen/files")
        self.assertEqual(fresh_api_resp.status_code, 200)
        files_after = [f["filename"] for f in fresh_api_resp.get_json().get("files", [])]
        self.assertNotIn("test_delete_fixture_1.xlsx", files_after)

    def test_repeated_deletion_is_idempotent_and_user_friendly(self):
        # File does not exist
        resp = self.client.post("/api/ausbildungen/file/non_existent_already_deleted.xlsx/delete")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("already_deleted"))
        self.assertIn("already deleted", data.get("message", "").lower())

    def test_active_update_job_blocks_deletion(self):
        test_file = self._create_temp_dataset("test_active_job_block.xlsx", rows=1)
        import app as app_module

        # Mock a running job
        orig_get_job = app_module._get_running_ausbildungen_update_for_file
        app_module._get_running_ausbildungen_update_for_file = lambda fn: {"is_running": True, "job_id": "job_123"}
        try:
            resp = self.client.post(f"/api/ausbildungen/file/{test_file.name}/delete")
            self.assertEqual(resp.status_code, 400)
            data = resp.get_json()
            self.assertFalse(data.get("success"))
            self.assertIn("running", data.get("message", "").lower())
            self.assertTrue(test_file.exists())
        finally:
            app_module._get_running_ausbildungen_update_for_file = orig_get_job

    def test_merge_with_delete_sources_invalidates_cache(self):
        f1 = self._create_temp_dataset("test_merge_src_1.xlsx", rows=2)
        f2 = self._create_temp_dataset("test_merge_src_2.xlsx", rows=2)

        # Warm cache
        _list_auto_extraction_export_files()

        resp = self.client.post("/api/ausbildungen/merge", json={
            "filenames": [f1.name, f2.name],
            "delete_sources": True,
            "output_name": "test_merged_output.xlsx"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        merged_filename = data.get("merged_filename")
        self.assertIsNotNone(merged_filename)
        merged_path = AUTO_EXTRACTION_EXPORT_DIR / merged_filename
        self.created_temp_files.append(merged_path)

        # Verify sources are gone
        self.assertFalse(f1.exists())
        self.assertFalse(f2.exists())
        self.assertTrue(merged_path.exists())

        # Verify immediate listing contains the new merged file and not sources
        fresh_api = self.client.get("/api/ausbildungen/files")
        names = [f["filename"] for f in fresh_api.get_json().get("files", [])]
        self.assertIn(merged_filename, names)
        self.assertNotIn(f1.name, names)
        self.assertNotIn(f2.name, names)


if __name__ == "__main__":
    unittest.main()


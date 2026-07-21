from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

import git

from bilibili2txt.services.gitqueue import GitQueue


class TestPipelineStatus(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name) / "queue"
        self.repo_dir.mkdir()
        git.Repo.init(self.repo_dir)
        self.queue = GitQueue(self.repo_dir, logging.getLogger("test"))
        self.queue.ensure_layout()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_pipeline_status_lifecycle(self):
        # Initial status should be None
        self.assertIsNone(self.queue.get_pipeline_status())

        # Set status to submitting
        self.queue.set_pipeline_status("submitting", 5)
        status = self.queue.get_pipeline_status()
        self.assertIsNotNone(status)
        self.assertEqual(status["status"], "submitting")
        self.assertEqual(status["submitted_count"], 5)
        self.assertIn("updated_at", status)

        # Update status to complete
        self.queue.set_pipeline_status("complete", 10)
        status = self.queue.get_pipeline_status()
        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["submitted_count"], 10)

        # Clear status
        self.queue.clear_pipeline_status()
        self.assertIsNone(self.queue.get_pipeline_status())


if __name__ == "__main__":
    unittest.main()

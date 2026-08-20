import os
import tempfile
import unittest
from unittest.mock import patch

import server


class ProgressEndpointTests(unittest.TestCase):
    """`/progress/<tag>` is what the app polls while /reconstruct is still
    open, so it has to read stages out of the log main.py is writing live."""

    def write_log(self, directory, tag, text):
        path = os.path.join(directory, f"Tag={tag}.log")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def stage(self, directory, tag):
        with patch.object(server, "LOG_DIR", directory):
            return server.reconstruction_stage(tag)

    def test_no_log_yet_reads_as_queued(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.stage(directory, "abc123"), "queued")

    def test_reports_the_newest_stage_reached(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write_log(
                directory,
                "abc123-pc10-lidar",
                "Requested edge-mask backend: h5\n"
                "SSM PCA components: 10\n"
                "Start Stage 0.\n"
                "M-step loss: 1.0\n"
                "Start Stage 1.\n",
            )
            self.assertEqual(self.stage(directory, "abc123"), "stage1")

    def test_every_marker_is_reachable_and_ordered(self):
        seen = []
        with tempfile.TemporaryDirectory() as directory:
            text = ""
            for marker, name in server.PROGRESS_MARKERS:
                text += marker + "\n"
                self.write_log(directory, "abc123", text)
                seen.append(self.stage(directory, "abc123"))
        self.assertEqual(seen, [name for _, name in server.PROGRESS_MARKERS])

    def test_tags_that_could_escape_the_log_directory_are_rejected(self):
        for tag in ("../../etc/passwd", "a b", "", "x" * 41, "tag;rm"):
            self.assertFalse(server.is_valid_request_tag(tag), tag)
        self.assertTrue(server.is_valid_request_tag("a1b2c3d4e5f6"))

    def test_endpoint_rejects_an_unsafe_tag(self):
        client = server.app.test_client()
        self.assertEqual(client.get("/progress/not%20a%20tag").status_code, 400)


if __name__ == "__main__":
    unittest.main()

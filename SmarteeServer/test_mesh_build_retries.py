import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class MeshBuildRetryTests(unittest.TestCase):
    def test_timeout_retries_and_then_reports_failure(self):
        with tempfile.TemporaryDirectory() as root, patch.object(
            main.subprocess, "run", side_effect=subprocess.TimeoutExpired("worker", 1)
        ) as run:
            with self.assertRaisesRegex(RuntimeError, "failed after 2 attempts"):
                main.build_mesh_with_retries(
                    "result.h5",
                    root,
                    "tag",
                    retries=2,
                    attempt_timeout_seconds=1,
                )

        self.assertEqual(run.call_count, 2)

    def test_stale_output_files_do_not_count_as_a_fresh_success(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "tag"
            output.mkdir()
            (output / "Pred_Upper_Mesh_Tag=tag.obj").write_text("upper")
            (output / "Pred_Lower_Mesh_Tag=tag.obj").write_text("lower")
            with patch.object(
                main.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0),
            ) as run, self.assertRaisesRegex(RuntimeError, "failed after 1 attempts"):
                main.build_mesh_with_retries(
                    "result.h5", root, "tag", retries=1, attempt_timeout_seconds=1
                )

        run.assert_called_once()

    def test_fresh_output_files_complete_the_attempt(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "tag"

            def write_outputs(*args, **kwargs):
                output.mkdir()
                (output / "Pred_Upper_Mesh_Tag=tag.obj").write_text("upper")
                (output / "Pred_Lower_Mesh_Tag=tag.obj").write_text("lower")
                return subprocess.CompletedProcess([], 0)

            with patch.object(main.subprocess, "run", side_effect=write_outputs):
                main.build_mesh_with_retries(
                    "result.h5", root, "tag", retries=1, attempt_timeout_seconds=1
                )


class ReconstructionCLIExitTests(unittest.TestCase):
    def test_reconstruction_exception_returns_nonzero_and_restores_stdout(self):
        args = main.build_argument_parser().parse_args(["tag123"])
        original_stdout = main.sys.stdout

        def fail_after_redirect(*args, **kwargs):
            del args, kwargs
            main.sys.stdout = open(Path(tempfile.gettempdir()) / "failed-reconstruction.log", "a")
            raise RuntimeError("synthetic reconstruction failure")

        with patch.object(main, "main", side_effect=fail_after_redirect), patch.object(
            main.ray, "init"
        ), patch.object(main.ray, "shutdown"):
            exit_code = main.execute_reconstruction_cli(args)

        self.assertEqual(exit_code, 1)
        self.assertIs(main.sys.stdout, original_stdout)


if __name__ == "__main__":
    unittest.main()

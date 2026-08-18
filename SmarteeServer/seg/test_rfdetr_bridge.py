import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import skimage.io

from seg.rfdetr_bridge import (
    RFDETRInferenceError,
    predict_rfdetr_edge_masks,
    predict_rfdetr_predictions,
)


def write_fake_prediction(
    output_dir: Path,
    stem: str,
    image_path: Path,
    omit_instance: bool = False,
    empty_edge: bool = False,
):
    output_dir.mkdir()
    edge = np.zeros((10, 20), dtype=np.uint8)
    if not empty_edge:
        edge[2:8, 3:17] = 255
    instance = np.zeros((8, 12), dtype=np.uint8)
    instance[1:5, 2:6] = 255
    skimage.io.imsave(str(output_dir / f"{stem}_edge.png"), edge, check_contrast=False)
    if not omit_instance:
        skimage.io.imsave(
            str(output_dir / f"{stem}-instance-000.png"),
            instance,
            check_contrast=False,
        )
    manifest = {
        "schemaVersion": 1,
        "images": [
            {
                "image": str(image_path),
                "stem": stem,
                "width": 12,
                "height": 8,
                "edgeMask": f"{stem}_edge.png",
                "overlay": f"{stem}_overlay.png",
                "instances": [] if empty_edge else [
                    {
                        "localId": "instance-000",
                        "mask": f"{stem}-instance-000.png",
                        "confidence": 0.91,
                        "bboxXYWH": [2, 1, 4, 4],
                        "centroidXY": [3.5, 2.5],
                        "areaPixels": 16,
                    }
                ],
            }
        ],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class RFDETRBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.image = self.root / "patient-0.png"
        self.checkpoint = self.root / "checkpoint.pth"
        self.python_link = self.root / "venv-python"
        skimage.io.imsave(
            str(self.image), np.zeros((8, 12, 3), dtype=np.uint8), check_contrast=False
        )
        self.checkpoint.touch()
        self.python_link.symlink_to(sys.executable)

    def tearDown(self):
        self.temporary_directory.cleanup()

    @mock.patch("seg.rfdetr_bridge.subprocess.run")
    def test_reads_mask_created_by_worker(self, run):
        def create_prediction(command, **_kwargs):
            output_dir = Path(command[command.index("--output") + 1])
            write_fake_prediction(output_dir, "patient-0", self.image)
            return subprocess.CompletedProcess(command, 0, "ok", "")

        run.side_effect = create_prediction
        masks = predict_rfdetr_edge_masks(
            [str(self.image)],
            python_executable=self.python_link,
            script=Path(__file__),
            checkpoint=self.checkpoint,
        )

        self.assertEqual(len(masks), 1)
        self.assertEqual(masks[0].shape, (10, 20))
        self.assertEqual(masks[0].dtype, np.uint8)
        self.assertEqual(masks[0][3, 4], 255)
        self.assertEqual(run.call_args.args[0][0], str(self.python_link.absolute()))

    @mock.patch("seg.rfdetr_bridge.subprocess.run")
    def test_reads_structured_instances_created_by_worker(self, run):
        def create_prediction(command, **_kwargs):
            output_dir = Path(command[command.index("--output") + 1])
            write_fake_prediction(output_dir, "patient-0", self.image)
            return subprocess.CompletedProcess(command, 0, "ok", "")

        run.side_effect = create_prediction
        predictions = predict_rfdetr_predictions(
            [str(self.image)],
            python_executable=self.python_link,
            script=Path(__file__),
            checkpoint=self.checkpoint,
        )

        self.assertEqual(len(predictions), 1)
        self.assertEqual(predictions[0].source, "rfdetr")
        self.assertEqual(len(predictions[0].instances), 1)
        instance = predictions[0].instances[0]
        self.assertEqual(instance.local_id, "instance-000")
        self.assertEqual(instance.mask.shape, (8, 12))
        self.assertEqual(instance.bbox_xywh, (2, 1, 4, 4))
        self.assertAlmostEqual(instance.confidence, 0.91)

    @mock.patch("seg.rfdetr_bridge.subprocess.run")
    def test_missing_instance_png_returns_view_fallback_error(self, run):
        def create_prediction(command, **_kwargs):
            output_dir = Path(command[command.index("--output") + 1])
            write_fake_prediction(
                output_dir, "patient-0", self.image, omit_instance=True
            )
            return subprocess.CompletedProcess(command, 0, "ok", "")

        run.side_effect = create_prediction
        outcomes = predict_rfdetr_predictions(
            [str(self.image)],
            python_executable=self.python_link,
            script=Path(__file__),
            checkpoint=self.checkpoint,
        )

        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], RFDETRInferenceError)
        self.assertIn("instance mask", str(outcomes[0]))

    @mock.patch("seg.rfdetr_bridge.subprocess.run")
    def test_reports_worker_failure_for_h5_fallback(self, run):
        run.return_value = subprocess.CompletedProcess([], 2, "", "bad checkpoint")

        with self.assertRaisesRegex(RFDETRInferenceError, "bad checkpoint"):
            predict_rfdetr_edge_masks(
                [str(self.image)],
                python_executable=Path(sys.executable),
                script=Path(__file__),
                checkpoint=self.checkpoint,
            )

    @mock.patch("seg.rfdetr_bridge.subprocess.run")
    def test_rejects_empty_prediction_for_h5_fallback(self, run):
        def create_empty_prediction(command, **_kwargs):
            output_dir = Path(command[command.index("--output") + 1])
            write_fake_prediction(output_dir, "patient-0", self.image, empty_edge=True)
            return subprocess.CompletedProcess(command, 0, "ok", "")

        run.side_effect = create_empty_prediction

        with self.assertRaisesRegex(RFDETRInferenceError, "empty edge mask"):
            predict_rfdetr_edge_masks(
                [str(self.image)],
                python_executable=Path(sys.executable),
                script=Path(__file__),
                checkpoint=self.checkpoint,
            )


if __name__ == "__main__":
    unittest.main()

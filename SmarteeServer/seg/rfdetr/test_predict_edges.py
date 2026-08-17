import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from predict_edges import (
    edge_mask_from_instances,
    overlay_instances,
    write_instance_artifacts,
)


class EdgeMaskTests(unittest.TestCase):
    def test_traces_each_instance_boundary(self):
        masks = np.zeros((2, 10, 10), dtype=bool)
        masks[0, 2:6, 1:5] = True
        masks[1, 2:6, 5:9] = True

        edge = edge_mask_from_instances(masks, edge_width=None)

        self.assertEqual(edge.dtype, np.uint8)
        self.assertEqual(edge[2, 1], 255)
        self.assertEqual(edge[2, 5], 255)
        self.assertEqual(edge[4, 4], 255)
        self.assertEqual(edge[4, 5], 255)
        self.assertEqual(edge[3, 2], 0)

    def test_resizes_to_smartee_edge_width(self):
        masks = np.zeros((1, 10, 20), dtype=bool)
        masks[0, 2:8, 2:18] = True

        edge = edge_mask_from_instances(masks, edge_width=800)

        self.assertEqual(edge.shape, (400, 800))
        self.assertGreater(np.count_nonzero(edge), 0)


class InstanceArtifactTests(unittest.TestCase):
    def test_writes_one_binary_png_and_record_per_instance(self):
        masks = np.zeros((2, 8, 12), dtype=bool)
        masks[0, 1:5, 2:6] = True
        masks[1, 3:7, 7:11] = True

        with tempfile.TemporaryDirectory() as root:
            output = Path(root)
            records = write_instance_artifacts(
                output_dir=output,
                stem="patient-0",
                masks=masks,
                confidences=np.array([0.91, 0.82], dtype=np.float32),
                image_height=8,
                image_width=12,
            )

            self.assertEqual(
                [record["localId"] for record in records],
                ["instance-000", "instance-001"],
            )
            self.assertEqual(records[0]["bboxXYWH"], [2, 1, 4, 4])
            self.assertEqual(records[0]["areaPixels"], 16)
            saved = cv2.imread(
                str(output / records[0]["mask"]), cv2.IMREAD_GRAYSCALE
            )
            self.assertEqual(saved.shape, (8, 12))
            self.assertEqual(set(np.unique(saved)), {0, 255})

    def test_resizes_model_mask_to_source_rgb_with_nearest_neighbour(self):
        masks = np.zeros((1, 4, 6), dtype=bool)
        masks[0, 1:3, 2:4] = True

        with tempfile.TemporaryDirectory() as root:
            records = write_instance_artifacts(
                output_dir=Path(root),
                stem="patient-0",
                masks=masks,
                confidences=np.array([0.75], dtype=np.float32),
                image_height=8,
                image_width=12,
            )
            saved = cv2.imread(
                str(Path(root) / records[0]["mask"]), cv2.IMREAD_GRAYSCALE
            )
            self.assertEqual(saved.shape, (8, 12))
            self.assertEqual(set(np.unique(saved)), {0, 255})

    def test_rejects_mask_confidence_count_mismatch(self):
        masks = np.zeros((2, 8, 12), dtype=bool)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "confidence count"):
                write_instance_artifacts(
                    Path(root), "patient-0", masks, np.array([0.9]), 8, 12
                )

    def test_instance_overlay_uses_distinct_colours(self):
        image = np.zeros((8, 12, 3), dtype=np.uint8)
        masks = np.zeros((2, 8, 12), dtype=bool)
        masks[0, 1:5, 2:6] = True
        masks[1, 3:7, 7:11] = True

        overlay = overlay_instances(image, masks)

        first_colour = tuple(overlay[2, 3])
        second_colour = tuple(overlay[4, 8])
        self.assertNotEqual(first_colour, (0, 0, 0))
        self.assertNotEqual(second_colour, (0, 0, 0))
        self.assertNotEqual(first_colour, second_colour)


if __name__ == "__main__":
    unittest.main()

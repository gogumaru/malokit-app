import enum
import unittest
from unittest import mock

import numpy as np

from seg.edge_backends import (
    predict_automatic_edge_masks,
    predict_automatic_edge_predictions,
    resolve_edge_backend,
)
from seg.prediction_types import EdgePrediction, ToothInstancePrediction
from seg.rfdetr_bridge import RFDETRInferenceError


class Photo(enum.Enum):
    UPPER = 0
    LOWER = 1
    LEFT = 2


def make_rfdetr_prediction(value=9):
    instance_mask = np.full((2, 2), 255, dtype=np.uint8)
    return EdgePrediction(
        edge_mask=np.full((2, 2), value, dtype=np.uint8),
        source="rfdetr",
        instances=(
            ToothInstancePrediction(
                local_id="instance-000",
                mask=instance_mask,
                confidence=0.9,
                bbox_xywh=(0, 0, 2, 2),
                centroid_xy=(0.5, 0.5),
                area_pixels=4,
            ),
        ),
    )


class EdgeBackendTests(unittest.TestCase):
    def setUp(self):
        self.inputs = [(photo, f"{photo.value}.png") for photo in Photo]
        self.h5 = mock.Mock(
            side_effect=lambda paths: [np.full((2, 2), 5, dtype=np.uint8) for _ in paths]
        )
        self.rfdetr = mock.Mock(
            side_effect=lambda paths: [np.full((2, 2), 9, dtype=np.uint8) for _ in paths]
        )

    def test_h5_remains_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(resolve_edge_backend(), "h5")

    def test_rfdetr_routes_only_supported_views(self):
        masks, sources, fallback_error = predict_automatic_edge_masks(
            self.inputs, "rfdetr", (0, 1), self.rfdetr, self.h5
        )

        self.rfdetr.assert_called_once_with(["0.png", "1.png"])
        self.h5.assert_called_once_with(["2.png"])
        self.assertEqual(sources[Photo.UPPER], "rfdetr")
        self.assertEqual(sources[Photo.LEFT], "h5")
        self.assertEqual(int(masks[Photo.UPPER][0, 0]), 9)
        self.assertIsNone(fallback_error)

    def test_rfdetr_failure_falls_back_to_h5(self):
        self.rfdetr.side_effect = RFDETRInferenceError("checkpoint missing")

        _masks, sources, fallback_error = predict_automatic_edge_masks(
            self.inputs, "rfdetr", (0, 1), self.rfdetr, self.h5
        )

        self.h5.assert_called_once_with(["2.png", "0.png", "1.png"])
        self.assertTrue(all(source == "h5" for source in sources.values()))
        self.assertIn("checkpoint missing", str(fallback_error))

    def test_structured_router_preserves_rfdetr_instances(self):
        self.rfdetr.side_effect = lambda paths: [
            make_rfdetr_prediction() for _ in paths
        ]

        predictions, fallback_reasons = predict_automatic_edge_predictions(
            self.inputs, "rfdetr", (0, 1), self.rfdetr, self.h5
        )

        self.assertEqual(fallback_reasons, {})
        self.assertEqual(predictions[Photo.UPPER].source, "rfdetr")
        self.assertEqual(len(predictions[Photo.UPPER].instances), 1)
        self.assertEqual(predictions[Photo.LEFT].source, "h5")
        self.assertEqual(predictions[Photo.LEFT].instances, ())

    def test_structured_router_falls_back_only_the_invalid_view(self):
        self.rfdetr.side_effect = lambda _paths: [
            make_rfdetr_prediction(),
            RFDETRInferenceError("empty edge mask"),
        ]

        predictions, fallback_reasons = predict_automatic_edge_predictions(
            self.inputs, "rfdetr", (0, 1), self.rfdetr, self.h5
        )

        self.assertEqual(predictions[Photo.UPPER].source, "rfdetr")
        self.assertEqual(predictions[Photo.LOWER].source, "h5")
        self.assertEqual(fallback_reasons, {Photo.LOWER: "empty edge mask"})

    def test_process_failure_falls_back_the_attempted_batch(self):
        self.rfdetr.side_effect = RFDETRInferenceError("checkpoint missing")

        predictions, fallback_reasons = predict_automatic_edge_predictions(
            self.inputs, "rfdetr", (0, 1), self.rfdetr, self.h5
        )

        self.assertTrue(all(prediction.source == "h5" for prediction in predictions.values()))
        self.assertTrue(all(prediction.instances == () for prediction in predictions.values()))
        self.assertTrue(
            all("checkpoint missing" in reason for reason in fallback_reasons.values())
        )


if __name__ == "__main__":
    unittest.main()

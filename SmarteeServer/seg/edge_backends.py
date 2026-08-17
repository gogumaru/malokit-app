"""Select Smartee's automatic edge-mask backend and route fallback work."""

import os
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import numpy as np

from seg.prediction_types import EdgePrediction
from seg.rfdetr_bridge import RFDETRInferenceError


EDGE_BACKENDS = ("h5", "rfdetr")


def resolve_edge_backend(requested: Optional[str] = None) -> str:
    backend = (requested or os.environ.get("SMARTEE_EDGE_BACKEND", "h5")).lower()
    if backend not in EDGE_BACKENDS:
        raise ValueError(
            f"Unknown edge-mask backend '{backend}'. Choose one of: "
            f"{', '.join(EDGE_BACKENDS)}"
        )
    return backend


def predict_automatic_edge_predictions(
    inputs: Sequence[Tuple[object, str]],
    backend: str,
    rfdetr_photo_values: Iterable[int],
    rfdetr_predictor: Callable[
        [Sequence[str]], List[Union[EdgePrediction, RFDETRInferenceError]]
    ],
    h5_predictor: Callable[[Sequence[str]], List[np.ndarray]],
) -> Tuple[Dict[object, EdgePrediction], Dict[object, str]]:
    """Route RF-DETR outcomes and fall back only views that cannot be used."""

    backend = resolve_edge_backend(backend)
    rfdetr_values = set(rfdetr_photo_values)
    predictions = {}
    fallback_reasons = {}
    h5_inputs = list(inputs)

    if backend == "rfdetr":
        rfdetr_inputs = [item for item in inputs if item[0].value in rfdetr_values]
        h5_inputs = [item for item in inputs if item[0].value not in rfdetr_values]
        if rfdetr_inputs:
            try:
                outcomes = rfdetr_predictor([path for _, path in rfdetr_inputs])
                if len(outcomes) != len(rfdetr_inputs):
                    raise RFDETRInferenceError(
                        "RF-DETR returned a different number of predictions than "
                        "input images"
                    )
                for (photo_type, path), outcome in zip(rfdetr_inputs, outcomes):
                    if isinstance(outcome, EdgePrediction):
                        predictions[photo_type] = outcome
                    elif isinstance(outcome, RFDETRInferenceError):
                        fallback_reasons[photo_type] = str(outcome)
                        h5_inputs.append((photo_type, path))
                    else:
                        fallback_reasons[photo_type] = (
                            "RF-DETR returned an unsupported prediction outcome"
                        )
                        h5_inputs.append((photo_type, path))
            except RFDETRInferenceError as exc:
                for photo_type, path in rfdetr_inputs:
                    fallback_reasons[photo_type] = str(exc)
                    h5_inputs.append((photo_type, path))

    if h5_inputs:
        h5_masks = h5_predictor([path for _, path in h5_inputs])
        if len(h5_masks) != len(h5_inputs):
            raise RuntimeError(".h5 returned a different number of masks than input images")
        for (photo_type, _), edge_mask in zip(h5_inputs, h5_masks):
            predictions[photo_type] = EdgePrediction(
                edge_mask=edge_mask,
                source="h5",
                instances=(),
            )

    return predictions, fallback_reasons


def predict_automatic_edge_masks(
    inputs: Sequence[Tuple[object, str]],
    backend: str,
    rfdetr_photo_values: Iterable[int],
    rfdetr_predictor: Callable[[Sequence[str]], List[np.ndarray]],
    h5_predictor: Callable[[Sequence[str]], List[np.ndarray]],
) -> Tuple[Dict[object, np.ndarray], Dict[object, str], Optional[RFDETRInferenceError]]:
    """Project structured routing back to the legacy edge-mask contract."""

    def structured_rfdetr_predictor(paths):
        values = rfdetr_predictor(paths)
        return [
            value
            if isinstance(value, (EdgePrediction, RFDETRInferenceError))
            else EdgePrediction(edge_mask=value, source="rfdetr", instances=())
            for value in values
        ]

    predictions, fallback_reasons = predict_automatic_edge_predictions(
        inputs,
        backend,
        rfdetr_photo_values,
        structured_rfdetr_predictor,
        h5_predictor,
    )
    masks = {photo: prediction.edge_mask for photo, prediction in predictions.items()}
    sources = {photo: prediction.source for photo, prediction in predictions.items()}
    fallback_error = None
    if fallback_reasons:
        details = "; ".join(
            f"{photo}: {reason}" for photo, reason in fallback_reasons.items()
        )
        fallback_error = RFDETRInferenceError(details)
    return masks, sources, fallback_error

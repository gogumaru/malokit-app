"""Pure ARKit RGB/depth mapping and K0-reference geometry helpers."""

from __future__ import annotations

import math
from typing import Sequence, Tuple


_CG_ORIENTATION_PREFIX = "CGImagePropertyOrientation."


def _positive_finite(value: float, label: str) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be finite and positive.")
    return value


def _finite(value: float, label: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite.")
    return value


def map_rgb_pixel_to_depth(
    x: int,
    y: int,
    rgb_width: int,
    rgb_height: int,
    depth_width: int,
    depth_height: int,
) -> Tuple[int, int]:
    """Map one RGB pixel to its nearest depth pixel with pixel-centre scaling."""

    rgb_width = int(_positive_finite(rgb_width, "rgb_width"))
    rgb_height = int(_positive_finite(rgb_height, "rgb_height"))
    depth_width = int(_positive_finite(depth_width, "depth_width"))
    depth_height = int(_positive_finite(depth_height, "depth_height"))
    if not (0 <= x < rgb_width and 0 <= y < rgb_height):
        raise ValueError("RGB pixel is outside the image bounds.")

    depth_x = min(depth_width - 1, int((x + 0.5) * depth_width / rgb_width))
    depth_y = min(depth_height - 1, int((y + 0.5) * depth_height / rgb_height))
    return depth_x, depth_y


def map_cropped_rgb_pixel_to_depth(
    x: int,
    y: int,
    rgb_width: int,
    rgb_height: int,
    intrinsic_reference_width: int,
    intrinsic_reference_height: int,
    depth_width: int,
    depth_height: int,
    rgb_crop: dict,
    orientation: str,
) -> Tuple[int, int]:
    """Map an upright cropped RGB pixel into ARKit's native depth coordinates."""

    rgb_width = int(_positive_finite(rgb_width, "rgb_width"))
    rgb_height = int(_positive_finite(rgb_height, "rgb_height"))
    reference_width = int(_positive_finite(intrinsic_reference_width, "intrinsic_reference_width"))
    reference_height = int(_positive_finite(intrinsic_reference_height, "intrinsic_reference_height"))
    if not (0 <= int(x) < rgb_width and 0 <= int(y) < rgb_height):
        raise ValueError("RGB pixel is outside the image bounds.")
    if not isinstance(rgb_crop, dict):
        raise ValueError("rgbCrop must be an object.")
    try:
        original_width = int(rgb_crop["originalWidth"])
        original_height = int(rgb_crop["originalHeight"])
        crop_x = int(rgb_crop["x"])
        crop_y = int(rgb_crop["y"])
        crop_width = int(rgb_crop["width"])
        crop_height = int(rgb_crop["height"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("rgbCrop is malformed.") from error
    if (
        original_width <= 0
        or original_height <= 0
        or crop_width <= 0
        or crop_height <= 0
        or crop_x < 0
        or crop_y < 0
        or crop_x + crop_width > original_width
        or crop_y + crop_height > original_height
    ):
        raise ValueError("rgbCrop is outside the oriented source image.")
    if not isinstance(orientation, str) or not orientation.startswith(_CG_ORIENTATION_PREFIX):
        raise ValueError("orientation is missing or malformed.")
    try:
        orientation_value = int(orientation[len(_CG_ORIENTATION_PREFIX):])
    except ValueError as error:
        raise ValueError("orientation is missing or malformed.") from error
    if orientation_value not in range(1, 9):
        raise ValueError("orientation is unsupported.")

    oriented_x = crop_x + (float(x) + 0.5) * crop_width / rgb_width
    oriented_y = crop_y + (float(y) + 0.5) * crop_height / rgb_height
    if orientation_value == 1:  # up
        native_x, native_y = oriented_x, oriented_y
        expected_size = (reference_width, reference_height)
    elif orientation_value == 2:  # up mirrored
        native_x, native_y = original_width - oriented_x, oriented_y
        expected_size = (reference_width, reference_height)
    elif orientation_value == 3:  # down
        native_x, native_y = original_width - oriented_x, original_height - oriented_y
        expected_size = (reference_width, reference_height)
    elif orientation_value == 4:  # down mirrored
        native_x, native_y = oriented_x, original_height - oriented_y
        expected_size = (reference_width, reference_height)
    elif orientation_value == 5:  # left mirrored / transpose
        native_x, native_y = oriented_y, oriented_x
        expected_size = (reference_height, reference_width)
    elif orientation_value == 6:  # right (90 degrees clockwise)
        native_x, native_y = oriented_y, original_width - oriented_x
        expected_size = (reference_height, reference_width)
    elif orientation_value == 7:  # right mirrored / transverse
        native_x, native_y = original_height - oriented_y, original_width - oriented_x
        expected_size = (reference_height, reference_width)
    else:  # left (90 degrees counter-clockwise)
        native_x, native_y = original_height - oriented_y, oriented_x
        expected_size = (reference_height, reference_width)
    if (original_width, original_height) != expected_size:
        raise ValueError("rgbCrop source dimensions do not match the ARKit reference orientation.")
    depth_x = min(
        int(depth_width) - 1,
        max(0, int(native_x * int(depth_width) / reference_width)),
    )
    depth_y = min(
        int(depth_height) - 1,
        max(0, int(native_y * int(depth_height) / reference_height)),
    )
    return depth_x, depth_y


def _intrinsics(intrinsic_matrix: Sequence[float]) -> Tuple[float, float, float, float]:
    if len(intrinsic_matrix) == 3 and all(
        isinstance(row, Sequence) and len(row) == 3 for row in intrinsic_matrix
    ):
        values = [value for column in intrinsic_matrix for value in column]
    else:
        values = list(intrinsic_matrix)
    if len(values) != 9:
        raise ValueError("intrinsic_matrix must contain 9 column-major values.")
    values = [_finite(value, "intrinsic_matrix value") for value in values]
    fx, fy, cx, cy = values[0], values[4], values[6], values[7]
    if fx <= 0 or fy <= 0:
        raise ValueError("intrinsic focal lengths must be positive.")
    return fx, fy, cx, cy


def back_project_depth_pixel(
    x: int,
    y: int,
    depth_metres: float,
    intrinsic_matrix: Sequence[float],
    rgb_reference_size: Tuple[int, int],
    depth_size: Tuple[int, int],
) -> Tuple[float, float, float]:
    """Back-project a depth cell using ARKit's right/down/forward camera axes.

    The returned point uses ARKit world-compatible camera coordinates: +X right,
    +Y up, and -Z forward.
    """

    rgb_width = _positive_finite(rgb_reference_size[0], "rgb_reference_width")
    rgb_height = _positive_finite(rgb_reference_size[1], "rgb_reference_height")
    depth_width = int(_positive_finite(depth_size[0], "depth_width"))
    depth_height = int(_positive_finite(depth_size[1], "depth_height"))
    if not (0 <= x < depth_width and 0 <= y < depth_height):
        raise ValueError("Depth pixel is outside the image bounds.")
    depth_metres = _positive_finite(depth_metres, "depth_metres")
    fx, fy, cx, cy = _intrinsics(intrinsic_matrix)
    scale_x = depth_width / rgb_width
    scale_y = depth_height / rgb_height
    scaled_fx, scaled_fy = fx * scale_x, fy * scale_y
    scaled_cx, scaled_cy = cx * scale_x, cy * scale_y
    return (
        (float(x) - scaled_cx) * depth_metres / scaled_fx,
        -(float(y) - scaled_cy) * depth_metres / scaled_fy,
        -depth_metres,
    )


def transform_point_to_reference(
    point_xyz: Sequence[float], camera_to_reference_column_major: Sequence[float]
) -> Tuple[float, float, float]:
    """Apply a finite column-major 4×4 camera-to-K0 transform."""

    if len(point_xyz) != 3:
        raise ValueError("point_xyz must contain exactly three values.")
    if len(camera_to_reference_column_major) != 16:
        raise ValueError("camera-to-reference transform must contain 16 values.")
    x, y, z = (_finite(value, "point coordinate") for value in point_xyz)
    matrix = [_finite(value, "camera-to-reference transform value") for value in camera_to_reference_column_major]
    transformed_x = matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12]
    transformed_y = matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13]
    transformed_z = matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14]
    transformed_w = matrix[3] * x + matrix[7] * y + matrix[11] * z + matrix[15]
    if not math.isfinite(transformed_w) or abs(transformed_w) < 1e-8:
        raise ValueError("camera-to-reference transform has an invalid homogeneous value.")
    return (
        transformed_x / transformed_w,
        transformed_y / transformed_w,
        transformed_z / transformed_w,
    )

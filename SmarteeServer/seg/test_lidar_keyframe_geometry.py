import unittest

from seg.lidar_keyframe_geometry import (
    back_project_depth_pixel,
    map_cropped_rgb_pixel_to_depth,
    map_rgb_pixel_to_depth,
    transform_point_to_reference,
)


class LiDARKeyframeGeometryTests(unittest.TestCase):
    def test_maps_rgb_centre_to_depth_cell_using_pixel_centres(self):
        self.assertEqual(map_rgb_pixel_to_depth(2, 1, 4, 2, 2, 1), (1, 0))

    def test_maps_right_oriented_crop_back_to_arkit_camera_pixel_before_depth(self):
        crop = {
            "originalWidth": 6,
            "originalHeight": 8,
            "x": 1,
            "y": 2,
            "width": 3,
            "height": 2,
        }

        self.assertEqual(
            map_cropped_rgb_pixel_to_depth(
                0, 0, 3, 2, 8, 6, 8, 6, crop, "CGImagePropertyOrientation.6"
            ),
            (2, 4),
        )

    def test_crop_mapping_scales_saved_rgb_when_dimensions_differ_from_crop(self):
        crop = {
            "originalWidth": 8,
            "originalHeight": 6,
            "x": 2,
            "y": 1,
            "width": 4,
            "height": 2,
        }

        self.assertEqual(
            map_cropped_rgb_pixel_to_depth(
                1, 0, 2, 1, 8, 6, 4, 3, crop, "CGImagePropertyOrientation.1"
            ),
            (2, 1),
        )

    def test_crop_mapping_rejects_mismatched_or_unrecognized_orientation_metadata(self):
        crop = {
            "originalWidth": 6,
            "originalHeight": 8,
            "x": 1,
            "y": 2,
            "width": 3,
            "height": 2,
        }

        with self.assertRaises(ValueError):
            map_cropped_rgb_pixel_to_depth(
                0, 0, 3, 2, 7, 6, 8, 6, crop, "CGImagePropertyOrientation.6"
            )
        with self.assertRaises(ValueError):
            map_cropped_rgb_pixel_to_depth(
                0, 0, 3, 2, 8, 6, 8, 6, crop, "CGImagePropertyOrientation.99"
            )

    def test_back_projects_depth_centre_with_arkit_camera_axes(self):
        point = back_project_depth_pixel(
            1,
            0,
            1.0,
            [4.0, 0.0, 0.0, 0.0, 2.0, 0.0, 2.0, 0.0, 1.0],
            (4, 2),
            (2, 1),
        )
        self.assertEqual(point, (0.0, 0.0, -1.0))

    def test_applies_column_major_camera_to_reference_translation(self):
        point = transform_point_to_reference(
            (0.0, 0.0, -1.0),
            [
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.01, 0.0, 0.0, 1.0,
            ],
        )
        self.assertEqual(point, (0.01, 0.0, -1.0))


if __name__ == "__main__":
    unittest.main()

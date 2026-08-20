import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from patient_texture import (
    _load_resized_photos,
    build_texture_atlas,
    fill_unobserved_colors,
    patient_enamel_color,
    project_vertices,
    write_colored_obj,
)


class PatientTextureTests(unittest.TestCase):
    def test_photo_source_tag_can_differ_from_output_mesh_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            for index in range(5):
                path = os.path.join(directory, f"source-{index}.png")
                from skimage.io import imsave

                imsave(path, np.full((2, 3, 3), 128, dtype=np.uint8), check_contrast=False)
            with patch("patient_texture.PHOTO_DIR", directory):
                photos = _load_resized_photos("output", source_tag="source")

        self.assertEqual(len(photos), 5)

    def test_projects_vertices_with_persisted_camera_parameters(self):
        vertices = np.array([[0.0, 0.0, 2.0], [2.0, 0.0, 2.0]])
        uv, depth = project_vertices(
            vertices,
            rotation_vector=np.zeros(3),
            translation=np.zeros(3),
            focal_pixels=10.0,
            principal_point=(5.0, 4.0),
        )
        np.testing.assert_allclose(uv, [[5.0, 4.0], [15.0, 4.0]])
        np.testing.assert_allclose(depth, [2.0, 2.0])

    def test_patient_palette_ignores_gum_red_and_dark_background(self):
        samples = np.array(
            [
                [0.82, 0.76, 0.62],
                [0.88, 0.83, 0.70],
                [0.75, 0.18, 0.20],
                [0.03, 0.03, 0.03],
            ]
        )
        weights = np.ones(4)
        color = patient_enamel_color(samples, weights)
        self.assertGreater(color[0], 0.78)
        self.assertGreater(color[1], 0.70)
        self.assertGreater(color[2], 0.58)

    def test_unobserved_vertices_receive_nearby_patient_enamel(self):
        vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
        colors = np.array([[0.9, 0.8, 0.65], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
        observed = np.array([True, False, False])
        result = fill_unobserved_colors(vertices, colors, observed)
        self.assertTrue(np.all(result > 0.45))
        self.assertGreater(result[1, 0], result[1, 2])
        self.assertGreater(result[2, 0], result[2, 2])

    def test_colored_obj_preserves_faces_and_writes_rgb(self):
        original = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
        colors = np.array([[1.0, 0.5, 0.25], [0.8, 0.7, 0.6], [0.4, 0.3, 0.2]])
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "mesh.obj")
            with open(path, "w", encoding="utf-8") as file:
                file.write(original)
            write_colored_obj(path, colors)
            with open(path, "r", encoding="utf-8") as file:
                result = file.read()
        self.assertIn("v 0 0 0 1.000000 0.500000 0.250000", result)
        self.assertIn("f 1 2 3", result)

    def test_texture_atlas_writes_uv_obj_and_png(self):
        vertices = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]], dtype=np.float32)
        faces = np.array([[0, 1, 2]], dtype=np.uint32)
        colors = np.array([[1., .8, .6], [.8, .7, .5], [.7, .6, .4]])
        with tempfile.TemporaryDirectory() as directory:
            obj_path = os.path.join(directory, "mesh.obj")
            png_path = os.path.join(directory, "texture.png")
            build_texture_atlas(vertices, faces, colors, obj_path, png_path, size=64)
            with open(obj_path, encoding="utf-8") as file:
                obj = file.read()
            self.assertTrue(os.path.exists(png_path))
            self.assertIn("vt ", obj)
            self.assertIn("f 1/1 2/2 3/3", obj)


if __name__ == "__main__":
    unittest.main()

import io
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import skimage.io
import h5py
import server
from seg.prediction_types import EdgePrediction, ToothInstancePrediction


class LiDARUploadTests(unittest.TestCase):
    def metadata(self, width=3, height=2, eligible=True):
        return {
            "schemaVersion": 1,
            "depthWidth": width,
            "depthHeight": height,
            "bytesPerSample": 4,
            "units": "metres",
            "validFraction": 1.0,
            "ssmDepthEligible": eligible,
        }

    def test_saves_valid_float32_bundle(self):
        metadata = self.metadata()
        depth = struct.pack("<6f", 0.2, 0.21, 0.22, 0.23, 0.24, 0.25)

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            server, "LIDAR_DIR", temp_dir
        ):
            with server.app.test_request_context(
                "/reconstruct",
                method="POST",
                data={
                    "frontDepth": (io.BytesIO(depth), "front.depth.f32"),
                    "frontDepthMetadata": (
                        io.BytesIO(json.dumps(metadata).encode("utf-8")),
                        "front.depth.json",
                    ),
                },
                content_type="multipart/form-data",
            ):
                result = server.save_lidar_capture_bundles("capture-test")

            self.assertEqual(result["front"]["depthWidth"], 3)
            self.assertTrue(result["front"]["ssmDepthEligible"])
            output = os.path.join(temp_dir, "capture-test")
            with open(os.path.join(output, "front.depth.f32"), "rb") as file:
                self.assertEqual(file.read(), depth)

    def test_rejects_depth_size_mismatch(self):
        metadata = self.metadata(width=3, height=2)
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            server, "LIDAR_DIR", temp_dir
        ):
            with server.app.test_request_context(
                "/reconstruct",
                method="POST",
                data={
                    "frontDepth": (io.BytesIO(b"too short"), "front.depth.f32"),
                    "frontDepthMetadata": (
                        io.BytesIO(json.dumps(metadata).encode("utf-8")),
                        "front.depth.json",
                    ),
                },
                content_type="multipart/form-data",
            ):
                with self.assertRaisesRegex(ValueError, "size mismatch"):
                    server.save_lidar_capture_bundles("capture-test")


class Figure8KeyframeUploadTests(unittest.TestCase):
    keyframe_ids = [f"K{index}" for index in range(7)]

    def metadata(self, keyframe_id, direct=True, confidence=True):
        return {
            "schemaVersion": 4,
            "depthWidth": 2,
            "depthHeight": 1,
            "bytesPerSample": 4,
            "units": "metres",
            "matrixLayout": "column-major",
            "coordinateSystem": "ARKit camera-to-world",
            "cameraToReferenceTransform": [1, 0, 0, 0] * 4,
            "figure8KeyframeID": keyframe_id,
            "figure8State": "idle",
            "isDirectView": direct,
            "orientation": "CGImagePropertyOrientation.1",
            "trackingState": "normal",
            "ssmDepthEligible": direct,
            "validFraction": 1.0,
        }

    def request_data(self, manifest_ids=None):
        ids = self.keyframe_ids if manifest_ids is None else manifest_ids
        data = {
            "frontFigure8Manifest": (
                io.BytesIO(json.dumps({"schemaVersion": 1, "keyframes": [{"id": keyframe_id} for keyframe_id in ids]}).encode("utf-8")),
                "front.figure8.json",
            )
        }
        for keyframe_id in ids:
            data[f"frontFigure8{keyframe_id}RGB"] = (
                io.BytesIO(b"\x89PNG"), f"{keyframe_id}.rgb.png"
            )
            data[f"frontFigure8{keyframe_id}Depth"] = (
                io.BytesIO(struct.pack("<2f", 0.2, 0.3)), f"{keyframe_id}.depth.f32"
            )
            data[f"frontFigure8{keyframe_id}Confidence"] = (
                io.BytesIO(bytes([2, 1])), f"{keyframe_id}.confidence.u8"
            )
            data[f"frontFigure8{keyframe_id}Metadata"] = (
                io.BytesIO(json.dumps(self.metadata(keyframe_id)).encode("utf-8")),
                f"{keyframe_id}.metadata.json",
            )
        return data

    def test_saves_complete_keyframes_separately_without_binary_response_data(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            server, "LIDAR_DIR", temp_dir
        ):
            with server.app.test_request_context(
                "/reconstruct",
                method="POST",
                data=self.request_data(),
                content_type="multipart/form-data",
            ):
                summary = server.save_figure8_keyframe_bundles("capture-test")

            output = os.path.join(temp_dir, "capture-test", "front")
            for name in ("K0.rgb.png", "K0.depth.f32", "K0.confidence.u8", "K0.metadata.json", "figure8_manifest.json"):
                self.assertTrue(os.path.exists(os.path.join(output, name)), name)
            self.assertEqual(summary["front"]["keyframeCount"], 7)
            response_text = json.dumps(summary)
            self.assertNotIn("rgb", response_text.lower())
            self.assertNotIn("depth", response_text.lower())
            self.assertNotIn("confidence", response_text.lower())

    def test_rejects_missing_keyframe_companion_file(self):
        data = self.request_data()
        del data["frontFigure8K1Confidence"]
        with server.app.test_request_context(
            "/reconstruct", method="POST", data=data, content_type="multipart/form-data"
        ):
            with self.assertRaisesRegex(ValueError, "K1.*confidence"):
                server.save_figure8_keyframe_bundles("capture-test")

    def test_rejects_malformed_or_non_direct_keyframes(self):
        malformed = self.request_data()
        malformed["frontFigure8K2Confidence"] = (io.BytesIO(bytes([2])), "K2.confidence.u8")
        with server.app.test_request_context(
            "/reconstruct", method="POST", data=malformed, content_type="multipart/form-data"
        ):
            with self.assertRaisesRegex(ValueError, "K2.*confidence"):
                server.save_figure8_keyframe_bundles("capture-test")

        mirror = self.request_data()
        mirror["frontFigure8K3Metadata"] = (
            io.BytesIO(json.dumps(self.metadata("K3", direct=False)).encode("utf-8")),
            "K3.metadata.json",
        )
        with server.app.test_request_context(
            "/reconstruct", method="POST", data=mirror, content_type="multipart/form-data"
        ):
            with self.assertRaisesRegex(ValueError, "K3.*direct"):
                server.save_figure8_keyframe_bundles("capture-test")

    def test_rejects_unknown_or_unordered_manifest_ids(self):
        unknown = self.request_data(self.keyframe_ids[:-1] + ["K7"])
        with server.app.test_request_context(
            "/reconstruct", method="POST", data=unknown, content_type="multipart/form-data"
        ):
            with self.assertRaisesRegex(ValueError, "unknown.*K7"):
                server.save_figure8_keyframe_bundles("capture-test")

        unordered = self.request_data(["K1", "K0", "K2", "K3", "K4", "K5", "K6"])
        with server.app.test_request_context(
            "/reconstruct", method="POST", data=unordered, content_type="multipart/form-data"
        ):
            with self.assertRaisesRegex(ValueError, "K0.*first"):
                server.save_figure8_keyframe_bundles("capture-test")


class DentalCloudSummaryTests(unittest.TestCase):
    def test_optimizer_summary_reads_final_m5_m6_m7_diagnostics(self):
        payload = {
            "schemaVersion": 1,
            "coarse": {
                "enabled": True,
                "accepted": False,
                "inputEligible": True,
                "fallbackApplied": True,
                "reason": "coarse_surface_distance_not_improved",
                "pairCounts": {"front": 120},
                "photoContourLossBefore": 1256.4876,
                "photoContourLossAfter": 1091.3952,
                "correspondenceAlignment": {"front": {"translationMetres": [1, 2, 3]}},
            },
            "toothPose": {
                "enabled": True,
                "pairCounts": {"U-03@front": 31},
                "poseDeltaNorms": {
                    "U-03": {"translationMillimetres": 1.2, "rotationRadians": 0.01}
                },
                "scaleParameterDeltaFromM6Loss": 0.0,
                "correspondenceAlignment": {"U-03@front": {"translationMetres": [1, 2, 3]}},
            },
            "toothShape": {"enabled": False, "reason": "fewer_than_two_fields_with_m6_pairs"},
        }
        with tempfile.TemporaryDirectory() as root, patch.object(
            server, "LIDAR_DIAGNOSTIC_DIR", root
        ):
            Path(root, "tag.json").write_text(json.dumps(payload), encoding="utf-8")

            summary = server.load_lidar_optimization_diagnostic_summary("tag")

        self.assertEqual(summary["coarse"]["pairCounts"]["front"], 120)
        self.assertFalse(summary["coarse"]["accepted"])
        self.assertTrue(summary["coarse"]["fallbackApplied"])
        self.assertEqual(summary["coarse"]["photoContourLossAfter"], 1091.3952)
        self.assertEqual(summary["toothPose"]["pairCounts"]["U-03@front"], 31)
        self.assertEqual(
            summary["toothPose"]["poseDeltaNorms"]["U-03"]["translationMillimetres"],
            1.2,
        )
        self.assertEqual(summary["toothShape"]["reason"], "fewer_than_two_fields_with_m6_pairs")
        self.assertNotIn("translationMetres", json.dumps(summary))

    def test_m7_summary_reads_only_safe_scalar_diagnostics(self):
        diagnostic = {
            "enabled": True,
            "weight": 0.002,
            "eligibleSlots": {
                "U-03": {
                    "fields": ["front", "leftLateral"],
                    "pairCounts": {"front": 31, "leftLateral": 42},
                }
            },
            "lastLossMetresSquared": 0.000001,
            "featureVectorDeltaNorms": {"U-03": 0.15},
            "points": [[1, 2, 3]],
        }
        with tempfile.TemporaryDirectory() as root, patch.object(
            server, "RECONSTRUCTION_DATA_DIR", root
        ):
            path = os.path.join(root, "demo-tag=test-tag.h5")
            with h5py.File(path, "w") as file:
                group = file.create_group("EMOPT")
                group.attrs["LIDAR_TOOTH_SHAPE_CONSTRAINTS_JSON"] = json.dumps(
                    diagnostic
                )

            summary = server.load_lidar_tooth_shape_constraint_summary("test-tag")

        self.assertTrue(summary["eligible"])
        self.assertEqual(summary["eligibleSlots"]["U-03"]["pairCounts"]["front"], 31)
        self.assertEqual(summary["featureVectorDeltaNorms"]["U-03"], 0.15)
        self.assertNotIn("points", json.dumps(summary))

    def test_m7_summary_reports_missing_diagnostics_without_failing_response(self):
        with tempfile.TemporaryDirectory() as root, patch.object(
            server, "RECONSTRUCTION_DATA_DIR", root
        ):
            summary = server.load_lidar_tooth_shape_constraint_summary("missing")

        self.assertFalse(summary["eligible"])
        self.assertEqual(summary["reason"], "reconstruction_diagnostics_missing")

    def test_tooth_pose_summary_exposes_counts_not_patient_points(self):
        constraint = type("Constraint", (), {
            "slot_id": "U-03", "field": "front", "photo_index": 4,
            "contributing_keyframes": ("K0", "K2", "K5"),
            "points_k0_metres": np.zeros((30, 3)),
        })()

        summary = server.lidar_tooth_pose_constraint_response_summary({2: (constraint,)}, {"U-04": "insufficient_distinct_fields"})

        self.assertTrue(summary["eligible"])
        self.assertEqual(summary["eligibleSlots"]["U-03"]["pointCount"], 30)
        self.assertNotIn("points_k0_metres", json.dumps(summary))

    def test_response_summary_has_coverage_not_points_or_binary_data(self):
        summary = server.dental_cloud_response_summary(
            {
                "front": {
                    "pointCount": 12,
                    "voxelSizeMetres": 0.002,
                    "perKeyframe": {"K0": {"acceptedPointCount": 4, "instanceCount": 2}},
                    "rejectionCounts": {"mask_edge_eroded": 9},
                    "points": [{"pointK0": [0, 0, -1]}],
                }
            }
        )

        self.assertEqual(summary["front"]["pointCount"], 12)
        self.assertEqual(summary["front"]["perKeyframe"]["K0"]["instanceCount"], 2)
        response_text = json.dumps(summary)
        self.assertNotIn("pointK0", response_text)
        self.assertNotIn("png", response_text.lower())
        self.assertNotIn("depth.f32", response_text.lower())

    def test_processes_complete_direct_bundle_into_diagnostic_cloud(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(server, "LIDAR_DIR", temp_dir):
            root = Path(temp_dir) / "capture-test" / "front"
            root.mkdir(parents=True)
            for keyframe_id in server.FIGURE8_KEYFRAME_IDS:
                skimage.io.imsave(
                    str(root / f"{keyframe_id}.rgb.png"),
                    np.zeros((5, 5, 3), dtype=np.uint8),
                    check_contrast=False,
                )
                (root / f"{keyframe_id}.depth.f32").write_bytes(np.ones((5, 5), dtype="<f4").tobytes())
                (root / f"{keyframe_id}.confidence.u8").write_bytes(bytes([2]) * 25)
                (root / f"{keyframe_id}.metadata.json").write_text(json.dumps({
                    "schemaVersion": 4, "depthWidth": 5, "depthHeight": 5,
                    "bytesPerSample": 4, "isDirectView": True, "ssmDepthEligible": True,
                    "trackingState": "normal", "matrixLayout": "column-major",
                    "coordinateSystem": "ARKit camera-to-world",
                    "intrinsicMatrix": [5, 0, 0, 0, 5, 0, 2, 2, 1],
                    "intrinsicReferenceWidth": 5, "intrinsicReferenceHeight": 5,
                    "cameraToReferenceTransform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
                }))
            (root / "figure8_manifest.json").write_text(json.dumps({
                "schemaVersion": 1,
                "keyframes": [{"id": keyframe_id} for keyframe_id in server.FIGURE8_KEYFRAME_IDS],
            }))
            mask = np.zeros((5, 5), dtype=np.uint8)
            mask[1:4, 1:4] = 255
            instance = ToothInstancePrediction("tooth-1", mask, 0.9, (1, 1, 3, 3), (2, 2), 9)

            result = server.process_lidar_dental_cloud(
                "capture-test",
                predictor=lambda paths: [EdgePrediction(mask, "rfdetr", (instance,)) for _ in paths],
            )

            self.assertEqual(result["front"]["keyframeCount"], 7)
            self.assertEqual(result["front"]["pointCount"], 1)
            self.assertTrue((root / "dental_cloud.json").is_file())

    def test_process_attaches_the_keyframe_slot_to_cloud_points(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(server, "LIDAR_DIR", temp_dir):
            root = Path(temp_dir) / "capture-test" / "mandibular"
            root.mkdir(parents=True)
            for keyframe_id in server.FIGURE8_KEYFRAME_IDS:
                skimage.io.imsave(str(root / f"{keyframe_id}.rgb.png"), np.zeros((5, 5, 3), dtype=np.uint8), check_contrast=False)
                (root / f"{keyframe_id}.depth.f32").write_bytes(np.ones((5, 5), dtype="<f4").tobytes())
                (root / f"{keyframe_id}.confidence.u8").write_bytes(bytes([2]) * 25)
                (root / f"{keyframe_id}.metadata.json").write_text(json.dumps({
                    "schemaVersion": 4, "depthWidth": 5, "depthHeight": 5, "bytesPerSample": 4,
                    "isDirectView": True, "ssmDepthEligible": True, "trackingState": "normal",
                    "matrixLayout": "column-major", "coordinateSystem": "ARKit camera-to-world",
                    "intrinsicMatrix": [5, 0, 0, 0, 5, 0, 2, 2, 1],
                    "intrinsicReferenceWidth": 5, "intrinsicReferenceHeight": 5,
                    "cameraToReferenceTransform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
                }))
            (root / "figure8_manifest.json").write_text(json.dumps({"schemaVersion": 1, "keyframes": [{"id": keyframe_id} for keyframe_id in server.FIGURE8_KEYFRAME_IDS]}))
            mask = np.zeros((5, 5), dtype=np.uint8)
            mask[1:4, 1:4] = 255
            instances = tuple(
                ToothInstancePrediction(f"tooth-{index:02d}", mask, 0.9, (1, 1, 3, 3), ((index - 0.5) * 5 / 14, 2), 9)
                for index in range(1, 15)
            )

            server.process_lidar_dental_cloud(
                "capture-test",
                predictor=lambda paths: [EdgePrediction(mask, "rfdetr", instances) for _ in paths],
            )

            cloud = json.loads((root / "dental_cloud.json").read_text())
            self.assertEqual(cloud["points"][0]["slotID"], "L-01")

    def test_k0_row_split_rejection_reason_survives_the_diagnostics_merge(self):
        # propagate_k0_slots only produces a diagnostic for K0 instances that
        # already reached assign_keyframe_slots' k0_assignments (i.e. were
        # assigned a slot). With too few detections, assign_keyframe_slots
        # rejects everything outright as "ambiguous_arch_rows" before that —
        # the persisted slot_assignments.json must still show that real
        # reason, not silently blank it to {}.
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(server, "LIDAR_DIR", temp_dir):
            # "front" (not mandibular/maxillary) is required to exercise the
            # upper/lower row-split path at all — mandibular/maxillary only
            # ever see one arch and skip straight to per-row DP alignment.
            root = Path(temp_dir) / "capture-test" / "front"
            root.mkdir(parents=True)
            for keyframe_id in server.FIGURE8_KEYFRAME_IDS:
                skimage.io.imsave(str(root / f"{keyframe_id}.rgb.png"), np.zeros((5, 5, 3), dtype=np.uint8), check_contrast=False)
                (root / f"{keyframe_id}.depth.f32").write_bytes(np.ones((5, 5), dtype="<f4").tobytes())
                (root / f"{keyframe_id}.confidence.u8").write_bytes(bytes([2]) * 25)
                (root / f"{keyframe_id}.metadata.json").write_text(json.dumps({
                    "schemaVersion": 4, "depthWidth": 5, "depthHeight": 5, "bytesPerSample": 4,
                    "isDirectView": True, "ssmDepthEligible": True, "trackingState": "normal",
                    "matrixLayout": "column-major", "coordinateSystem": "ARKit camera-to-world",
                    "intrinsicMatrix": [5, 0, 0, 0, 5, 0, 2, 2, 1],
                    "intrinsicReferenceWidth": 5, "intrinsicReferenceHeight": 5,
                    "cameraToReferenceTransform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
                }))
            (root / "figure8_manifest.json").write_text(json.dumps({"schemaVersion": 1, "keyframes": [{"id": keyframe_id} for keyframe_id in server.FIGURE8_KEYFRAME_IDS]}))
            mask = np.zeros((5, 5), dtype=np.uint8)
            mask[1:4, 1:4] = 255
            # Only 2 instances: below assign_keyframe_slots' 4-instance
            # minimum for a row split, so every instance is rejected as
            # "ambiguous_arch_rows" and none ever reach k0_assignments.
            instances = (
                ToothInstancePrediction("tooth-a", mask, 0.9, (1, 1, 3, 3), (2, 2), 9),
                ToothInstancePrediction("tooth-b", mask, 0.9, (1, 1, 3, 3), (2, 3), 9),
            )

            server.process_lidar_dental_cloud(
                "capture-test",
                predictor=lambda paths: [EdgePrediction(mask, "rfdetr", instances) for _ in paths],
            )

            slot_assignments = json.loads((root / "segmentation" / "slot_assignments.json").read_text())
            k0_rejections = slot_assignments["keyframes"]["K0"]["rejections"]
            self.assertEqual(set(k0_rejections.values()), {"ambiguous_arch_rows"})


class ReconstructionModelSelectionTests(unittest.TestCase):
    def test_baseline_only_selects_ten_pc_model(self):
        with server.app.test_request_context(
            "/reconstruct",
            method="POST",
            data={"modelMode": "baseline-only"},
        ):
            selected = server.selected_reconstruction_models()

        self.assertEqual([model["num_pc"] for model in selected], [10])
        self.assertEqual(selected[0]["shape_regularization"], 1.0)

    def test_default_request_preserves_configured_models(self):
        with server.app.test_request_context("/reconstruct", method="POST"):
            selected = server.selected_reconstruction_models()

        self.assertEqual(selected, server.COMPARISON_MODELS)


class EngineWiringTests(unittest.TestCase):
    """Take 5 Pictures (baseline-only) must always run the 'lidar' engine
    (emopt5views_lidar.py); Upload 5 Photos (comparison) must always run
    'baseline' (emopt5views.py) — never the other way around, and never both
    reachable from the same request mode."""

    def test_capture_models_are_lidar_engine_only(self):
        self.assertTrue(server.CAPTURE_MODELS)
        for model in server.CAPTURE_MODELS:
            self.assertEqual(model["engine"], "lidar")

    def test_comparison_models_are_baseline_engine_only(self):
        self.assertTrue(server.COMPARISON_MODELS)
        for model in server.COMPARISON_MODELS:
            self.assertEqual(model["engine"], "baseline")

    def test_model_lists_do_not_overlap(self):
        capture_ids = {model["id"] for model in server.CAPTURE_MODELS}
        comparison_ids = {model["id"] for model in server.COMPARISON_MODELS}
        self.assertEqual(capture_ids & comparison_ids, set())

    def test_run_reconstruction_passes_engine_flag_to_subprocess(self):
        fake_result = unittest.mock.Mock(returncode=0)
        with patch.object(server.subprocess, "run", return_value=fake_result) as mock_run, \
             patch.object(server.os.path, "exists", return_value=True):
            server.run_reconstruction("tag123", engine="lidar")

        command = mock_run.call_args[0][0]
        self.assertIn("--engine", command)
        self.assertEqual(command[command.index("--engine") + 1], "lidar")

    def test_lidar_reconstruction_passes_capture_tag_but_baseline_does_not(self):
        fake_result = unittest.mock.Mock(returncode=0)
        with patch.object(server.subprocess, "run", return_value=fake_result) as mock_run, \
             patch.object(server.os.path, "exists", return_value=True):
            server.run_reconstruction("lidar-tag", engine="lidar", lidar_capture_tag="capture-tag")
            lidar_command = mock_run.call_args[0][0]
            server.run_reconstruction("baseline-tag", engine="baseline", lidar_capture_tag="capture-tag")
            baseline_command = mock_run.call_args[0][0]

        self.assertEqual(lidar_command[lidar_command.index("--lidar-capture-tag") + 1], "capture-tag")
        self.assertNotIn("--lidar-capture-tag", baseline_command)

    def test_run_reconstruction_defaults_to_baseline_engine(self):
        fake_result = unittest.mock.Mock(returncode=0)
        with patch.object(server.subprocess, "run", return_value=fake_result) as mock_run, \
             patch.object(server.os.path, "exists", return_value=True):
            server.run_reconstruction("tag123")

        command = mock_run.call_args[0][0]
        self.assertEqual(command[command.index("--engine") + 1], "baseline")

    def test_run_reconstruction_rejects_stale_preexisting_meshes(self):
        fake_result = unittest.mock.Mock(returncode=0, stderr="")
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "tag123"
            output.mkdir()
            (output / "Pred_Upper_Mesh_Tag=tag123.obj").write_text("stale upper")
            (output / "Pred_Lower_Mesh_Tag=tag123.obj").write_text("stale lower")
            with patch.object(server, "MESH_DIR", root), patch.object(
                server, "MAX_ATTEMPTS", 1
            ), patch.object(server.subprocess, "run", return_value=fake_result):
                with self.assertRaisesRegex(RuntimeError, "wrote no fresh mesh"):
                    server.run_reconstruction("tag123")


class EdgeBackendSelectionTests(unittest.TestCase):
    def test_take_five_uses_rfdetr_first(self):
        with server.app.test_request_context(
            "/reconstruct", method="POST", data={"modelMode": "baseline-only"}
        ):
            self.assertEqual(server.selected_edge_backend(), "rfdetr")

    def test_upload_preserves_configured_server_backend(self):
        with patch.object(server, "EDGE_BACKEND", "h5"):
            with server.app.test_request_context("/reconstruct", method="POST"):
                self.assertEqual(server.selected_edge_backend(), "h5")
        with patch.object(server, "EDGE_BACKEND", "rfdetr"):
            with server.app.test_request_context("/reconstruct", method="POST"):
                self.assertEqual(server.selected_edge_backend(), "rfdetr")

    def test_run_reconstruction_passes_explicit_edge_backend(self):
        fake_result = unittest.mock.Mock(returncode=0)
        with patch.object(server.subprocess, "run", return_value=fake_result) as run, patch.object(
            server.os.path, "exists", return_value=True
        ):
            server.run_reconstruction("tag123", edge_backend="rfdetr")
        command = run.call_args[0][0]
        self.assertEqual(command[command.index("--edge-backend") + 1], "rfdetr")

    def test_health_reports_capture_and_upload_backend_policies(self):
        with patch.object(server, "EDGE_BACKEND", "h5"):
            response = server.app.test_client().get("/health")
        payload = response.get_json()
        self.assertEqual(payload["captureEdgeBackend"], "rfdetr")
        self.assertEqual(payload["uploadEdgeBackend"], "h5")

    def test_loads_segmentation_view_summary(self):
        with tempfile.TemporaryDirectory() as root:
            tag_dir = os.path.join(root, "tag123")
            os.makedirs(tag_dir)
            with open(os.path.join(tag_dir, "instances.json"), "w") as file:
                json.dump(
                    {
                        "schemaVersion": 1,
                        "views": {
                            "4": {
                                "backend": "rfdetr",
                                "instanceCount": 12,
                                "fallbackReason": None,
                            }
                        },
                    },
                    file,
                )
            with patch.object(server, "INSTANCE_MASK_DIR", root):
                summary = server.load_segmentation_view_summary("tag123")
        self.assertEqual(summary["front"]["backend"], "rfdetr")
        self.assertEqual(summary["front"]["instanceCount"], 12)
        self.assertIsNone(summary["front"]["fallbackReason"])

    def test_rejects_unknown_segmentation_manifest_schema(self):
        with tempfile.TemporaryDirectory() as root:
            tag_dir = os.path.join(root, "tag123")
            os.makedirs(tag_dir)
            with open(os.path.join(tag_dir, "instances.json"), "w") as file:
                json.dump({"schemaVersion": 2}, file)
            with patch.object(server, "INSTANCE_MASK_DIR", root):
                with self.assertRaisesRegex(ValueError, "Unsupported instance manifest schema"):
                    server.load_segmentation_view_summary("tag123")

    def test_loads_inventory_metadata_without_instance_png_paths(self):
        with tempfile.TemporaryDirectory() as root:
            tag_dir = os.path.join(root, "tag123")
            os.makedirs(tag_dir)
            with open(os.path.join(tag_dir, "tooth_inventory.json"), "w") as file:
                json.dump(
                    {
                        "schemaVersion": 1,
                        "tag": "tag123",
                        "slots": [
                            {
                                "slotId": "U-01",
                                "patientStatus": "observed",
                                "evidence": [{"localId": "instance-000"}],
                            }
                        ],
                    },
                    file,
                )
            with patch.object(server, "TOOTH_INVENTORY_DIR", root):
                summary = server.load_tooth_inventory_summary("tag123")

        self.assertEqual(summary["slots"][0]["slotId"], "U-01")
        self.assertNotIn("mask", summary["slots"][0])


if __name__ == "__main__":
    unittest.main()

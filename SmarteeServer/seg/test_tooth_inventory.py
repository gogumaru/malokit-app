import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import skimage.io

from seg.tooth_inventory import (
    InventoryInstance,
    InventoryView,
    align_primary_arch,
    build_tooth_inventory,
    load_inventory_views,
    write_tooth_inventory,
)


def primary_instances_for_slots(slot_numbers, confidence=0.9):
    return tuple(
        InventoryInstance(
            local_id=f"slot-{slot_number:02d}",
            centroid_xy=((slot_number - 0.5) / 14.0, 0.5),
            width=0.05,
            height=0.1,
            detector_confidence=confidence,
            area_pixels=100,
        )
        for slot_number in slot_numbers
    )


def primary_views_with_gap(slot_id=None):
    upper_slots = [index for index in range(1, 15) if slot_id != f"U-{index:02d}"]
    lower_slots = [index for index in range(1, 15) if slot_id != f"L-{index:02d}"]
    return {
        0: InventoryView(0, "upper", "rfdetr", None, primary_instances_for_slots(upper_slots)),
        1: InventoryView(1, "lower", "rfdetr", None, primary_instances_for_slots(lower_slots)),
    }


def supporting_instances_with_clear_arch_rows():
    upper = tuple(
        InventoryInstance(
            local_id=f"support-upper-{slot_number:02d}",
            centroid_xy=((slot_number - 0.5) / 14.0, 0.25),
            width=0.05,
            height=0.1,
            detector_confidence=0.9,
            area_pixels=100,
        )
        for slot_number in range(1, 15)
    )
    lower = tuple(
        InventoryInstance(
            local_id=f"support-lower-{slot_number:02d}",
            centroid_xy=((slot_number - 0.5) / 14.0, 0.75),
            width=0.05,
            height=0.1,
            detector_confidence=0.9,
            area_pixels=100,
        )
        for slot_number in range(1, 15)
    )
    return upper + lower


class InventoryBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_bundle(self, backend="rfdetr", corrupt_mask_shape=None):
        tag_dir = self.root / "tag"
        tag_dir.mkdir()
        mask_shape = corrupt_mask_shape or (40, 80)
        mask = np.zeros(mask_shape, dtype=np.uint8)
        mask[10:30, 20:40] = 255
        skimage.io.imsave(str(tag_dir / "0-instance-000.png"), mask, check_contrast=False)
        instance_records = []
        if backend == "rfdetr":
            instance_records.append(
                {
                    "localId": "instance-000",
                    "mask": "0-instance-000.png",
                    "confidence": 0.9,
                    "bboxXYWH": [20, 10, 20, 20],
                    "centroidXY": [30.0, 20.0],
                    "areaPixels": 400,
                }
            )
        (tag_dir / "instances.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "tag": "tag",
                    "views": {
                        "0": {
                            "backend": backend,
                            "checkpoint": "upper",
                            "fallbackReason": None,
                            "rgbWidth": 80,
                            "rgbHeight": 40,
                            "instances": instance_records,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_loads_rfdetr_instance_with_normalized_geometry(self):
        self.write_bundle()

        views = load_inventory_views(self.root, "tag")

        tooth = views[0].instances[0]
        self.assertEqual(tooth.local_id, "instance-000")
        self.assertAlmostEqual(tooth.centroid_xy[0], 0.375)
        self.assertAlmostEqual(tooth.centroid_xy[1], 0.5)
        self.assertAlmostEqual(tooth.width, 0.25)
        self.assertAlmostEqual(tooth.height, 0.5)

    def test_h5_view_has_no_identity_instances(self):
        self.write_bundle(backend="h5")

        self.assertEqual(load_inventory_views(self.root, "tag")[0].instances, ())

    def test_rejects_wrong_geometry_instance_png(self):
        self.write_bundle(corrupt_mask_shape=(20, 20))

        with self.assertRaisesRegex(ValueError, "geometry"):
            load_inventory_views(self.root, "tag")

    def test_complete_primary_arch_maps_to_consecutive_slots(self):
        assignments = align_primary_arch(primary_instances_for_slots(range(1, 15)), "U")

        self.assertEqual(
            [assignment.slot_id for assignment in assignments],
            [f"U-{index:02d}" for index in range(1, 15)],
        )
        self.assertTrue(all(assignment.instance is not None for assignment in assignments))

    def test_central_gap_does_not_shift_later_primary_assignments(self):
        assignments = align_primary_arch(
            primary_instances_for_slots([1, 2, 3, 5, 6, 7]), "U"
        )

        by_slot = {assignment.slot_id: assignment for assignment in assignments}
        self.assertIsNone(by_slot["U-04"].instance)
        self.assertEqual(by_slot["U-05"].instance.local_id, "slot-05")

    def test_low_confidence_detection_is_left_unassigned(self):
        assignments = align_primary_arch(primary_instances_for_slots([1, 2], 0.20), "L")

        self.assertTrue(all(assignment.instance is None for assignment in assignments))

    def test_unobserved_patient_slot_is_unknown_and_design_slot_is_inferred(self):
        inventory = build_tooth_inventory("tag", primary_views_with_gap("U-04"))
        slot = next(item for item in inventory["slots"] if item["slotId"] == "U-04")

        self.assertEqual(slot["patientStatus"], "unknown")
        self.assertEqual(slot["designStatus"], "inferred")

    def test_one_missing_view_never_confirms_absence(self):
        inventory = build_tooth_inventory("tag", primary_views_with_gap("L-05"))
        slot = next(item for item in inventory["slots"] if item["slotId"] == "L-05")

        self.assertNotEqual(slot["patientStatus"], "confirmedAbsent")

    def test_explicit_confirmation_is_the_only_absence_source(self):
        inventory = build_tooth_inventory(
            "tag", primary_views_with_gap("L-05"), confirmed_absent_slots=("L-05",)
        )
        slot = next(item for item in inventory["slots"] if item["slotId"] == "L-05")

        self.assertEqual(slot["patientStatus"], "confirmedAbsent")
        self.assertEqual(slot["designStatus"], "confirmedAbsent")

    def test_fallback_view_is_recorded_without_inventing_an_observation(self):
        inventory = build_tooth_inventory(
            "tag",
            {
                0: InventoryView(0, "upper", "h5", "rfdetr_unavailable", ()),
                1: InventoryView(1, "lower", "h5", "rfdetr_unavailable", ()),
            },
        )

        self.assertFalse(inventory["sourceViews"]["0"]["identityEvidenceAvailable"])
        self.assertTrue(
            all(slot["patientStatus"] == "unknown" for slot in inventory["slots"][:14])
        )

    def test_ambiguous_supporting_view_is_recorded_but_not_assigned(self):
        views = primary_views_with_gap()
        views[2] = InventoryView(2, "left", "rfdetr", None, primary_instances_for_slots([1, 2]))
        inventory = build_tooth_inventory("tag", views)

        self.assertEqual(inventory["sourceViews"]["2"]["rejectionReasons"], ["ambiguous_arch_rows"])

    def test_clear_supporting_rows_corroborate_the_matching_primary_slots(self):
        views = primary_views_with_gap()
        views[2] = InventoryView(
            2, "left", "rfdetr", None, supporting_instances_with_clear_arch_rows()
        )

        inventory = build_tooth_inventory("tag", views)
        upper_slot = next(slot for slot in inventory["slots"] if slot["slotId"] == "U-05")
        lower_slot = next(slot for slot in inventory["slots"] if slot["slotId"] == "L-05")

        self.assertEqual(inventory["sourceViews"]["2"]["rejectionReasons"], [])
        self.assertIn(2, [evidence["photoIndex"] for evidence in upper_slot["evidence"]])
        self.assertIn(2, [evidence["photoIndex"] for evidence in lower_slot["evidence"]])

    def test_writes_inventory_atomically(self):
        inventory = build_tooth_inventory("tag", primary_views_with_gap())

        inventory_path = write_tooth_inventory(self.root, "tag", inventory)

        self.assertEqual(inventory_path, self.root / "tag" / "tooth_inventory.json")
        self.assertEqual(json.loads(inventory_path.read_text())["schemaVersion"], 1)
        self.assertFalse((inventory_path.parent / "tooth_inventory.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()

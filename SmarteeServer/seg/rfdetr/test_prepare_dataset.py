import unittest
from pathlib import Path

from prepare_dataset import (
    ImageSample,
    assign_patients,
    original_stem,
    patient_id_from_filename,
    verify_assignment,
)


class FilenameParsingTests(unittest.TestCase):
    def test_removes_roboflow_suffix(self):
        name = "202193202108305_JPG.rf.11903aacdb9a717a898a64aae100e35f.jpg"
        self.assertEqual(original_stem(name), "202193202108305")

    def test_extracts_patient_before_date_and_view(self):
        name = "202193202108305_JPG.rf.11903aacdb9a717a898a64aae100e35f.jpg"
        self.assertEqual(patient_id_from_filename(name), "202193")

    def test_supports_longer_patient_id(self):
        name = "2021105202110144_JPG.rf.abc.jpg"
        self.assertEqual(patient_id_from_filename(name), "2021105")

    def test_rejects_unknown_naming_scheme(self):
        with self.assertRaises(ValueError):
            patient_id_from_filename("mouth-photo.rf.abc.jpg")


class PatientSplitTests(unittest.TestCase):
    @staticmethod
    def sample(patient_id: str, index: int) -> ImageSample:
        return ImageSample(
            patient_id=patient_id,
            archive=Path("source.zip"),
            source_member=f"train/{patient_id}-{index}.jpg",
            image={"id": index, "file_name": f"{patient_id}-{index}.jpg"},
            annotations=({"id": index, "image_id": index, "category_id": 1},),
        )

    def test_patient_never_crosses_splits(self):
        samples = [
            self.sample(patient_id, index)
            for index, patient_id in enumerate(
                ["a", "a", "a", "b", "b", "c", "d", "e", "f", "g"],
                start=1,
            )
        ]
        assigned = assign_patients(
            samples,
            ratios={"train": 0.6, "valid": 0.2, "test": 0.2},
            seed=42,
        )
        verify_assignment(assigned)
        self.assertEqual(sum(map(len, assigned.values())), len(samples))
        self.assertTrue(all(assigned[split] for split in assigned))

    def test_ambiguous_patient_is_training_only(self):
        samples = [
            self.sample(patient_id, index)
            for index, patient_id in enumerate(
                ["a", "b", "c", "d", "e", "f"], start=1
            )
        ]
        samples.append(
            ImageSample(
                patient_id="train-only:lateral:2",
                archive=Path("lateral.zip"),
                source_member="train/2.jpg",
                image={"id": 7, "file_name": "2.jpg"},
                annotations=({"id": 7, "image_id": 7, "category_id": 1},),
                train_only=True,
            )
        )

        assigned = assign_patients(
            samples,
            ratios={"train": 0.6, "valid": 0.2, "test": 0.2},
            seed=42,
        )

        self.assertIn(samples[-1], assigned["train"])
        verify_assignment(assigned)


if __name__ == "__main__":
    unittest.main()

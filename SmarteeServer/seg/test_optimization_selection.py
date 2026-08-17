import unittest

import numpy as np

from seg.optimization_selection import BestOptimizationState


class BestOptimizationStateTests(unittest.TestCase):
    def test_keeps_the_26_2949_snapshot_when_the_next_trial_is_52_4001(self):
        tracker = BestOptimizationState(34.1389, {"rowScaleXZ": np.array([1.0, 1.0])})

        self.assertTrue(tracker.consider(26.2949, {"rowScaleXZ": np.array([0.9, 0.95])}))
        self.assertFalse(tracker.consider(52.4001, {"rowScaleXZ": np.array([0.7, 0.8])}))

        self.assertEqual(tracker.loss, 26.2949)
        np.testing.assert_allclose(tracker.parameters["rowScaleXZ"], [0.9, 0.95])

    def test_rejects_stage_one_when_its_first_trial_is_not_better_than_stage_zero(self):
        tracker = BestOptimizationState(34.1389, {"rowScaleXZ": np.array([1.0, 1.0])})

        self.assertFalse(tracker.consider(34.1389, {"rowScaleXZ": np.array([0.9, 0.95])}))

        self.assertEqual(tracker.loss, 34.1389)
        np.testing.assert_allclose(tracker.parameters["rowScaleXZ"], [1.0, 1.0])

    def test_parameter_snapshot_is_not_mutated_by_later_trials(self):
        candidate = {"rowScaleXZ": np.array([0.9, 0.95])}
        tracker = BestOptimizationState(34.1389, {"rowScaleXZ": np.array([1.0, 1.0])})

        tracker.consider(26.2949, candidate)
        candidate["rowScaleXZ"][0] = 0.1

        np.testing.assert_allclose(tracker.parameters["rowScaleXZ"], [0.9, 0.95])


if __name__ == "__main__":
    unittest.main()

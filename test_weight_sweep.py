#!/usr/bin/env python3

import unittest

import pandas as pd

from weight_sweep import (
    consensus_candidate,
    generate_weight_grid,
    rank_results,
)


class WeightSweepTests(unittest.TestCase):
    def test_default_four_asset_grid_is_bounded_and_sums_to_one(self):
        symbols = ["513180.SH", "515450.SH", "513300.SH", "159783.SZ"]
        grid = generate_weight_grid(
            symbols,
            step=0.05,
            min_weight=0.10,
            max_weight=0.50,
        )
        self.assertEqual(len(grid), 375)
        for weights in grid:
            self.assertAlmostEqual(sum(weights.values()), 1.0)
            for value in weights.values():
                self.assertGreaterEqual(value, 0.10)
                self.assertLessEqual(value, 0.50)
                self.assertAlmostEqual((value / 0.05) % 1, 0.0)

    def test_invalid_step_is_rejected(self):
        with self.assertRaises(ValueError):
            generate_weight_grid(["A", "B"], step=0.03)

    def test_rank_results_rewards_better_worst_period_and_drawdown(self):
        frame = pd.DataFrame(
            [
                {
                    "weight_A": 0.5,
                    "weight_B": 0.5,
                    "full_xirr": 0.16,
                    "full_sharpe": 0.9,
                    "worst_fold_xirr": 0.04,
                    "mean_fold_xirr": 0.11,
                    "full_max_drawdown": -0.20,
                    "fold_xirr_std": 0.03,
                    "hhi": 0.50,
                },
                {
                    "weight_A": 0.8,
                    "weight_B": 0.2,
                    "full_xirr": 0.18,
                    "full_sharpe": 0.7,
                    "worst_fold_xirr": -0.08,
                    "mean_fold_xirr": 0.08,
                    "full_max_drawdown": -0.36,
                    "fold_xirr_std": 0.11,
                    "hhi": 0.68,
                },
            ]
        )
        ranked = rank_results(frame)
        self.assertAlmostEqual(float(ranked.iloc[0]["weight_A"]), 0.5)

    def test_consensus_returns_actual_top_candidate(self):
        ranked = pd.DataFrame(
            [
                {"weight_A": 0.40, "weight_B": 0.60, "robust_score": 0.9},
                {"weight_A": 0.45, "weight_B": 0.55, "robust_score": 0.8},
                {"weight_A": 0.90, "weight_B": 0.10, "robust_score": 0.1},
            ]
        )
        chosen, center = consensus_candidate(ranked, ["A", "B"], top_n=2)
        self.assertAlmostEqual(center["A"], 0.425)
        self.assertIn(float(chosen["weight_A"]), {0.40, 0.45})


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3

import unittest

import numpy as np
import pandas as pd

from risk_analysis import rolling_risk_report, static_risk_report
from walk_forward import build_walk_forward_windows, summarize_walk_forward


class WalkForwardTests(unittest.TestCase):
    def _prices(self):
        dates = pd.bdate_range("2018-01-01", "2025-12-31")
        n = len(dates)
        return pd.DataFrame(
            {
                "date": dates,
                "A.SH": 100.0 * np.exp(np.linspace(0, 0.8, n)),
                "B.SH": 100.0 * np.exp(np.linspace(0, 0.5, n)),
            }
        )

    def test_walk_forward_has_no_train_test_overlap(self):
        windows = build_walk_forward_windows(
            self._prices(), train_years=3, test_months=12, min_train_days=400, min_test_days=40
        )
        self.assertGreaterEqual(len(windows), 4)
        for window in windows:
            self.assertLess(window.train_end, window.test_start)
            self.assertLessEqual(window.train_start, window.train_end)
            self.assertLessEqual(window.test_start, window.test_end)
            self.assertTrue((window.train["date"] < window.test_start).all())
            self.assertTrue((window.test["date"] >= window.test_start).all())

    def test_walk_forward_summary_reports_weight_stability(self):
        results = pd.DataFrame(
            {
                "test_start": pd.to_datetime(["2023-01-01", "2024-01-01"]),
                "test_end": pd.to_datetime(["2023-12-31", "2024-12-31"]),
                "selected_test_xirr": [0.10, 0.08],
                "equal_test_xirr": [0.08, 0.09],
                "default_test_xirr": [0.08, 0.09],
                "selected_weight_A.SH": [0.30, 0.40],
                "selected_weight_B.SH": [0.70, 0.60],
            }
        )
        oos_nav = pd.DataFrame(
            {
                "date": pd.bdate_range("2023-01-02", periods=60),
                "twr_return": [0.001] * 60,
                "oos_nav": np.cumprod([1.001] * 60),
            }
        )
        summary = summarize_walk_forward(results, oos_nav)
        self.assertAlmostEqual(summary["mean_selected_weight_A.SH"], 0.35)
        self.assertAlmostEqual(summary["std_selected_weight_A.SH"], 0.05)
        self.assertAlmostEqual(summary["hit_rate_vs_equal"], 0.5)


class RiskAnalysisTests(unittest.TestCase):
    def _identical_returns(self):
        base = np.array(
            [0.01, -0.005, 0.002, 0.004, -0.003] * 20,
            dtype=float,
        )
        return pd.DataFrame(
            {
                "date": pd.bdate_range("2024-01-01", periods=len(base)),
                "A.SH": base,
                "B.SH": base,
            }
        )

    def test_identical_assets_have_no_diversification_benefit(self):
        report = static_risk_report(
            self._identical_returns(), {"A.SH": 0.25, "B.SH": 0.75}
        )
        summary = report["summary"]
        assets = report["assets"].set_index("symbol")
        self.assertAlmostEqual(summary["diversification_ratio"], 1.0, places=10)
        self.assertAlmostEqual(summary["pc1_explained_share"], 1.0, places=10)
        self.assertAlmostEqual(assets.loc["A.SH", "risk_share"], 0.25, places=10)
        self.assertAlmostEqual(assets.loc["B.SH", "risk_share"], 0.75, places=10)
        self.assertAlmostEqual(assets["risk_share"].sum(), 1.0, places=10)

    def test_risk_shares_sum_to_one_for_correlated_assets(self):
        rng = np.random.default_rng(7)
        common = rng.normal(0, 0.01, 300)
        returns = pd.DataFrame(
            {
                "date": pd.bdate_range("2023-01-02", periods=300),
                "A.SH": common + rng.normal(0, 0.004, 300),
                "B.SH": 0.7 * common + rng.normal(0, 0.006, 300),
                "C.SH": rng.normal(0, 0.012, 300),
            }
        )
        report = static_risk_report(
            returns, {"A.SH": 0.3, "B.SH": 0.4, "C.SH": 0.3}
        )
        self.assertAlmostEqual(report["assets"]["risk_share"].sum(), 1.0, places=10)
        self.assertGreater(report["summary"]["diversification_ratio"], 1.0)
        self.assertGreaterEqual(report["summary"]["effective_risk_bets"], 1.0)

    def test_rolling_risk_produces_latest_snapshot(self):
        returns = self._identical_returns()
        rolling = rolling_risk_report(
            returns,
            {"A.SH": 0.5, "B.SH": 0.5},
            window=40,
            stride=21,
        )
        self.assertFalse(rolling.empty)
        self.assertEqual(pd.Timestamp(rolling.iloc[-1]["date"]), returns.iloc[-1]["date"])
        self.assertIn("risk_share_A.SH", rolling.columns)


if __name__ == "__main__":
    unittest.main()

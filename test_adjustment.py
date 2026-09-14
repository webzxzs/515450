#!/usr/bin/env python3

import unittest

import pandas as pd

from adjustment_analysis import align_price_bases, asset_adjustment_report


class AdjustmentAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.symbols = ["AAA.SH", "BBB.SH"]
        dates = pd.date_range("2024-01-01", periods=5, freq="D")
        self.actual = pd.DataFrame(
            {
                "date": dates,
                "AAA.SH": [100.0, 90.0, 91.0, 92.0, 93.0],
                "BBB.SH": [50.0, 51.0, 52.0, 53.0, 54.0],
            }
        )
        # AAA forward-adjustment removes the apparent 10% ex-distribution drop;
        # BBB is unchanged.
        self.forward = pd.DataFrame(
            {
                "date": dates,
                "AAA.SH": [90.0, 90.0, 91.0, 92.0, 93.0],
                "BBB.SH": [50.0, 51.0, 52.0, 53.0, 54.0],
            }
        )

    def test_align_price_bases_keeps_identical_dates(self):
        actual, forward = align_price_bases(self.actual, self.forward, self.symbols)
        self.assertEqual(list(actual["date"]), list(forward["date"]))
        self.assertEqual(list(actual.columns), ["date", *self.symbols])
        self.assertEqual(list(forward.columns), ["date", *self.symbols])

    def test_forward_adjustment_detects_return_wedge(self):
        report, daily = asset_adjustment_report(
            self.actual, self.forward, self.symbols, wedge_threshold=1e-5
        )
        aaa = report.set_index("symbol").loc["AAA.SH"]
        bbb = report.set_index("symbol").loc["BBB.SH"]

        self.assertGreater(int(aaa["adjustment_days"]), 0)
        self.assertGreater(float(aaa["forward_total_return"]), float(aaa["actual_total_return"]))
        self.assertEqual(int(bbb["adjustment_days"]), 0)
        self.assertAlmostEqual(
            float(bbb["forward_total_return"]),
            float(bbb["actual_total_return"]),
            places=12,
        )
        self.assertIn("adjustment_wedge_AAA.SH", daily.columns)

    def test_alignment_drops_non_common_dates(self):
        shortened = self.forward.iloc[1:].reset_index(drop=True)
        actual, forward = align_price_bases(self.actual, shortened, self.symbols)
        self.assertEqual(len(actual), 4)
        self.assertEqual(len(forward), 4)
        self.assertEqual(actual.iloc[0]["date"], shortened.iloc[0]["date"])


if __name__ == "__main__":
    unittest.main()

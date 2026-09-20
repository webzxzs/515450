#!/usr/bin/env python3

import unittest

import pandas as pd

from dividend_data import apply_explicit_total_return


class DividendDataTests(unittest.TestCase):
    def test_cash_dividend_removes_ex_dividend_price_drop(self):
        daily = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
                "close": [100.0, 90.0, 91.0],
            }
        )
        events = pd.DataFrame(
            {
                "symbol": ["AAA.SH"],
                "ex_date": pd.to_datetime(["2026-01-05"]),
                "cash_per_share": [10.0],
            }
        )

        result = apply_explicit_total_return(daily, "AAA.SH", events=events)

        self.assertAlmostEqual(float(result.iloc[0]["close"]), 100.0)
        self.assertAlmostEqual(float(result.iloc[1]["close"]), 100.0)
        self.assertAlmostEqual(float(result.iloc[2]["close"]), 101.1111111111, places=8)

    def test_no_dividends_keeps_actual_close(self):
        daily = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-02", "2026-01-05"]),
                "close": [10.0, 11.0],
            }
        )
        empty = pd.DataFrame(columns=["symbol", "ex_date", "cash_per_share"])

        result = apply_explicit_total_return(daily, "AAA.SH", events=empty)

        self.assertEqual(result["close"].tolist(), [10.0, 11.0])

    def test_missing_ex_date_inside_history_is_rejected(self):
        daily = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-02", "2026-01-06"]),
                "close": [100.0, 101.0],
            }
        )
        events = pd.DataFrame(
            {
                "symbol": ["AAA.SH"],
                "ex_date": pd.to_datetime(["2026-01-05"]),
                "cash_per_share": [1.0],
            }
        )

        with self.assertRaises(ValueError):
            apply_explicit_total_return(daily, "AAA.SH", events=events)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from longbridge_data import CacheInfo, LongbridgeDataError, fetch_daily, load_daily_data


class LongbridgeDataTests(unittest.TestCase):
    @patch("longbridge_data._run_cli_window")
    def test_fetch_daily_can_allow_empty_non_trading_range(self, run_cli):
        run_cli.return_value = pd.DataFrame()

        empty = fetch_daily(
            "513180.SH",
            "2026-09-19",
            "2026-09-20",
            adjust="forward",
            allow_empty=True,
        )

        self.assertTrue(empty.empty)
        self.assertIn("close", empty.columns)

    @patch("longbridge_data._run_cli_window")
    def test_fetch_daily_still_rejects_empty_primary_request(self, run_cli):
        run_cli.return_value = pd.DataFrame()

        with self.assertRaises(LongbridgeDataError):
            fetch_daily(
                "513180.SH",
                "2026-09-19",
                "2026-09-20",
                adjust="forward",
            )

    def test_cached_data_tolerates_empty_prelisting_and_weekend_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "513180_SH_forward.csv"
            pd.DataFrame(
                {
                    "date": pd.to_datetime(["2021-05-10", "2021-05-11"]),
                    "open": [1.0, 1.1],
                    "high": [1.1, 1.2],
                    "low": [0.9, 1.0],
                    "close": [1.0, 1.1],
                }
            ).to_csv(cache_path, index=False)

            info = CacheInfo(cache_path, "513180.SH", "forward")
            calls = []

            def fake_fetch(symbol, start, end, *, adjust, allow_empty=False):
                calls.append((pd.Timestamp(start).date(), pd.Timestamp(end).date(), allow_empty))
                return pd.DataFrame(
                    columns=["date", "open", "high", "low", "close", "volume", "amount"]
                )

            with patch("longbridge_data.cache_info", return_value=info), patch(
                "longbridge_data.fetch_daily", side_effect=fake_fetch
            ):
                result = load_daily_data(
                    "513180.SH",
                    start="2020-01-01",
                    end="2021-05-16",
                    adjust="forward",
                )

            self.assertEqual(len(result), 2)
            self.assertEqual(result["date"].iloc[0], pd.Timestamp("2021-05-10"))
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(call[2] for call in calls))

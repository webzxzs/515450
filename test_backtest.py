import unittest
from unittest.mock import patch

import pandas as pd

from backtest import StrategyConfig, load_price_table, parse_portfolio, run_strategy


class PortfolioStrategyTests(unittest.TestCase):
    def test_parse_portfolio_normalizes_weights(self):
        weights = parse_portfolio("515450.SH:80,513130.SH:20")
        self.assertAlmostEqual(weights["515450.SH"], 0.8)
        self.assertAlmostEqual(weights["513130.SH"], 0.2)
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_price_loader_forward_fills_valuation_but_marks_untradable(self):
        aaa = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
                "close": [10.0, 11.0, 12.0],
            }
        )
        bbb = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-02", "2026-01-06"]),
                "close": [20.0, 22.0],
            }
        )

        def fake_load(symbol, **kwargs):
            return aaa.copy() if symbol == "AAA.SH" else bbb.copy()

        with patch("backtest.load_daily_data", side_effect=fake_load):
            prices = load_price_table(
                ["AAA.SH", "BBB.SH"],
                start="2026-01-01",
                end=None,
                adjust="forward",
                refresh=False,
            )

        jan5 = prices.loc[prices["date"] == pd.Timestamp("2026-01-05")].iloc[0]
        self.assertEqual(float(jan5["BBB.SH"]), 20.0)
        self.assertFalse(bool(jan5["tradable_BBB.SH"]))
        self.assertTrue(bool(jan5["tradable_AAA.SH"]))

    def test_strategy_does_not_trade_symbol_on_unavailable_date(self):
        prices = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-02", "2026-02-02"]),
                "AAA.SH": [10.0, 10.0],
                "BBB.SH": [10.0, 10.0],
                "tradable_AAA.SH": [True, True],
                "tradable_BBB.SH": [False, True],
            }
        )
        cfg = StrategyConfig(
            weights={"AAA.SH": 0.5, "BBB.SH": 0.5},
            monthly_contribution=1000,
            rebalance_months=0,
            commission_rate=0.0,
            min_commission=0.0,
            lot_sizes={"AAA.SH": 1, "BBB.SH": 1},
        )
        result = run_strategy(prices, cfg)
        jan_trades = result.trades[result.trades["date"] == pd.Timestamp("2026-01-02")]
        self.assertTrue((jan_trades["symbol"] == "AAA.SH").any())
        self.assertFalse((jan_trades["symbol"] == "BBB.SH").any())

    def test_periodic_rebalance_generates_rebalance_trades(self):
        prices = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    [
                        "2026-01-02",
                        "2026-02-02",
                        "2026-03-02",
                        "2026-04-01",
                        "2026-05-04",
                        "2026-06-01",
                    ]
                ),
                "AAA.SH": [10, 10, 20, 20, 20, 20],
                "BBB.SH": [10, 10, 10, 10, 10, 10],
            }
        )
        cfg = StrategyConfig(
            weights={"AAA.SH": 0.5, "BBB.SH": 0.5},
            monthly_contribution=1000,
            rebalance_months=3,
            commission_rate=0.0,
            min_commission=0.0,
            lot_sizes={"AAA.SH": 1, "BBB.SH": 1},
        )

        result = run_strategy(prices, cfg)

        self.assertEqual(result.summary["months"], 6)
        self.assertEqual(result.summary["total_contribution"], 6000)
        self.assertTrue((result.trades["reason"] == "REBALANCE").any())
        self.assertEqual(int(result.monthly["rebalanced"].sum()), 2)

    def test_zero_rebalance_months_is_dca_only(self):
        prices = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-02", "2026-02-02", "2026-03-02"]),
                "AAA.SH": [10, 20, 30],
                "BBB.SH": [10, 10, 10],
            }
        )
        cfg = StrategyConfig(
            weights={"AAA.SH": 0.5, "BBB.SH": 0.5},
            monthly_contribution=1000,
            rebalance_months=0,
            commission_rate=0.0,
            min_commission=0.0,
            lot_sizes={"AAA.SH": 1, "BBB.SH": 1},
        )

        result = run_strategy(prices, cfg)

        self.assertFalse((result.trades["reason"] == "REBALANCE").any())
        self.assertFalse((result.trades["side"] == "SELL").any())
        self.assertEqual(result.summary["total_contribution"], 3000)


if __name__ == "__main__":
    unittest.main()

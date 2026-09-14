import unittest

import pandas as pd

from backtest import StrategyConfig, parse_portfolio, run_strategy


class PortfolioStrategyTests(unittest.TestCase):
    def test_parse_portfolio_normalizes_weights(self):
        weights = parse_portfolio("515450.SH:80,513130.SH:20")
        self.assertAlmostEqual(weights["515450.SH"], 0.8)
        self.assertAlmostEqual(weights["513130.SH"], 0.2)
        self.assertAlmostEqual(sum(weights.values()), 1.0)

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

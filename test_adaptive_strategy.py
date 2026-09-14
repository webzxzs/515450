import unittest

import pandas as pd

from adaptive_strategy import AdaptiveStrategyConfig, run_adaptive_strategy
from policy_sweep import build_policy_variants


class AdaptiveStrategyTests(unittest.TestCase):
    def _prices(self):
        return pd.DataFrame(
            {
                "date": pd.to_datetime(
                    [
                        "2024-01-02",
                        "2024-02-01",
                        "2024-03-01",
                        "2024-04-01",
                    ]
                ),
                "A": [10.0, 20.0, 20.0, 20.0],
                "B": [10.0, 10.0, 10.0, 10.0],
            }
        )

    def _config(self, **overrides):
        values = dict(
            weights={"A": 0.5, "B": 0.5},
            monthly_contribution=100.0,
            commission_rate=0.0,
            min_commission=0.0,
            lot_sizes={"A": 1, "B": 1},
            contribution_mode="underweight",
            rebalance_rule="none",
            rebalance_months=0,
            rebalance_threshold=0.0,
        )
        values.update(overrides)
        return AdaptiveStrategyConfig(**values)

    def test_underweight_dca_directs_more_cash_to_laggard(self):
        prices = self._prices()
        underweight = run_adaptive_strategy(prices, self._config())
        target = run_adaptive_strategy(
            prices,
            self._config(contribution_mode="target"),
        )

        underweight_b = int(underweight.summary["ending_shares_B"])
        target_b = int(target.summary["ending_shares_B"])
        self.assertGreater(underweight_b, target_b)
        self.assertTrue((underweight.trades["side"] == "BUY").all())

    def test_threshold_rebalance_fires_only_when_drift_is_large_enough(self):
        prices = self._prices()
        tight = run_adaptive_strategy(
            prices,
            self._config(
                contribution_mode="target",
                rebalance_rule="threshold",
                rebalance_threshold=0.01,
            ),
        )
        loose = run_adaptive_strategy(
            prices,
            self._config(
                contribution_mode="target",
                rebalance_rule="threshold",
                rebalance_threshold=0.45,
            ),
        )
        self.assertGreater(int(tight.summary["rebalance_events"]), 0)
        self.assertEqual(int(loose.summary["rebalance_events"]), 0)

    def test_threshold_does_not_treat_uninvested_cash_as_weight_drift(self):
        prices = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-02", "2024-02-01", "2024-03-01"]),
                "A": [10.0, 10.0, 10.0],
                "B": [10.0, 10.0, 10.0],
            }
        )
        result = run_adaptive_strategy(
            prices,
            self._config(
                monthly_contribution=100.0,
                lot_sizes={"A": 100, "B": 100},
                contribution_mode="underweight",
                rebalance_rule="threshold",
                rebalance_threshold=0.01,
            ),
        )
        self.assertEqual(int(result.summary["rebalance_events"]), 0)
        self.assertEqual(float(result.summary["ending_max_weight_drift"]), 0.0)

    def test_periodic_rebalance_cadence_is_respected(self):
        result = run_adaptive_strategy(
            self._prices(),
            self._config(
                rebalance_rule="periodic",
                rebalance_months=2,
                rebalance_threshold=0.0,
            ),
        )
        self.assertEqual(int(result.summary["rebalance_events"]), 2)
        triggers = result.monthly.loc[result.monthly["rebalanced"], "rebalance_trigger"].tolist()
        self.assertEqual(triggers, ["periodic", "periodic"])

    def test_default_policy_grid_has_sixteen_rules(self):
        policies = build_policy_variants([1, 3, 6, 12], [0.03, 0.05, 0.10])
        names = {str(item["policy"]) for item in policies}
        self.assertEqual(len(policies), 16)
        self.assertEqual(len(names), 16)
        self.assertIn("target_periodic_12m", names)
        self.assertIn("underweight_periodic_3m", names)
        self.assertIn("target_threshold_5pct", names)
        self.assertIn("underweight_threshold_10pct", names)
        self.assertIn("underweight_none", names)


if __name__ == "__main__":
    unittest.main()

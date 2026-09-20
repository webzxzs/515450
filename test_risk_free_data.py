import tempfile
import unittest
from pathlib import Path

import pandas as pd

from risk_free_data import align_risk_free_returns, annualized_excess_sharpe


class RiskFreeDataTests(unittest.TestCase):
    def _snapshot(self, directory: str) -> Path:
        path = Path(directory) / "risk_free.csv"
        pd.DataFrame(
            {
                "date": ["2024-01-02", "2024-01-03", "2024-01-05"],
                "annual_yield_pct": [2.0, 2.4, 3.0],
            }
        ).to_csv(path, index=False)
        return path

    def test_alignment_uses_latest_prior_observation_without_lookahead(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._snapshot(tmp)
            aligned = align_risk_free_returns(
                pd.to_datetime(["2024-01-03", "2024-01-04", "2024-01-05"]),
                path=path,
            )
            self.assertAlmostEqual(float(aligned.iloc[0]["risk_free_annual"]), 0.024)
            self.assertAlmostEqual(float(aligned.iloc[1]["risk_free_annual"]), 0.024)
            self.assertAlmostEqual(float(aligned.iloc[2]["risk_free_annual"]), 0.030)

    def test_alignment_rejects_dates_before_snapshot_instead_of_looking_forward(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._snapshot(tmp)
            with self.assertRaises(ValueError):
                align_risk_free_returns(pd.to_datetime(["2024-01-01"]), path=path)

    def test_positive_risk_free_rate_reduces_sharpe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "risk_free.csv"
            dates = pd.bdate_range("2024-01-02", periods=60)
            pd.DataFrame(
                {
                    "date": dates,
                    "annual_yield_pct": [3.0] * len(dates),
                }
            ).to_csv(path, index=False)
            returns = pd.Series(([0.0002, 0.0018, 0.0007, 0.0011, 0.0004] * 12))
            sharpe = annualized_excess_sharpe(returns, dates, path=path)
            zero_rf = float(returns.mean() / returns.std(ddof=1) * (242 ** 0.5))
            self.assertLess(sharpe, zero_rf)


if __name__ == "__main__":
    unittest.main()

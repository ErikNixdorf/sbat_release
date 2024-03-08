import numpy as np
import pandas as pd


class TestConfig1:
    def test_daily_stats(self, model_config1):
        expected = [
            [0.83560016, 1.22026351, 1.46034379],
            [0.77467953, 1.06789572, 1.37849998],
            [0.21449713, 0.29782467, 1.38847861],
            [0.19540341, 0.23059803, 1.18011267],
        ]
        result = model_config1.gauges_meta[
            ["q_daily_mean", "q_daily_std", "q_daily_cv"]
        ].dropna().values.flatten()

        np.testing.assert_almost_equal(
            result,
            expected,
        )

    def test_monthly_stats(self, model_config1):
        expected = [
            [0.83616979, 0.55223783, 0.66043744],
            [0.77583502, 0.49909641, 0.64330225],
            [0.21478395, 0.13230531, 0.61599255],
            [0.19565859, 0.1093387, 0.55882393],
        ]

        result = model_config1.gauges_meta[
            ["q_monthly_mean", "q_monthly_std", "q_monthly_cv"]
        ].dropna().values.flatten()

        np.testing.assert_almost_equal(
            result,
            expected,
        )


class TestConfig3:
    def test_daily_stats(self, model_config3):
        expected = pd.Series(
            [3.304937, 2.084462, 0.829984],
            index=["q_daily_mean", "q_daily_std", "q_daily_cv"],
        )
        result = model_config3.gauges_meta[
            ["q_daily_mean", "q_daily_std", "q_daily_cv"]
        ].mean()

        pd.testing.assert_series_equal(expected, result)

    def test_monthly_stats(self, model_config3):
        expected = pd.Series(
            [3.332814, 1.762536, 0.602831],
            index=["q_monthly_mean", "q_monthly_std", "q_monthly_cv"],
        )

        result = model_config3.gauges_meta[
            ["q_monthly_mean", "q_monthly_std", "q_monthly_cv"]
        ].mean()

        pd.testing.assert_series_equal(expected, result)

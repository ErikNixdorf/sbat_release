import numpy as np
import pandas as pd
from pathlib import Path

class TestConfig1:
    def test_updated_gauges_meta(self, model_config1):
        expected = [
            [0.44402187438793106],
            [0.3820896833759385],
            [0.13783595100685841],
            [0.12515986411384228],
        ]
        result = model_config1.gauges_meta[["balance"]].values
        np.testing.assert_almost_equal(result, expected, decimal=6)

    def test_sections_meta(self, model_config1):
        expected = pd.read_csv(Path(Path(__file__).parents[0],"data/example1/sections_meta.csv"), index_col=0)
        result = model_config1.sections_meta
        result["decade"] = result["decade"].astype(np.int64)
        pd.testing.assert_frame_equal(expected, result)


class TestConfig3:
    def test_updated_gauges_meta(self, model_config3):
        expected = pd.read_csv(Path(Path(__file__).parents[0],"data/example3/gauges_meta.csv"))
        expected['decade'] = expected['decade'].astype(str)
        expected = expected.set_index(['gauge','decade'])["balance"]
        result = model_config3.gauges_meta[["balance"]]
        pd.testing.assert_series_equal(expected, result["balance"])

    def test_updated_gauges_meta_nans(self, model_config3):
        expected = pd.Series(
            index=[
                "goeritz_nr_195",
                "hammerstadt_1",
                "hammerstadt_1",
                "heinersbrueck",
                "merzdorf_2",
                "neusalza_spremberg",
                "neusalza_spremberg",
                "niedergurig",
                "radensdorf_1",
                "radensdorf_2",
                "reichwalde_3",
                "reichwalde_3",
                "schoenfeld",
                "schoenfeld",
                "schoeps",
            ],
            name="balance",
        )
        expected.index.name = "gauge"
        single_indexed = model_config3.gauges_meta[["balance"]].reset_index(
            level=1, drop=True
        )
        result = single_indexed["balance"][single_indexed["balance"].isnull()]
        pd.testing.assert_series_equal(expected, result)

    def test_sections_meta(self, model_config3):
        expected = pd.read_csv(Path(Path(__file__).parents[0],"data/example3/sections_meta.csv"), index_col=0)
        result = model_config3.sections_meta
        result["decade"] = result["decade"].astype(np.int64)
        pd.testing.assert_frame_equal(expected, result)
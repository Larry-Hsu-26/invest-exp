import json

import pandas as pd
import pytest

from invest_exp.data import load_series, parse_twse_month, splice


def test_parse_roc_date_and_commas():
    payload = {
        "stat": "OK",
        "fields": ["日期", "開盤指數", "最高指數", "最低指數", "收盤指數"],
        "data": [
            [" 92/01/02", "4,500.00", "4,600.00", "4,400.00", "4,524.92"],
            ["92/01/03", "1", "1", "1", "4,626.36"],
        ],
    }
    df = parse_twse_month(payload)
    assert list(df.index) == [pd.Timestamp("2003-01-02"), pd.Timestamp("2003-01-03")]
    assert df["close"].tolist() == [4524.92, 4626.36]


def test_parse_total_return_two_columns():
    payload = {"stat": "OK", "fields": ["日　期", "發行量加權股價報酬指數"], "data": [["115/11/02", "103,873.24"]]}
    df = parse_twse_month(payload)
    assert df.loc[pd.Timestamp("2026-11-02"), "close"] == 103873.24


def test_parse_empty_month():
    assert parse_twse_month({"stat": "OK", "data": []}).empty


def test_load_series_concatenates_months_in_order(tmp_path):
    d = tmp_path / "MFI94U"
    d.mkdir()
    (d / "200302.json").write_text(json.dumps({"stat": "OK", "data": [["92/02/05", "10"]]}))
    (d / "200301.json").write_text(json.dumps({"stat": "OK", "data": [["92/01/02", "9"]]}))
    s = load_series(tmp_path, "MFI94U")
    assert s.index.is_monotonic_increasing
    assert s.tolist() == [9.0, 10.0]


def _series(values: dict[str, float]) -> pd.Series:
    return pd.Series({pd.Timestamp(k): v for k, v in values.items()}, dtype=float)


def test_splice_scales_at_overlap_day():
    price = _series({"2002-12-30": 100.0, "2002-12-31": 110.0, "2003-01-02": 120.0})
    tr = _series({"2003-01-02": 240.0, "2003-01-03": 250.0})
    out = splice(price, tr)
    # 2003-01-02 兩者都有：比值 2，之前的價格指數乘 2 接上。
    assert out.loc[pd.Timestamp("2002-12-31"), "level"] == 220.0
    assert out.loc[pd.Timestamp("2003-01-02"), "level"] == 240.0
    assert out.loc[pd.Timestamp("2003-01-03"), "level"] == 250.0


def test_splice_marks_pre_tr_rows():
    price = _series({"2002-12-31": 110.0, "2003-01-02": 120.0})
    tr = _series({"2003-01-02": 240.0})
    out = splice(price, tr)
    assert out["is_tr"].tolist() == [False, True]


def test_splice_rejects_missing_overlap():
    price = _series({"2002-12-31": 110.0})
    tr = _series({"2003-01-02": 240.0})
    with pytest.raises(ValueError, match="overlap"):
        splice(price, tr)

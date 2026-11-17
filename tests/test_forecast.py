import numpy as np
import pandas as pd
import pytest

from invest_exp.forecast import context_windows, garch_lower


def test_context_windows_end_before_target_day():
    level = np.arange(10, dtype=float)
    targets, ctx = context_windows(level, context=3)
    assert targets.tolist() == list(range(3, 10))
    # 第 t 天的 context 是 t−3、t−2、t−1，不含 t。
    assert ctx[0].tolist() == [0.0, 1.0, 2.0]
    assert ctx[-1].tolist() == [6.0, 7.0, 8.0]


def test_garch_lower_uses_only_past():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2020-01-01", periods=260)
    close = pd.Series(100 * np.exp(rng.standard_normal(260).cumsum() * 0.01), index=idx)
    base = garch_lower(close, qs=(0.1,), window=200, targets=idx[[220, 230, 240]])
    # 從目標日本身開始改（非等比例），抓「用到當日報酬」這種差一天的洩漏。
    shocked = close.copy()
    shocked.iloc[230:] *= np.linspace(0.5, 1.5, 30)
    after = garch_lower(shocked, qs=(0.1,), window=200, targets=idx[[220, 230, 240]])
    pd.testing.assert_series_equal(base["q0.1"].iloc[:2], after["q0.1"].iloc[:2])
    assert base["q0.1"].iloc[2] != after["q0.1"].iloc[2]


def test_garch_lower_rejects_targets_without_full_window():
    idx = pd.bdate_range("2020-01-01", periods=230)
    close = pd.Series(np.linspace(100, 120, 230), index=idx)
    # 不在 index 的日期（get_indexer 回 −1）與歷史不足的日期都必須拒絕，否則會取到序列尾端的未來資料。
    for bad in (pd.DatetimeIndex(["2030-01-01"]), idx[[150]]):
        with pytest.raises(ValueError):
            garch_lower(close, qs=(0.1,), window=200, targets=bad)


def test_garch_lower_below_previous_close_for_low_quantile():
    rng = np.random.default_rng(2)
    idx = pd.bdate_range("2020-01-01", periods=230)
    close = pd.Series(100 * np.exp(rng.standard_normal(230).cumsum() * 0.01), index=idx)
    out = garch_lower(close, qs=(0.05, 0.1), window=200, targets=idx[[210, 220]])
    prev = close.shift(1).loc[out.index]
    assert (out["q0.05"] < out["q0.1"]).all()
    assert (out["q0.1"] < prev).all()

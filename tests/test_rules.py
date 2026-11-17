import numpy as np
import pandas as pd

from invest_exp.rules import below, drawdown_signal, empirical_lower, ma_signal


def _close(values) -> pd.Series:
    return pd.Series(values, index=pd.bdate_range("2020-01-01", periods=len(values)), dtype=float)


def test_ma_signal_uses_today_close():
    close = _close([10, 10, 10, 7])
    sig = ma_signal(close, 3)
    # 第 4 天均線含當日：(10+10+7)/3=9，收盤 7 < 9。
    assert sig.tolist() == [False, False, False, True]


def test_ma_signal_false_before_enough_history():
    assert not ma_signal(_close([5, 1]), 3).any()


def test_drawdown_from_trailing_high():
    close = _close([100, 120, 110, 107, 108])
    sig = drawdown_signal(close, 0.10, lookback=3)
    # 第 4 天：過去 3 日高點 120，107 <= 108 → 成立；第 5 天高點 110，108 > 99 → 不成立。
    assert sig.tolist() == [False, False, False, True, False]


def test_empirical_lower_uses_only_past_returns():
    rng = np.random.default_rng(0)
    close = _close(100 * np.exp(rng.standard_normal(60).cumsum() * 0.01))
    base = empirical_lower(close, window=20, q=0.1)
    shocked = close.copy()
    shocked.iloc[40:] *= 0.5
    after = empirical_lower(shocked, window=20, q=0.1)
    # 第 40 天（含）以後的價格改變，不能影響第 40 天（含）以前的下界。
    pd.testing.assert_series_equal(base.iloc[:41], after.iloc[:41])


def test_empirical_lower_matches_definition():
    close = _close([100, 101, 99, 102, 100, 98])
    lower = empirical_lower(close, window=3, q=0.5)
    r = close.pct_change()
    expected = close.iloc[4] * (1 + r.iloc[2:5].median())
    assert lower.iloc[5] == expected


def test_below_false_when_lower_missing():
    close = _close([1, 2, 3])
    lower = pd.Series([np.nan, 5, 1], index=close.index)
    assert below(close, lower).tolist() == [False, True, False]

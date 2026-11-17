"""進場訊號：第 t 天收盤後判斷；下界只用 t−1 以前的資料。"""

import pandas as pd


def ma_signal(close: pd.Series, n: int) -> pd.Series:
    ma = close.rolling(n, min_periods=n).mean()
    return (close < ma).fillna(False).astype(bool)


def drawdown_signal(close: pd.Series, x: float, lookback: int = 252) -> pd.Series:
    high = close.rolling(lookback, min_periods=lookback).max()
    return (close <= (1 - x) * high).fillna(False).astype(bool)


def empirical_lower(close: pd.Series, window: int, q: float) -> pd.Series:
    # shift(1)：當日報酬不能參與當日分位數的估計。
    past = close.pct_change().shift(1)
    rq = past.rolling(window, min_periods=window).quantile(q)
    return close.shift(1) * (1 + rq)


def below(close: pd.Series, lower: pd.Series) -> pd.Series:
    return (close < lower).fillna(False).astype(bool)

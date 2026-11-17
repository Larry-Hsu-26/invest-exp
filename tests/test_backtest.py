import numpy as np
import pandas as pd
import pytest

from invest_exp.backtest import deposit_days, simulate, xirr


def _close(values, start="2021-01-01") -> pd.Series:
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def _signal(close: pd.Series, true_days=()) -> pd.Series:
    s = pd.Series(False, index=close.index)
    for d in true_days:
        s.iloc[d] = True
    return s


def test_deposit_days_first_trading_day_each_month():
    idx = pd.bdate_range("2021-01-01", "2021-03-31")
    days = deposit_days(idx, idx[0], idx[-1])
    assert list(days) == [pd.Timestamp("2021-01-01"), pd.Timestamp("2021-02-01"), pd.Timestamp("2021-03-01")]


def test_dca_buys_on_deposit_day():
    close = _close(np.linspace(100, 130, 45))
    always = pd.Series(True, index=close.index)
    r = simulate(close, always, close.index[0], close.index[-1], amount=100.0, fee=0.0)
    assert list(r.trades["date"]) == list(deposit_days(close.index, close.index[0], close.index[-1]))
    assert r.cash == 0.0


def test_no_signal_keeps_cash_in_final_value():
    close = _close(np.linspace(100, 130, 45))
    r = simulate(close, _signal(close), close.index[0], close.index[-1], amount=100.0, fee=0.0)
    assert r.units == 0.0
    assert r.final_value == pytest.approx(r.contributed)
    assert r.cash_ratio == pytest.approx(1.0)


def test_buys_all_pending_cash_once():
    close = _close(np.full(45, 100.0))
    # 兩次存入（1/1、2/1）都在等，2/10 第一次訊號，一次買完。
    buy_day = close.index.get_loc(pd.Timestamp("2021-02-10"))
    r = simulate(close, _signal(close, [buy_day]), close.index[0], close.index[-1], amount=100.0, fee=0.0)
    assert r.n_buys == 1
    assert r.units == pytest.approx(2.0)
    assert r.trades["amount"].tolist() == [200.0]


def test_signal_before_deposit_does_not_buy_that_deposit():
    close = _close(np.full(30, 100.0))  # 1/1–2/11：只有兩次存入
    pre = close.index.get_loc(pd.Timestamp("2021-01-29"))
    r = simulate(close, _signal(close, [0, pre]), close.index[0], close.index[-1], amount=100.0, fee=0.0)
    # 1/1 存入當天買；2/1 存入後沒有訊號，留著現金。
    assert r.units == pytest.approx(1.0)
    assert r.cash == pytest.approx(100.0)


def test_fee_reduces_units():
    close = _close(np.full(5, 100.0))
    always = pd.Series(True, index=close.index)
    r = simulate(close, always, close.index[0], close.index[-1], amount=100.0, fee=0.01)
    assert r.units == pytest.approx(0.99)


def test_lag_one_buys_next_day_close():
    close = _close([100.0, 50.0, 80.0, 90.0, 95.0])
    r = simulate(close, _signal(close, [1]), close.index[0], close.index[-1], amount=100.0, fee=0.0, lag=1)
    # 第 2 天訊號，第 3 天收盤 80 買。
    assert r.trades["date"].tolist() == [close.index[2]]
    assert r.units == pytest.approx(100.0 / 80.0)


def test_window_ignores_days_outside_range():
    close = _close(np.full(70, 100.0))
    start = pd.Timestamp("2021-02-01")
    r = simulate(close, pd.Series(True, index=close.index), start, close.index[-1], amount=100.0, fee=0.0)
    assert r.contributed == 300.0
    assert r.trades["date"].min() >= start


def test_xirr_known_answer():
    flows = [(pd.Timestamp("2020-01-01"), -100.0), (pd.Timestamp("2020-12-31"), 110.0)]
    # 2020 是閏年，相隔 365 天；以 365 天為一年。
    assert xirr(flows) == pytest.approx(0.10, abs=1e-6)


def test_xirr_monthly_deposits_zero_growth():
    flows = [(pd.Timestamp(f"2020-{m:02d}-01"), -100.0) for m in range(1, 13)]
    flows.append((pd.Timestamp("2020-12-31"), 1200.0))
    assert xirr(flows) == pytest.approx(0.0, abs=1e-9)

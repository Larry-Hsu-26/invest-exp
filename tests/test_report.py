import pandas as pd
import pytest

from invest_exp import report


def test_mechanism_counts_unbought_deposits_at_window_end_close():
    idx = pd.bdate_range("2021-01-01", "2021-03-31")
    level = pd.Series(100.0, index=idx)
    level.loc["2021-02-10":] = 110.0
    level.iloc[-1] = 120.0
    start, end = idx[0], idx[-1]
    d1, d2 = pd.Timestamp("2021-01-01"), pd.Timestamp("2021-02-01")
    trades = pd.DataFrame(
        {
            "rule": ["B0", "B0", "X", "X"],
            "years": ["10"] * 4,
            "window_start": [start] * 4,
            "deposit_date": [d1, d2, d1, d2],
            # X：第一筆等到 2/10 用 110 買；第二筆到期末都沒買。
            "buy_date": [d1, d2, pd.Timestamp("2021-02-10"), pd.NaT],
            "buy_close": [100.0, 100.0, 110.0, float("nan")],
        }
    )
    windows = pd.DataFrame(
        {
            "rule": ["B0", "X"],
            "years": ["10", "10"],
            "start": [start, start],
            "end": [end, end],
            "cash_ratio": [0.0, 0.4],
            "final_value": [240.0, 200.0],
            "contributed": [200.0, 200.0],
        }
    )
    m = {r["rule"]: r for r in report.mechanism(trades, windows, level, ["B0", "X"])}
    # 同一批存款：Σ(1/存入日收盤) ÷ Σ(1/實際價格) − 1，沒買的以期末收盤 120 計。
    assert m["X"]["cost_vs_b0"] == pytest.approx((2 / 100 / (1 / 110 + 1 / 120) - 1) * 100, abs=0.01)
    assert m["X"]["cheaper"] == pytest.approx(0.0)
    assert m["X"]["unbought"] == pytest.approx(1.0)
    assert m["X"]["wait"] == pytest.approx(((pd.Timestamp("2021-02-10") - d1).days + (end - d2).days) / 2)
    assert m["B0"]["cost_vs_b0"] == pytest.approx(0.0)

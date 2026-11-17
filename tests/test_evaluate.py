import numpy as np
import pandas as pd
import pytest

from invest_exp.evaluate import first_eligible_month, pinball, summarize, window_spans


def test_window_spans_fit_inside_complete_months():
    idx = pd.bdate_range("2003-01-01", "2014-03-14")
    spans = window_spans(idx, pd.Timestamp("2003-01-01"), years=10)
    starts = [s for s, _ in spans]
    # 2014-03 不完整，最後一個窗口要在 2014-02 結束 → 起點最晚 2004-03。
    assert starts[0] == pd.Timestamp("2003-01-01")
    assert starts[-1] == pd.Timestamp("2004-03-01")
    assert all(e <= pd.Timestamp("2014-02-28") for _, e in spans)
    first_end = spans[0][1]
    assert first_end == pd.Timestamp("2012-12-31")


def test_first_eligible_month_not_before_tr_or_ready():
    idx = pd.bdate_range("2002-01-01", "2004-12-31")
    month = first_eligible_month(idx, tr_start=pd.Timestamp("2003-01-02"), ready=[pd.Timestamp("2003-02-17")])
    # 第一次存入日必須晚於所有規則都有訊號的那天 → 2003-03 的第一個交易日。
    assert month == pd.Timestamp("2003-03-03")


def test_pinball_known_answer():
    actual = np.array([0.0, 0.0])
    lower = np.array([0.1, -0.1])
    # 實際低於預測：(0.1−0)×(1−0.1)=0.09；高於：(0−(−0.1))×0.1=0.01 → 平均 0.05
    assert pinball(actual, lower, 0.1) == pytest.approx(0.05)


def test_summarize_win_rate_and_excess():
    rows = []
    for i, (a, b) in enumerate([(110, 100), (90, 100), (120, 100)]):
        rows.append({"rule": "A", "years": 10, "start": i, "final_value": a})
        rows.append({"rule": "B", "years": 10, "start": i, "final_value": b})
    df = summarize(pd.DataFrame(rows), opponents=["B"])
    row = df[(df["rule"] == "A") & (df["opponent"] == "B")].iloc[0]
    assert row["win_rate"] == pytest.approx(2 / 3)
    assert row["excess_median"] == pytest.approx(0.10)
    assert row["n_windows"] == 3

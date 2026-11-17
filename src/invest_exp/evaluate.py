"""滾動窗口回測、彙總、預測校準與隨機進場對照。"""

import numpy as np
import pandas as pd

from invest_exp.backtest import deposit_days, simulate_arrays, xirr


def _month_firsts(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.Series(index, index=index).groupby([index.year, index.month]).first().to_numpy())


def _month_lasts(index: pd.DatetimeIndex) -> pd.Series:
    s = pd.Series(index, index=index).groupby([index.year, index.month]).last()
    return s


def first_eligible_month(index: pd.DatetimeIndex, tr_start: pd.Timestamp, ready: list[pd.Timestamp]) -> pd.Timestamp:
    threshold = max([tr_start, *ready])
    firsts = _month_firsts(index)
    return firsts[firsts >= threshold][0]


def window_spans(
    index: pd.DatetimeIndex, first_day: pd.Timestamp, years: int | None
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """每月一個起點；years=None 為全期間單一窗口。最後一個月視為不完整，窗口不得結束在該月。"""
    if years is None:
        return [(first_day, index[-1])]
    lasts = _month_lasts(index)
    last_ym = (index[-1].year, index[-1].month)
    complete = {ym: d for ym, d in lasts.items() if ym < last_ym}
    spans = []
    for start in _month_firsts(index):
        if start < first_day:
            continue
        m = start.year * 12 + start.month - 1 + 12 * years - 1
        ym = (m // 12, m % 12 + 1)
        if ym not in complete:
            break
        spans.append((start, complete[ym]))
    return spans


def pinball(actual: np.ndarray, lower: np.ndarray, q: float) -> float:
    diff = actual - lower
    return float(np.where(diff >= 0, diff * q, -diff * (1 - q)).mean())


def run_windows(
    close: pd.Series,
    nxt_by_rule: dict[str, np.ndarray],
    spans_by_years: dict[int | None, list[tuple[pd.Timestamp, pd.Timestamp]]],
    amount: float,
    fee: float,
    keep_trades: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    idx = close.index
    arr = close.to_numpy(dtype=float)
    rows, trades = [], []
    for years, spans in spans_by_years.items():
        for start, end in spans:
            deps = deposit_days(idx, start, end)
            dep_idx = idx.get_indexer(deps)
            end_idx = int(idx.get_loc(end))
            for rule, nxt in nxt_by_rule.items():
                r = simulate_arrays(arr, nxt, dep_idx, end_idx, amount, fee)
                flows = [(d, -amount) for d in deps] + [(end, r["final_value"])]
                rows.append(
                    {
                        "rule": rule,
                        "years": "full" if years is None else years,
                        "start": start,
                        "end": end,
                        "final_value": r["final_value"],
                        "contributed": r["contributed"],
                        "units": r["units"],
                        "cash_end": r["cash"],
                        "n_buys": r["n_buys"],
                        "cash_ratio": r["cash_ratio"],
                        "max_cash": r["max_cash"],
                        "avg_cost": r["avg_cost"],
                        "xirr": xirr(flows),
                    }
                )
                if keep_trades:
                    buy, bought = r["buy_idx"], r["bought"]
                    trades.append(
                        pd.DataFrame(
                            {
                                "rule": rule,
                                "years": "full" if years is None else years,
                                "window_start": start,
                                "deposit_date": deps,
                                "buy_date": [idx[b] if ok else pd.NaT for b, ok in zip(buy, bought, strict=True)],
                                "buy_close": [arr[b] if ok else np.nan for b, ok in zip(buy, bought, strict=True)],
                            }
                        )
                    )
    return pd.DataFrame(rows), (pd.concat(trades, ignore_index=True) if keep_trades else None)


def summarize(results: pd.DataFrame, opponents: list[str]) -> pd.DataFrame:
    out = []
    for years, g in results.groupby("years", sort=False):
        wide = g.pivot(index="start", columns="rule", values="final_value")
        for rule in wide.columns:
            for opp in opponents:
                if opp == rule or opp not in wide.columns:
                    continue
                ex = wide[rule] / wide[opp] - 1
                out.append(
                    {
                        "years": years,
                        "rule": rule,
                        "opponent": opp,
                        "n_windows": int(ex.notna().sum()),
                        "win_rate": float((ex > 0).mean()),
                        "excess_median": float(ex.median()),
                        "excess_mean": float(ex.mean()),
                        "excess_p10": float(ex.quantile(0.1)),
                        "excess_p90": float(ex.quantile(0.9)),
                    }
                )
    return pd.DataFrame(out)


def calibration_table(close: pd.Series, lowers: dict[str, pd.Series], q: float, release: pd.Timestamp) -> pd.DataFrame:
    """以報酬表示：實際報酬與下界隱含報酬的覆蓋率、pinball loss；依年份與發布後期間。"""
    prev = close.shift(1)
    actual = close / prev - 1
    rows = []
    for name, lower in lowers.items():
        lr = (lower / prev - 1).dropna()
        a = actual.reindex(lr.index)
        periods = {str(y): lr.index.year == y for y in sorted(set(lr.index.year))}
        periods["all"] = np.ones(len(lr), dtype=bool)
        periods["pre-release"] = lr.index < release
        periods["post-release"] = lr.index >= release
        for period, mask in periods.items():
            if mask.sum() == 0:
                continue
            rows.append(
                {
                    "model": name,
                    "q": q,
                    "period": period,
                    "n": int(mask.sum()),
                    "hit_rate": float((a[mask] < lr[mask]).mean()),
                    "pinball": pinball(a[mask].to_numpy(), lr[mask].to_numpy(), q),
                }
            )
    return pd.DataFrame(rows)


def random_control(
    close: pd.Series,
    p: float,
    spans: list[tuple[pd.Timestamp, pd.Timestamp]],
    amount: float,
    fee: float,
    n: int,
    seed: int,
) -> np.ndarray:
    """n 組每天以機率 p 觸發的隨機規則，各窗口的期末資產（n × 窗口數）。"""
    from invest_exp.backtest import next_true

    idx = close.index
    arr = close.to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    prepared = []
    for start, end in spans:
        dep_idx = idx.get_indexer(deposit_days(idx, start, end))
        prepared.append((dep_idx, int(idx.get_loc(end))))
    out = np.empty((n, len(spans)))
    for i in range(n):
        nxt = next_true(rng.random(len(arr)) < p)
        for j, (dep_idx, end_idx) in enumerate(prepared):
            out[i, j] = simulate_arrays(arr, nxt, dep_idx, end_idx, amount, fee)["final_value"]
    return out

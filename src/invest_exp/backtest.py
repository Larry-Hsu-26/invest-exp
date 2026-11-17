"""只買不賣的回測：每月存入，訊號日把累積的現金全部買進。

「條件成立就買全部現金」等價於每筆存款在存入日（含）之後的第一個執行日買進，
各筆存款互不影響，所以可以整批向量化計算。
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import brentq


@dataclass(frozen=True)
class Result:
    final_value: float
    contributed: float
    units: float
    cash: float
    n_buys: int
    cash_ratio: float
    max_cash: float
    avg_cost: float
    trades: pd.DataFrame
    flows: list[tuple[pd.Timestamp, float]]


def deposit_days(index: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    days = index[(index >= start) & (index <= end)]
    first = pd.Series(days, index=days).groupby([days.year, days.month]).first()
    return pd.DatetimeIndex(first.to_numpy())


def next_true(flags: np.ndarray) -> np.ndarray:
    """每個位置 i：i（含）之後第一個 True 的位置；沒有則為 len(flags)。"""
    n = len(flags)
    out = np.full(n + 1, n, dtype=np.int64)
    for i in range(n - 1, -1, -1):
        out[i] = i if flags[i] else out[i + 1]
    return out[:n]


def execution_flags(signal: pd.Series, lag: int) -> np.ndarray:
    # lag=1：第 t 天的訊號在 t+1 天收盤成交。
    return signal.shift(lag, fill_value=False).to_numpy(dtype=bool)


def simulate_arrays(
    close: np.ndarray, nxt: np.ndarray, dep_idx: np.ndarray, end_idx: int, amount: float, fee: float
) -> dict:
    buy = nxt[dep_idx]
    bought = buy <= end_idx
    units_k = np.where(bought, amount * (1 - fee) / close[np.minimum(buy, len(close) - 1)], 0.0)
    units = float(units_k.sum())
    cash = float(amount * (~bought).sum())
    start_idx = int(dep_idx[0])
    span = end_idx - start_idx + 1
    # 每筆存款在 [存入日, 買進日) 之間是現金；買進日收盤後變成單位。
    cash_diff = np.zeros(span + 1)
    unit_diff = np.zeros(span + 1)
    np.add.at(cash_diff, dep_idx - start_idx, amount)
    leave = np.where(bought, buy, end_idx + 1) - start_idx
    np.add.at(cash_diff, leave, -amount)
    np.add.at(unit_diff, np.where(bought, buy, end_idx + 1) - start_idx, units_k)
    cash_t = np.cumsum(cash_diff)[:span]
    units_t = np.cumsum(unit_diff)[:span]
    value_t = cash_t + units_t * close[start_idx : end_idx + 1]
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio_t = np.where(value_t > 0, cash_t / value_t, 0.0)
    spent = amount * bought.sum()
    return {
        "final_value": units * float(close[end_idx]) + cash,
        "contributed": amount * len(dep_idx),
        "units": units,
        "cash": cash,
        "n_buys": int(len(np.unique(buy[bought]))),
        "cash_ratio": float(ratio_t.mean()),
        "max_cash": float(cash_t.max()),
        "avg_cost": float(spent / units) if units > 0 else float("nan"),
        "buy_idx": buy,
        "bought": bought,
    }


def simulate(
    close: pd.Series,
    signal: pd.Series,
    start: pd.Timestamp,
    end: pd.Timestamp,
    amount: float,
    fee: float,
    lag: int = 0,
) -> Result:
    idx = close.index
    deps = deposit_days(idx, start, end)
    dep_idx = idx.get_indexer(deps)
    end_idx = int(idx.get_indexer([idx[idx <= end][-1]])[0])
    nxt = next_true(execution_flags(signal.reindex(idx, fill_value=False), lag))
    r = simulate_arrays(close.to_numpy(dtype=float), nxt, dep_idx, end_idx, amount, fee)
    buy_idx, bought = r["buy_idx"], r["bought"]
    per_day = pd.Series(amount, index=buy_idx[bought]).groupby(level=0).sum()
    trades = pd.DataFrame(
        {
            "date": idx[per_day.index.to_numpy()],
            "amount": per_day.to_numpy(),
            "close": close.to_numpy()[per_day.index.to_numpy()],
        }
    )
    trades["units"] = trades["amount"] * (1 - fee) / trades["close"]
    flows = [(d, -amount) for d in deps] + [(idx[end_idx], r["final_value"])]
    return Result(
        final_value=r["final_value"],
        contributed=r["contributed"],
        units=r["units"],
        cash=r["cash"],
        n_buys=r["n_buys"],
        cash_ratio=r["cash_ratio"],
        max_cash=r["max_cash"],
        avg_cost=r["avg_cost"],
        trades=trades,
        flows=flows,
    )


def xirr(flows: list[tuple[pd.Timestamp, float]]) -> float:
    t0 = flows[0][0]
    years = np.array([(d - t0).days / 365.0 for d, _ in flows])
    amounts = np.array([a for _, a in flows])

    def npv(rate: float) -> float:
        return float((amounts / (1 + rate) ** years).sum())

    return float(brentq(npv, -0.99, 10.0, xtol=1e-12))

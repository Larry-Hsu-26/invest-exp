"""每日的分位數下界：Timestral-209M（預測收盤）與 GARCH(1,1)-t（預測報酬）。

第 t 天的預測只用 t−1 以前的資料；結果存檔，規則只讀存檔。
"""

import warnings

import numpy as np
import pandas as pd
from arch import arch_model

TIMESTRAL_REPO = "mistralai/Timestral-209M"
TIMESTRAL_REVISION = "9874d252ab0aae16f7f7c999f98f98d6ad7d8365"


def qcol(q: float) -> str:
    return f"q{q:g}"


def context_windows(level: np.ndarray, context: int) -> tuple[np.ndarray, np.ndarray]:
    """第 t 天（t ≥ context）的 context 是 level[t−context : t]，不含 t。"""
    windows = np.lib.stride_tricks.sliding_window_view(level, context)[:-1]
    return np.arange(context, len(level)), windows


def load_timestral():
    from timestral import TimestralForecaster

    return TimestralForecaster.from_pretrained(TIMESTRAL_REPO, revision=TIMESTRAL_REVISION, device="cpu")


def timestral_forecasts(level: pd.Series, context: int, model, batch: int = 64, log_every: int = 20) -> pd.DataFrame:
    targets, windows = context_windows(level.to_numpy(dtype=float), context)
    levels = model.quantile_levels
    out = np.empty((len(targets), len(levels)))
    for b, start in enumerate(range(0, len(targets), batch)):
        chunk = np.ascontiguousarray(windows[start : start + batch])
        fc = model.forecast(chunk, prediction_length=1)
        out[start : start + len(chunk)] = fc.quantiles[:, 0, 0, :].numpy()
        if b % log_every == 0:
            print(f"[timestral C={context}] {start + len(chunk)}/{len(targets)}", flush=True)
    df = pd.DataFrame(out, index=level.index[targets], columns=[qcol(q) for q in levels])
    df.index.name = "date"
    df.insert(0, "context_end", level.index[targets - 1])
    return df


def garch_lower(
    close: pd.Series, qs: tuple[float, ...], window: int = 1008, targets: pd.DatetimeIndex | None = None
) -> pd.DataFrame:
    returns = close.pct_change() * 100
    positions = np.arange(window + 1, len(close)) if targets is None else close.index.get_indexer(targets)
    # get_indexer 對不存在的日期回 −1，iloc[-1-window:-1] 會取到序列尾端（未來）的資料。
    if (positions < window + 1).any():
        raise ValueError("garch targets need a full window of past returns inside the series")
    rows, params = [], None
    for p in positions:
        sample = returns.iloc[p - window : p]
        model = arch_model(sample, mean="Constant", vol="GARCH", p=1, q=1, dist="t", rescale=False)
        with warnings.catch_warnings():
            # 收斂失敗不中斷，記在 converged 欄位，報告裡列出比例。
            warnings.simplefilter("ignore")
            res = model.fit(disp="off", show_warning=False, starting_values=params)
        params = res.params.to_numpy()
        var = float(res.forecast(horizon=1, reindex=False).variance.iloc[-1, 0])
        mu, nu = float(res.params["mu"]), float(res.params["nu"])
        row = {"date": close.index[p], "converged": res.convergence_flag == 0}
        prev = float(close.iloc[p - 1])
        for q in qs:
            z = float(model.distribution.ppf(q, [nu]))
            row[qcol(q)] = prev * (1 + (mu + np.sqrt(var) * z) / 100)
        rows.append(row)
    return pd.DataFrame(rows).set_index("date")

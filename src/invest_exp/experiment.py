"""實驗主程式：forecasts（Timestral、GARCH 預測存檔）→ evaluate（訊號、回測、彙總、校準、隨機對照）。

一次執行寫進 runs/<run_id>/，不覆蓋；manifest.json 記錄版本、設定與每個檔案的 SHA256。
"""

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from invest_exp import backtest, evaluate, forecast, rules
from invest_exp.data import load_series, splice

RAW = Path("data/raw/twse")
PROCESSED = Path("data/processed")
RUNS = Path("runs")
AMOUNT = 20_000.0
FEE = 0.001425
RELEASE = pd.Timestamp("2026-10-14")
QS = (0.10, 0.05)
CONTEXTS = (512, 1024, 2048)
GARCH_WINDOW = 1008
MAIN = {"F": "F_C1024_q10", "Q": "Q_W252_q10", "G": "G_q10", "B1": "B1_MA240", "B2": "B2_DD10", "B0": "B0"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qtag(q: float) -> str:
    return f"q{round(q * 100):02d}"


def git_commit() -> tuple[str, bool]:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "src"], capture_output=True, text=True).stdout)
    return commit, dirty


def build_series() -> dict[str, pd.DataFrame]:
    price = load_series(RAW, "MI_5MINS_HIST")
    tr = load_series(RAW, "MFI94U")
    PROCESSED.mkdir(parents=True, exist_ok=True)
    tr_spliced = splice(price, tr)
    price_df = pd.DataFrame({"level": price, "is_tr": False})
    price_df.index.name = "date"
    tr_spliced.to_csv(PROCESSED / "taiex_tr_spliced.csv")
    price_df.to_csv(PROCESSED / "taiex_price.csv")
    return {"tr": tr_spliced, "price": price_df}


SERIES_FILES = {"tr": "taiex_tr_spliced.csv", "price": "taiex_price.csv"}


def _read_series(folder: Path) -> dict[str, pd.DataFrame]:
    return {k: pd.read_csv(folder / f, index_col="date", parse_dates=True) for k, f in SERIES_FILES.items()}


def load_run_series(run: Path) -> dict[str, pd.DataFrame]:
    """run 只讀自己的快照：之後重抓資料會改寫 data/processed，舊 run 不能跟著變。"""
    snap = run / "data"
    if not snap.exists():
        # 快照機制之前的 run：全域檔與 manifest 記錄的 SHA256 相符才補快照，否則中止。
        manifest = run / "manifest.json"
        recorded = json.loads(manifest.read_text()).get("data_files", {}) if manifest.exists() else {}
        for f in SERIES_FILES.values():
            src = PROCESSED / f
            if recorded.get(str(src)) != sha256(src):
                raise ValueError(f"{src}: sha256 does not match {manifest}; cannot reconstruct run snapshot")
        snap.mkdir(parents=True)
        for f in SERIES_FILES.values():
            shutil.copy2(PROCESSED / f, snap / f)
    return _read_series(snap)


def price_complete(series: dict[str, pd.DataFrame]) -> bool:
    # 價格指數端點曾被證交所單獨擋住；沒抓到與報酬指數相同的最後一天，就不做不含息版本。
    return series["price"].index.max() >= series["tr"].index.max()


def stage_forecasts(run: Path) -> None:
    """只算還沒有的預測檔，可在同一個 run 補做；補做時沿用 run 的資料快照，不混進新資料。"""
    if not (run / "data").exists():
        build_series()
        (run / "data").mkdir(parents=True)
        for f in SERIES_FILES.values():
            shutil.copy2(PROCESSED / f, run / "data" / f)
    series = _read_series(run / "data")
    out = run / "forecasts"
    out.mkdir(parents=True, exist_ok=True)
    timing_path = out / "timing.json"
    timing = json.loads(timing_path.read_text()) if timing_path.exists() else {}
    jobs = [("tr", c) for c in CONTEXTS]
    garch_jobs = ["tr"]
    if price_complete(series):
        jobs.append(("price", 1024))
        garch_jobs.append("price")
        timing.pop("price_skipped", None)
    else:
        timing["price_skipped"] = (
            f"price index ends {series['price'].index.max().date()}, tr ends {series['tr'].index.max().date()}"
        )
    model = None
    for name, c in jobs:
        path = out / f"timestral_{name}_C{c}.csv"
        if path.exists():
            continue
        if model is None:
            torch.manual_seed(0)
            model = forecast.load_timestral()
        t = time.time()
        forecast.timestral_forecasts(series[name]["level"], context=c, model=model).to_csv(path)
        timing[f"timestral_{name}_C{c}"] = round(time.time() - t, 1)
        timing_path.write_text(json.dumps(timing, indent=2))
    for name in garch_jobs:
        path = out / f"garch_{name}.csv"
        if path.exists():
            continue
        t = time.time()
        forecast.garch_lower(series[name]["level"], qs=QS, window=GARCH_WINDOW).to_csv(path)
        timing[f"garch_{name}"] = round(time.time() - t, 1)
        timing_path.write_text(json.dumps(timing, indent=2))
    timing_path.write_text(json.dumps(timing, indent=2))


def build_signals(close: pd.Series, fdir: Path, name: str) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    sig, lowers = {}, {}
    sig["B0"] = pd.Series(True, index=close.index)
    for n in (20, 60, 120, 240):
        sig[f"B1_MA{n}"] = rules.ma_signal(close, n)
    for x in (5, 10, 15, 20):
        sig[f"B2_DD{x}"] = rules.drawdown_signal(close, x / 100)
    for w in (252, 1008):
        for q in QS:
            lowers[f"Q_W{w}_{qtag(q)}"] = rules.empirical_lower(close, w, q)
    g = pd.read_csv(fdir / f"garch_{name}.csv", index_col="date", parse_dates=True)
    for q in QS:
        lowers[f"G_{qtag(q)}"] = g[forecast.qcol(q)].reindex(close.index)
    contexts = CONTEXTS if name == "tr" else (1024,)
    for c in contexts:
        f = pd.read_csv(fdir / f"timestral_{name}_C{c}.csv", index_col="date", parse_dates=True)
        for q in QS:
            lowers[f"F_C{c}_{qtag(q)}"] = f[forecast.qcol(q)].reindex(close.index)
    for key, lower in lowers.items():
        sig[key] = rules.below(close, lower)
    return pd.DataFrame(sig), lowers


def ready_date(rule: str, lowers: dict[str, pd.Series], close: pd.Series) -> pd.Timestamp:
    if rule in lowers:
        return lowers[rule].first_valid_index()
    n = {"B0": 1, "B1_MA20": 20, "B1_MA60": 60, "B1_MA120": 120, "B1_MA240": 240}.get(rule, 252)
    return close.index[n - 1]


def stage_evaluate(run: Path, n_random: int) -> None:
    out = run / "results"
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} already has results; 不覆蓋舊結果，請開新的 run")
    series = load_run_series(run)
    fdir = run / "forecasts"
    out.mkdir(parents=True, exist_ok=True)
    tr_start = series["tr"].index[series["tr"]["is_tr"]].min()
    meta = {}
    scenarios = {
        "main": ("tr", FEE, 0),
        "fee0": ("tr", 0.0, 0),
        "lag1": ("tr", FEE, 1),
        "price_index": ("price", FEE, 0),
    }
    if not (fdir / "timestral_price_C1024.csv").exists():
        del scenarios["price_index"]
        meta["price_index"] = "skipped: no price-index forecasts (price data incomplete)"
    all_results, signals_saved = [], set()
    for scen, (name, fee, lag) in scenarios.items():
        close = series[name]["level"]
        sig, lowers = build_signals(close, fdir, name)
        if name not in signals_saved:
            sig.astype(int).to_csv(out / f"signals_{name}.csv")
            pd.DataFrame(lowers).to_csv(out / f"lowers_{name}.csv")
            signals_saved.add(name)
        # C2048 要到 2007 年才有訊號，主窗口不含它，另在自己的起點評估（scenario c2048）。
        main_rules = [r for r in sig.columns if "C2048" not in r]
        first = evaluate.first_eligible_month(close.index, tr_start, [ready_date(r, lowers, close) for r in main_rules])
        spans = {y: evaluate.window_spans(close.index, first, y) for y in (10, 20, None)}
        nxt = {r: backtest.next_true(backtest.execution_flags(sig[r], lag)) for r in main_rules}
        res, trades = evaluate.run_windows(close, nxt, spans, AMOUNT, fee, keep_trades=(scen == "main"))
        res.insert(0, "scenario", scen)
        all_results.append(res)
        meta[scen] = {
            "series": name,
            "fee": fee,
            "lag": lag,
            "first_month": str(first.date()),
            "n_windows": {str(k): len(v) for k, v in spans.items()},
        }
        if trades is not None:
            trades.to_csv(out / "trades_main.csv.gz", index=False)
        if scen == "main":
            main_spans, main_close, main_sig, main_first = spans, close, sig, first
            cal = pd.concat(
                [
                    evaluate.calibration_table(
                        close, {k: v for k, v in lowers.items() if k.endswith(qtag(q))}, q, RELEASE
                    )
                    for q in QS
                ],
                ignore_index=True,
            )
            cal.to_csv(out / "calibration.csv", index=False)
            # 觸發率：主窗口期間（第一個存入日之後）每天條件成立的比例。
            rate = main_sig.loc[main_first:].mean().rename("trigger_rate")
            rate.to_csv(out / "trigger_rates.csv")
        if scen == "main" and "F_C2048_q10" in sig.columns:
            rules2048 = list(sig.columns)
            first2 = evaluate.first_eligible_month(
                close.index, tr_start, [ready_date(r, lowers, close) for r in rules2048]
            )
            spans2 = {y: evaluate.window_spans(close.index, first2, y) for y in (10, None)}
            nxt2 = {r: backtest.next_true(backtest.execution_flags(sig[r], 0)) for r in rules2048}
            res2, _ = evaluate.run_windows(close, nxt2, spans2, AMOUNT, fee)
            res2.insert(0, "scenario", "c2048")
            all_results.append(res2)
            meta["c2048"] = {
                "series": name,
                "fee": fee,
                "lag": 0,
                "first_month": str(first2.date()),
                "n_windows": {str(k): len(v) for k, v in spans2.items()},
            }
    results = pd.concat(all_results, ignore_index=True)
    results.to_csv(out / "windows.csv", index=False)
    summaries = []
    for scen, g in results.groupby("scenario", sort=False):
        s = evaluate.summarize(g, opponents=sorted(g["rule"].unique()))
        s.insert(0, "scenario", scen)
        summaries.append(s)
    pd.concat(summaries, ignore_index=True).to_csv(out / "summary.csv", index=False)

    rand_rows = []
    for key in ("F_C1024_q10", "F_C1024_q05"):
        p = float(rate[key])
        for years, spans in main_spans.items():
            mat = evaluate.random_control(main_close, p, spans, AMOUNT, FEE, n=n_random, seed=20261117)
            f_vals = results[
                (results["scenario"] == "main")
                & (results["rule"] == key)
                & (results["years"] == ("full" if years is None else years))
            ]["final_value"].to_numpy()
            b0 = results[
                (results["scenario"] == "main")
                & (results["rule"] == "B0")
                & (results["years"] == ("full" if years is None else years))
            ]["final_value"].to_numpy()
            for j, (start, end) in enumerate(spans):
                rand_rows.append(
                    {
                        "rule": key,
                        "years": "full" if years is None else years,
                        "start": start,
                        "end": end,
                        "p": p,
                        "f_final": f_vals[j],
                        "b0_final": b0[j],
                        "random_median": float(np.median(mat[:, j])),
                        "random_p10": float(np.quantile(mat[:, j], 0.1)),
                        "random_p90": float(np.quantile(mat[:, j], 0.9)),
                        "f_percentile": float((mat[:, j] < f_vals[j]).mean()),
                    }
                )
    pd.DataFrame(rand_rows).to_csv(out / "random_control.csv", index=False)
    (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))


def write_manifest(run: Path, args: argparse.Namespace, started: str, code: tuple[str, bool] | None = None) -> None:
    # 執行期間可能有新 commit 進來；記錄階段開始時的版本才對得上實際跑的程式碼。
    commit, dirty = code if code is not None else git_commit()
    files = {
        str(p.relative_to(run)): sha256(p) for p in sorted(run.rglob("*")) if p.is_file() and p.name != "manifest.json"
    }
    data_files = {str(p): sha256(p) for p in sorted(PROCESSED.glob("*.csv"))}
    raw_log = RAW / "fetch_log.csv"
    path = run / "manifest.json"
    # 同一個 run 分階段執行時，保留每個階段的紀錄，不覆蓋。
    stages = json.loads(path.read_text())["stages"] if path.exists() else []
    stages.append(
        {
            "stage": args.stage,
            "started_utc": started,
            "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "command": vars(args),
            "git_commit": commit,
            "src_dirty": dirty,
        }
    )
    manifest = {
        "run_id": run.name,
        "stages": stages,
        "python": platform.python_version(),
        "packages": {p: version(p) for p in ("torch", "timestral", "arch", "pandas", "numpy", "scipy")},
        "timestral": {
            "repo": forecast.TIMESTRAL_REPO,
            "revision": forecast.TIMESTRAL_REVISION,
            "code_commit": "a534bdbd244d64f3d9d743f46c7bf6fc330ed4ff",
            "symmetric_averaging": True,
        },
        "torch_threads": torch.get_num_threads(),
        "config": {
            "amount": AMOUNT,
            "fee": FEE,
            "quantiles": QS,
            "contexts": CONTEXTS,
            "garch_window": GARCH_WINDOW,
            "release": str(RELEASE.date()),
            "main": MAIN,
        },
        "raw_fetch_log_sha256": sha256(raw_log) if raw_log.exists() else None,
        "data_files": data_files,
        "files": files,
    }
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="時序分位數進場規則實驗")
    ap.add_argument("stage", choices=["forecasts", "evaluate", "all"])
    ap.add_argument("--run", help="run 目錄名稱；evaluate 時指定要評估的 run")
    ap.add_argument("--n-random", type=int, default=500)
    args = ap.parse_args(argv)
    started = datetime.now(UTC).isoformat(timespec="seconds")
    code = git_commit()
    run = RUNS / (args.run or f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{code[0][:7]}")
    run.mkdir(parents=True, exist_ok=True)
    if args.stage in ("forecasts", "all"):
        stage_forecasts(run)
    if args.stage in ("evaluate", "all"):
        stage_evaluate(run, args.n_random)
    write_manifest(run, args, started, code)
    print(f"[experiment] done: {run}", flush=True)


if __name__ == "__main__":
    main()

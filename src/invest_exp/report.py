"""從 runs/<run_id>/ 產生單一 HTML 報告；所有數字都來自 run 目錄的檔案。"""

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

MAIN_F = "F_C1024_q10"
OPPONENTS = [
    ("H1", "Q_W252_q10", "滾動經驗分位數（不用模型）"),
    ("H2", "G_q10", "GARCH-t（經典統計模型）"),
    ("H3a", "B1_MA240", "跌破 240 日均線"),
    ("H3b", "B2_DD10", "一年高點回檔 10%"),
    ("H4", "B0", "定期定額"),
]
PATH_RULES = ["B0", MAIN_F, "Q_W252_q10", "G_q10"]
SCENARIO_NAMES = {
    "main": "主設定",
    "fee0": "手續費 0",
    "lag1": "隔日收盤成交",
    "price_index": "價格指數（不含息）",
    "c2048": "Timestral C=2048 的起點",
}


def rule_name(rule: str) -> str:
    if rule == "B0":
        return "定期定額"
    if m := re.fullmatch(r"B1_MA(\d+)", rule):
        return f"跌破 {m[1]} 日均線"
    if m := re.fullmatch(r"B2_DD(\d+)", rule):
        return f"一年高點回檔 {m[1]}%"
    if m := re.fullmatch(r"Q_W(\d+)_q(\d+)", rule):
        return f"經驗分位數 {m[1]} 日 q0.{m[2]}"
    if m := re.fullmatch(r"G_q(\d+)", rule):
        return f"GARCH-t q0.{m[1]}"
    if m := re.fullmatch(r"F_C(\d+)_q(\d+)", rule):
        return f"Timestral C{m[1]} q0.{m[2]}"
    return rule


def _f(x: float, digits: int = 1) -> float | None:
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), digits)


def value_paths(trades: pd.DataFrame, level: pd.Series, amount: float, fee: float) -> dict:
    """全期間窗口：由每筆存入的買進日重建每天的資產。"""
    full = trades[trades["years"] == "full"]
    start = pd.Timestamp(full["deposit_date"].min())
    lv = level.loc[start:]
    out = {"dates": [d.strftime("%Y-%m-%d") for d in lv.index], "level": [round(v, 2) for v in lv]}
    for rule in PATH_RULES:
        t = full[full["rule"] == rule]
        dep = pd.to_datetime(t["deposit_date"])
        buy = pd.to_datetime(t["buy_date"])
        cash = pd.Series(0.0, index=lv.index)
        units = pd.Series(0.0, index=lv.index)
        for d, b, c in zip(dep, buy, t["buy_close"], strict=True):
            cash.loc[d:] += amount
            if pd.notna(b):
                cash.loc[b:] -= amount
                units.loc[b:] += amount * (1 - fee) / c
        out[rule] = [round(v) for v in (cash + units * lv)]
        if rule == MAIN_F:
            bd = sorted(set(buy.dropna()))
            out["f_buys"] = {"dates": [d.strftime("%Y-%m-%d") for d in bd], "level": [round(lv.loc[d], 2) for d in bd]}
    return out


def build_data(run: Path, processed: Path = Path("data/processed")) -> dict:
    res = run / "results"
    manifest = json.loads((run / "manifest.json").read_text())
    meta = json.loads((res / "meta.json").read_text())
    windows = pd.read_csv(res / "windows.csv", parse_dates=["start", "end"])
    summary = pd.read_csv(res / "summary.csv")
    cal = pd.read_csv(res / "calibration.csv")
    rand = pd.read_csv(res / "random_control.csv", parse_dates=["start"])
    rates = pd.read_csv(res / "trigger_rates.csv", index_col=0)["trigger_rate"]
    trades = pd.read_csv(res / "trades_main.csv.gz", dtype={"years": str})
    level = pd.read_csv(processed / "taiex_tr_spliced.csv", index_col="date", parse_dates=True)["level"]
    amount, fee = manifest["config"]["amount"], manifest["config"]["fee"]

    def row(scen, years, rule, opp):
        s = summary[
            (summary["scenario"] == scen)
            & (summary["years"].astype(str) == str(years))
            & (summary["rule"] == rule)
            & (summary["opponent"] == opp)
        ]
        if s.empty:
            return None
        r = s.iloc[0]
        return {
            "win": _f(r["win_rate"] * 100),
            "median": _f(r["excess_median"] * 100, 2),
            "p10": _f(r["excess_p10"] * 100, 2),
            "p90": _f(r["excess_p90"] * 100, 2),
            "n": int(r["n_windows"]),
        }

    years_list = [y for y in ("10", "20", "full") if (windows["years"].astype(str) == y).any()]
    main_w = windows[windows["scenario"] == "main"]

    def diff_ntd(years, rule, opp):
        g = main_w[main_w["years"].astype(str) == years].pivot(index="start", columns="rule", values="final_value")
        return None if g.empty or opp not in g else _f((g[rule] - g[opp]).median(), 0)

    hyp = []
    for code, opp, label in OPPONENTS:
        cells = {}
        for y in years_list:
            c = row("main", y, MAIN_F, opp)
            if c:
                c["diff_ntd"] = diff_ntd(y, MAIN_F, opp)
            cells[y] = c
        hyp.append({"code": code, "opp": opp, "label": label, "cells": cells})

    # 機制：買得比較便宜（平均成本），但錢等比較久（閒置）；兩者相抵才是結果。
    mech = []
    w10 = main_w[main_w["years"].astype(str) == "10"]
    if not w10.empty:
        cost = w10.pivot(index="start", columns="rule", values="avg_cost")
        cash = w10.pivot(index="start", columns="rule", values="cash_ratio")
        fv = w10.pivot(index="start", columns="rule", values="final_value")
        for r in ["B0", MAIN_F, "Q_W252_q10", "G_q10", "B1_MA240", "B2_DD10"]:
            if r in cost:
                mech.append(
                    {
                        "rule": r,
                        "name": rule_name(r),
                        "cost_vs_b0": _f(((cost[r] / cost["B0"]) - 1).median() * 100, 2),
                        "cash": _f(cash[r].median() * 100, 1),
                        "excess": _f(((fv[r] / fv["B0"]) - 1).median() * 100, 2),
                        "final": _f(fv[r].median(), 0),
                        "contributed": _f(w10["contributed"].median(), 0),
                    }
                )
    r10 = rand[(rand["rule"] == MAIN_F) & (rand["years"].astype(str) == "10")]
    rand_summary = {
        y: {
            "median_pct": _f(g["f_percentile"].median() * 100),
            "share_above_half": _f((g["f_percentile"] > 0.5).mean() * 100),
            "n": len(g),
        }
        for y, g in rand[rand["rule"] == MAIN_F].groupby(rand["years"].astype(str))
    }

    main = windows[windows["scenario"] == "main"]
    rules = sorted(main["rule"].unique(), key=lambda r: (r[0] != "F", r[0] != "G", r[0] != "Q", r))
    table = []
    for rule in rules:
        rec = {"rule": rule, "name": rule_name(rule), "trigger": _f(rates.get(rule, np.nan) * 100)}
        for y in years_list:
            g = main[(main["rule"] == rule) & (main["years"].astype(str) == y)]
            vs = row("main", y, rule, "B0") if rule != "B0" else None
            rec[y] = {
                "xirr": _f(g["xirr"].median() * 100, 2),
                "cash": _f(g["cash_ratio"].median() * 100),
                "buys": _f(g["n_buys"].median(), 0),
                "vsB0": vs,
            }
        table.append(rec)

    box = {}
    for y in ("10", "20"):
        wide = main[main["years"].astype(str) == y].pivot(index="start", columns="rule", values="final_value")
        if wide.empty:
            continue
        box[y] = {
            r: [round((v - 1) * 100, 3) for v in (wide[r] / wide["B0"])]
            for r in [MAIN_F, "Q_W252_q10", "G_q10", "B1_MA240", "B2_DD10"]
            if r in wide
        }
        box[y]["starts"] = [d.strftime("%Y-%m") for d in wide.index]

    robust = []
    for scen in SCENARIO_NAMES:
        if not (windows["scenario"] == scen).any():
            robust.append({"scen": scen, "name": SCENARIO_NAMES[scen], "skipped": meta.get(scen, "")})
            continue
        y = "10"
        robust.append(
            {
                "scen": scen,
                "name": SCENARIO_NAMES[scen],
                "first": meta[scen]["first_month"],
                "cells": {opp: row(scen, y, MAIN_F, opp) for _, opp, _ in OPPONENTS},
            }
        )

    cal_q = {}
    for q in (0.1, 0.05):
        c = cal[np.isclose(cal["q"], q)].set_index(["model", "period"])
        tag = f"q{round(q * 100):02d}"
        models = [m for m in (f"F_C1024_{tag}", f"Q_W252_{tag}", f"G_{tag}") if m in c.index.get_level_values(0)]
        years_ = sorted({p for p in c.index.get_level_values(1) if p.isdigit()})

        def val(m, p, col, scale, digits, c=c):
            # 各模型開始有預測的年份不同（經驗分位數 2000 起、Timestral 2003 起），查不到就是空值。
            return _f(c.loc[(m, p), col] * scale, digits) if (m, p) in c.index else None

        cal_q[tag] = {
            "years": years_,
            "series": {m: [val(m, p, "hit_rate", 100, 2) for p in years_] for m in models},
            "summary": [
                {
                    "model": m,
                    "name": rule_name(m),
                    **{
                        p: {
                            "hit": val(m, p, "hit_rate", 100, 2),
                            "pinball": val(m, p, "pinball", 1e4, 3),
                            "n": int(c.loc[(m, p), "n"]),
                        }
                        for p in ("all", "pre-release", "post-release")
                        if (m, p) in c.index
                    },
                }
                for m in models
            ],
        }

    return {
        "run_id": manifest["run_id"],
        "n_random": next(
            st["command"].get("n_random") for st in reversed(manifest["stages"]) if st["stage"] in ("evaluate", "all")
        ),
        "git_commit": manifest["stages"][-1]["git_commit"],
        "finished": manifest["stages"][-1]["finished_utc"],
        "timestral": manifest["timestral"],
        "packages": manifest["packages"],
        "config": manifest["config"],
        "data_range": [level.index.min().strftime("%Y-%m-%d"), level.index.max().strftime("%Y-%m-%d")],
        "tr_start": meta["main"]["first_month"],
        "n_windows": meta["main"]["n_windows"],
        "years": years_list,
        "hyp": hyp,
        "mech": mech,
        "rand": rand_summary,
        "rand10": {
            "starts": [d.strftime("%Y-%m") for d in r10["start"]],
            "pct": [round(v * 100, 1) for v in r10["f_percentile"]],
        },
        "table": table,
        "box": box,
        "robust": robust,
        "cal": cal_q,
        "paths": value_paths(trades, level, amount, fee),
        "files": sorted(manifest["files"].keys()),
    }


def render(data: dict) -> str:
    template = (Path(__file__).parent / "report_template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return template.replace("__DATA__", payload.replace("</", "<\\/"))


PLOTLY_URL = "https://cdnjs.cloudflare.com/ajax/libs/plotly.js/2.35.3/plotly.min.js"


def standalone(html: str) -> tuple[str, str]:
    """把 plotly 內嵌進頁面：不連網也能開，供稽核留存。回傳 (html, plotly 的 SHA256)。"""
    import hashlib

    import requests

    js = requests.get(PLOTLY_URL, timeout=120).text
    digest = hashlib.sha256(js.encode("utf-8")).hexdigest()
    tag = f'<script src="{PLOTLY_URL}"></script>'
    assert html.count(tag) == 1
    return html.replace(tag, f"<script>/* {PLOTLY_URL} sha256 {digest} */\n{js}</script>"), digest


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="產生 HTML 報告")
    ap.add_argument("--run", required=True)
    args = ap.parse_args(argv)
    run = Path("runs") / args.run
    out = Path("reports")
    out.mkdir(parents=True, exist_ok=True)
    html = render(build_data(run))
    (out / f"{args.run}.html").write_text(html, encoding="utf-8")
    full, digest = standalone(html)
    (out / f"{args.run}.standalone.html").write_text(full, encoding="utf-8")
    print(f"[report] reports/{args.run}.html, standalone plotly sha256 {digest}", flush=True)


if __name__ == "__main__":
    main()

"""從 runs/<run_id>/ 產生單一 HTML 報告；所有數字都來自 run 目錄的檔案。"""

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from invest_exp import experiment

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


def mechanism(trades: pd.DataFrame, windows: pd.DataFrame, level: pd.Series, rules: list[str]) -> list[dict]:
    """每筆存款實際的買進價格對存入日收盤（＝定期定額的買價）；期末沒買的以窗口最後一天收盤計。

    只買不賣、現金不計息時，期末資產差距完全由同一批存款的買進價格決定。只看已買的會漏掉
    最貴的那幾筆（等到窗口結束都沒等到），成本會被低估。
    """
    t = trades.copy()
    for c in ("window_start", "deposit_date", "buy_date"):
        t[c] = pd.to_datetime(t[c])
    w = windows.copy()
    w["start"], w["end"] = pd.to_datetime(w["start"]), pd.to_datetime(w["end"])
    t = t.merge(w[["rule", "start", "end"]], left_on=["rule", "window_start"], right_on=["rule", "start"])
    t["dep_close"] = level.reindex(t["deposit_date"]).to_numpy()
    t["unbought"] = t["buy_close"].isna()
    t["price"] = t["buy_close"].fillna(pd.Series(level.reindex(t["end"]).to_numpy(), index=t.index))
    t["wait"] = (t["buy_date"].fillna(t["end"]) - t["deposit_date"]).dt.days
    per = t.groupby(["rule", "window_start"]).apply(
        lambda g: pd.Series(
            {
                "cost": (1 / g["dep_close"]).sum() / (1 / g["price"]).sum() - 1,
                "cheaper": (g["price"] < g["dep_close"]).mean(),
                "wait": g["wait"].mean(),
                "unbought": g["unbought"].sum(),
            }
        ),
        include_groups=False,
    )
    fv = w.pivot(index="start", columns="rule", values="final_value")
    out = []
    for r in rules:
        if r not in fv or r not in per.index.get_level_values(0):
            continue
        p = per.loc[r]
        out.append(
            {
                "rule": r,
                "name": rule_name(r),
                "cost_vs_b0": _f(p["cost"].median() * 100, 2),
                "cheaper": _f(p["cheaper"].median() * 100, 0),
                "wait": _f(p["wait"].median(), 0),
                "unbought": _f(p["unbought"].mean(), 1),
                "cash": _f(w.loc[w["rule"] == r, "cash_ratio"].median() * 100, 1),
                "excess": _f(((fv[r] / fv["B0"]) - 1).median() * 100, 2),
                "final": _f(fv[r].median(), 0),
                "contributed": _f(w["contributed"].median(), 0),
            }
        )
    return out


def build_data(run: Path) -> dict:
    res = run / "results"
    manifest = json.loads((run / "manifest.json").read_text())
    meta = json.loads((res / "meta.json").read_text())
    windows = pd.read_csv(res / "windows.csv", parse_dates=["start", "end"])
    summary = pd.read_csv(res / "summary.csv")
    cal = pd.read_csv(res / "calibration.csv")
    rand = pd.read_csv(res / "random_control.csv", parse_dates=["start"])
    rates = pd.read_csv(res / "trigger_rates.csv", index_col=0)["trigger_rate"]
    trades = pd.read_csv(res / "trades_main.csv.gz", dtype={"years": str})
    level = experiment.load_run_series(run)["tr"]["level"]
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
                # 隔日成交下判定若翻轉，要在主表旁標出，不然 10 年的勝負會被讀成穩健的結論。
                c["lag1"] = row("lag1", y, MAIN_F, opp)
            cells[y] = c
        hyp.append({"code": code, "opp": opp, "label": label, "cells": cells})

    mech = mechanism(
        trades[trades["years"] == "10"],
        main_w[main_w["years"].astype(str) == "10"],
        level,
        ["B0", MAIN_F, "Q_W252_q10", "G_q10", "B1_MA240", "B2_DD10"],
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
        "main_f": MAIN_F,
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
    page = template.replace("__DATA__", payload.replace("</", "<\\/"))
    # 網頁版（Artifact）會自己包 head；本機直接開時沒有這行，Chrome 會把中文猜成 Big5。
    return '<meta charset="utf-8">\n' + page


PLOTLY_URL = "https://cdnjs.cloudflare.com/ajax/libs/plotly.js/2.35.3/plotly.min.js"


def standalone(html: str, js: str | None = None) -> tuple[str, str]:
    """把 plotly 內嵌進頁面、包成完整的 HTML 文件：不連網、本機直接開都正常，供稽核留存。

    回傳 (html, plotly 的 SHA256)。
    """
    import hashlib

    if js is None:
        import requests

        js = requests.get(PLOTLY_URL, timeout=120).text
    digest = hashlib.sha256(js.encode("utf-8")).hexdigest()
    tag = f'<script src="{PLOTLY_URL}"></script>'
    assert html.count(tag) == 1
    body = html.replace(tag, f"<script>/* {PLOTLY_URL} sha256 {digest} */\n{js}</script>")
    body = body.removeprefix('<meta charset="utf-8">\n')
    head = (
        '<!doctype html>\n<html lang="zh-Hant">\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    )
    return head + body, digest


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

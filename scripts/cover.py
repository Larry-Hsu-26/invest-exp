"""產生 README 封面的 HTML（docs/assets/cover.html）；數字與曲線都取自正式 run。

PNG 由瀏覽器截圖產生（1280×640、2 倍解析度），見 README〈封面〉。
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

RUN = Path("runs/20261117T165733Z-7abf9c7")
OUT = Path("docs/assets/cover.html")
W, H = 1280, 640
X0, X1, Y0, Y1 = 64, W - 64, 372, 560


def main() -> None:
    level = pd.read_csv(RUN / "data/taiex_tr_spliced.csv", index_col="date", parse_dates=True)["level"]
    level = level[level.index >= "2003-01-02"]
    sig = pd.read_csv(RUN / "results/signals_tr.csv", index_col="date", parse_dates=True)["F_C1024_q10"]
    sig = sig.reindex(level.index).fillna(0).astype(bool)
    summary = pd.read_csv(RUN / "results/summary.csv")
    rand = pd.read_csv(RUN / "results/random_control.csv")

    def win(opp: str) -> float:
        s = summary[
            (summary["scenario"] == "main")
            & (summary["years"].astype(str) == "10")
            & (summary["rule"] == "F_C1024_q10")
            & (summary["opponent"] == opp)
        ]
        return float(s["win_rate"].iloc[0]) * 100

    r10 = rand[(rand["rule"] == "F_C1024_q10") & (rand["years"].astype(str) == "10")]
    stats = {
        "b0": round(win("B0")),
        "rand": round(float(r10["f_percentile"].median()) * 100),
        "ma": round(win("B1_MA240")),
        "dd": round(win("B2_DD10")),
    }

    t = (level.index - level.index[0]).days.to_numpy()
    x = X0 + (X1 - X0) * t / t[-1]
    ly = np.log(level.to_numpy())
    y = Y1 - (Y1 - Y0) * (ly - ly.min()) / (ly.max() - ly.min())
    line = " ".join(f"{a:.1f},{b:.1f}" for a, b in zip(x, y, strict=True))
    area = f"M{X0},{Y1} L" + line.replace(" ", " L") + f" L{X1},{Y1} Z"
    ticks = "".join(f'<line x1="{a:.1f}" x2="{a:.1f}" y1="582" y2="596"/>' for a in x[sig.to_numpy()])
    years = "".join(
        f'<text x="{X0 + (X1 - X0) * (pd.Timestamp(f"{yr}-01-01") - level.index[0]).days / t[-1]:.1f}" y="620">{yr}</text>'
        for yr in (2005, 2010, 2015, 2020, 2025)
    )
    first, last = level.index[0].date(), level.index[-1].date()
    html = TEMPLATE.format(
        W=W,
        H=H,
        area=area,
        line=line,
        ticks=ticks,
        years=years,
        X0=X0,
        X1=X1,
        Y1=Y1,
        first=first,
        last=last,
        meta=json.dumps({"run": RUN.name, **stats}),
        **stats,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"[cover] {OUT} {stats}")


TEMPLATE = """<!doctype html>
<html lang="zh-Hant">
<meta charset="utf-8">
<title>invest-exp cover</title>
<!-- {meta} -->
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;700;900&family=IBM+Plex+Mono:wght@500&display=block">
<style>
  html, body {{ margin: 0; }}
  body {{ width: {W}px; height: {H}px; background: #0e141c; color: #e8edf3; overflow: hidden;
    font-family: "Noto Sans TC", "WenQuanYi Zen Hei", sans-serif; position: relative; }}
  .eyebrow {{ position: absolute; left: 64px; top: 58px; font: 500 15px "IBM Plex Mono", monospace;
    letter-spacing: .14em; color: #7fa7d9; }}
  h1 {{ position: absolute; left: 60px; top: 86px; margin: 0; font-size: 68px; font-weight: 900; letter-spacing: .02em; }}
  .sub {{ position: absolute; left: 64px; top: 196px; width: 740px; margin: 0; font-size: 23px; line-height: 1.55; color: #a9b6c6; }}
  .stats {{ position: absolute; right: 64px; top: 62px; width: 380px; display: grid; gap: 18px; }}
  .stat {{ border-left: 3px solid #2f3d4f; padding-left: 16px; }}
  .stat b {{ display: block; font: 700 38px/1.15 "Noto Sans TC", sans-serif; font-variant-numeric: tabular-nums; color: #f2f5f8; }}
  .stat span {{ font-size: 16px; color: #8e9bab; }}
  .stat.key {{ border-color: #eb6834; }}
  svg {{ position: absolute; left: 0; top: 0; }}
  .yr {{ font: 500 13px "IBM Plex Mono", monospace; fill: #6b7889; text-anchor: middle; }}
  .legend {{ position: absolute; right: 64px; top: 330px; font-size: 14px; color: #8e9bab; }}
  .legend i {{ display: inline-block; width: 14px; height: 3px; vertical-align: middle; margin: 0 6px 0 18px; }}
</style>
<div class="eyebrow">TAIEX TOTAL RETURN · TIMESTRAL-209M · {first} – {last}</div>
<h1>台股分位數進場回測</h1>
<p class="sub">每月存 2 萬、只買不賣。<br>收盤跌破 Timestral 一日 q0.10 下界才買，能贏定期定額嗎？</p>
<div class="stats">
  <div class="stat key"><b>{b0}%</b><span>10 年窗口勝過定期定額的比例</span></div>
  <div class="stat key"><b>第 {rand} 百分位</b><span>在同頻率隨機進場中的排名（50＝隨機）</span></div>
  <div class="stat"><b>{ma}%／{dd}%</b><span>勝過「跌破年線」「一年高點回檔 10%」的比例</span></div>
</div>
<div class="legend"><i style="background:#3987e5"></i>報酬指數（對數）<i style="background:#eb6834;width:3px;height:12px"></i>Timestral 觸發日</div>
<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <defs><linearGradient id="g" x1="0" x2="0" y1="0" y2="1">
    <stop offset="0" stop-color="#3987e5" stop-opacity=".32"/><stop offset="1" stop-color="#3987e5" stop-opacity="0"/>
  </linearGradient></defs>
  <path d="{area}" fill="url(#g)"/>
  <polyline points="{line}" fill="none" stroke="#3987e5" stroke-width="2.2" stroke-linejoin="round"/>
  <line x1="{X0}" x2="{X1}" y1="{Y1}" y2="{Y1}" stroke="#2f3d4f"/>
  <g stroke="#eb6834" stroke-width="1" stroke-opacity=".85">{ticks}</g>
  <g class="yr">{years}</g>
</svg>
</html>
"""

if __name__ == "__main__":
    main()

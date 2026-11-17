"""抓證交所每月的指數歷史資料，原始回應原樣存檔，並記錄每次請求供稽核。"""

import argparse
import csv
import hashlib
import json
import time
from datetime import UTC, date, datetime
from pathlib import Path

import requests

BASE = "https://www.twse.com.tw/rwd/zh/TAIEX"
# 加權指數（價格指數）與報酬指數；證交所網站的起始日見 AGENTS.md〈Known Gotchas〉。
# 報酬指數是主資料，先抓；價格指數 2003 以後只用於「不含息」穩健性檢查。
# 證交所會單獨擋某個端點（回 307），兩者分開抓、分開退避。
ENDPOINTS = {
    "MFI94U": date(2003, 1, 1),
    "MI_5MINS_HIST": date(1999, 1, 1),
}
LOG_FIELDS = ["endpoint", "month", "url", "fetched_at_utc", "http_status", "sha256", "rows", "stat"]
DELAY_S = 3.5


def months(start: date, end: date) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def fetch_month(session: requests.Session, endpoint: str, month: str) -> tuple[str, int, str]:
    url = f"{BASE}/{endpoint}?date={month}01&response=json"
    # 證交所擋太密的請求時回 HTML 而不是 JSON；退避重試，不要把擋頁當成資料。
    for wait in (0, 60, 300, 900, 1800):
        time.sleep(wait)
        r = session.get(url, timeout=60)
        text = r.text
        try:
            json.loads(text)
            return url, r.status_code, text
        except json.JSONDecodeError:
            print(f"[fetch] {endpoint} {month} not JSON (status {r.status_code}), retry after backoff", flush=True)
    raise RuntimeError(f"{endpoint} {month}: blocked after retries")


def run(root: Path, end: date, endpoints: list[str]) -> None:
    log_path = root / "fetch_log.csv"
    new_log = not log_path.exists()
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (invest-exp research)"
    with log_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
        if new_log:
            writer.writeheader()
        for endpoint in endpoints:
            start = ENDPOINTS[endpoint]
            out_dir = root / endpoint
            out_dir.mkdir(parents=True, exist_ok=True)
            for month in months(start, end):
                path = out_dir / f"{month}.json"
                # 當月資料還在增加，每次都重抓；過去的月份已存檔就不重抓，可接續。
                if path.exists() and month != f"{end.year:04d}{end.month:02d}":
                    continue
                url, status, text = fetch_month(session, endpoint, month)
                path.write_text(text, encoding="utf-8")
                payload = json.loads(text)
                writer.writerow(
                    {
                        "endpoint": endpoint,
                        "month": month,
                        "url": url,
                        "fetched_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                        "http_status": status,
                        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "rows": len(payload.get("data") or []),
                        "stat": payload.get("stat", ""),
                    }
                )
                fh.flush()
                print(f"[fetch] {endpoint} {month} rows={len(payload.get('data') or [])}", flush=True)
                time.sleep(DELAY_S)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="抓證交所指數歷史資料（原始 JSON 存檔）")
    ap.add_argument("--root", type=Path, default=Path("data/raw/twse"))
    ap.add_argument("--end", type=date.fromisoformat, default=date.today())
    ap.add_argument("--endpoints", nargs="+", default=list(ENDPOINTS), choices=list(ENDPOINTS))
    args = ap.parse_args(argv)
    run(args.root, args.end, args.endpoints)


if __name__ == "__main__":
    main()

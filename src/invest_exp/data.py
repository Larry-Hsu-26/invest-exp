"""解析證交所原始 JSON，並把 2003 以前的價格指數接到報酬指數前面（只當暖機用）。"""

import json
from pathlib import Path

import pandas as pd


def _roc_date(text: str) -> pd.Timestamp:
    y, m, d = (int(x) for x in text.strip().split("/"))
    return pd.Timestamp(year=y + 1911, month=m, day=d)


def parse_twse_month(payload: dict) -> pd.DataFrame:
    rows = payload.get("data") or []
    # 收盤一律是最後一欄：價格指數有開高低收，報酬指數只有一欄。
    records = {_roc_date(r[0]): float(r[-1].replace(",", "")) for r in rows}
    df = pd.DataFrame({"close": pd.Series(records, dtype=float)})
    df.index.name = "date"
    return df.sort_index()


def load_series(root: Path, endpoint: str) -> pd.Series:
    parts = []
    for p in sorted((root / endpoint).glob("*.json")):
        payload = json.loads(p.read_text(encoding="utf-8"))
        # 非 OK（查無資料、查詢日期過早）若當成空月份，序列會悄悄少一段。
        if payload.get("stat") != "OK":
            raise ValueError(f"{endpoint}/{p.stem}: stat={payload.get('stat')!r}")
        parts.append(parse_twse_month(payload))
    s = pd.concat(parts)["close"].sort_index()
    if s.index.has_duplicates:
        raise ValueError(f"{endpoint}: duplicate dates")
    return s


def splice(price: pd.Series, tr: pd.Series) -> pd.DataFrame:
    first = tr.index.min()
    if first not in price.index:
        raise ValueError(f"no overlap day: price index lacks {first.date()}")
    ratio = tr.loc[first] / price.loc[first]
    pre = price[price.index < first] * ratio
    level = pd.concat([pre, tr]).sort_index()
    out = pd.DataFrame({"level": level, "is_tr": level.index >= first})
    out.index.name = "date"
    return out

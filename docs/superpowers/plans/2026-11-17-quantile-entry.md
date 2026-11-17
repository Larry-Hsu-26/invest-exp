# M1：時序分位數進場規則回測 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: executing-plans（使用者指定一次做完、隔天看報告）。

**Goal:** 依 spec 抓資料、產生 Timestral／GARCH／經驗分位數的每日下界、回測 7 類規則在滾動窗口的表現，輸出可稽核的 run 目錄與 HTML 報告。

**Architecture:** `invest_exp` 套件分層：`data`（解析與拼接）→ `forecast`（Timestral、GARCH 下界，存檔）→ `rules`（讀下界與價格產生布林訊號）→ `backtest`（單一窗口模擬）→ `evaluate`（滾動窗口、彙總、預測品質）→ `report`（HTML）。`experiment` 串起整個流程並寫 `runs/<run_id>/`。

**Tech Stack:** Python 3.12、pandas 3、numpy、torch 2.8.0＋cpu、timestral（`a534bdb`）、arch 9.0.0、plotly、pytest 9.2.0、ruff 0.17.3。

**Spec:** `docs/superpowers/specs/2026-11-17-quantile-entry-design.md`

**計畫形式的取捨**：使用者授權一次做完並代為決策。本計畫列出每個 task 的檔案、介面與必須先寫的測試（名稱與行為），程式碼在實作時依 TDD 撰寫，不在計畫內預寫。

## Global Constraints

- 決策第 t 天只用到 t 收盤以前的資料；分位數下界只用 t−1 以前的資料。
- 每月第一個交易日存入 20,000；條件成立買進全部現金；手續費 0.1425%（穩健性 0）；現金不計息；不賣出。
- 原始資料、預測、訊號、買進紀錄、窗口結果、manifest 一律存進 `runs/<run_id>/` 並 commit，不覆蓋。
- 測試 `uv run pytest -q -W error`；lint `uv run ruff check . && uv run ruff format --check .`。

## Review Focus

1. **偷看未來**：下界、均線、高點、GARCH 估計若含當日資料，訊號會神準。→ Task 3、4 各有「改動未來資料不影響當日之前的訊號」測試。
2. **拼接比例套到投資窗口**：2003 以前的拼接序列被當成可投資價格。→ Task 2 測試窗口起點不早於報酬指數起點；Task 6 測試。
3. **閒置現金被漏算**：期末資產沒加未投入現金，等待型規則被低估。→ Task 5 測試。
4. **同一天重複買或存入日未買**：B0 存入當天必須買；其他規則同一天只買一次。→ Task 5 測試。
5. **XIRR 算錯**：不規則現金流的 IRR。→ Task 5 以已知答案測試。

---

### Task 1：抓取原始資料（已開始執行）

- Files：`src/invest_exp/fetch.py`
- 行為：每月一個原始 JSON、`fetch_log.csv`（網址、時間、狀態、SHA256、筆數）；被擋時退避重試；過去月份已存檔就跳過。
- 驗證：`fetch_log.csv` 的月份數 = 預期月份數；無 `stat != OK` 的月份（休市月除外）。

### Task 2：解析與拼接（核心，先寫測試）

- Files：`src/invest_exp/data.py`、`tests/test_data.py`
- Produces：
  - `parse_twse_month(payload: dict) -> pd.DataFrame`（index 為日期，欄位 `close`）：民國日期轉西元、去千分位。
  - `load_series(root: Path, endpoint: str) -> pd.Series`
  - `splice(price: pd.Series, tr: pd.Series) -> pd.DataFrame`：欄位 `level`、`is_tr`（是否為真實報酬指數）。
- 測試：`test_parse_roc_date_and_commas`、`test_splice_scales_at_overlap_day`、`test_splice_marks_pre_tr_rows`、`test_splice_rejects_missing_overlap`。

### Task 3：傳統與經驗分位數規則（核心，先寫測試）

- Files：`src/invest_exp/rules.py`、`tests/test_rules.py`
- Produces：`ma_signal(close, n)`、`drawdown_signal(close, x, lookback=252)`、`empirical_lower(close, window, q)`（回傳當日下界）、`below(close, lower)`。
- 測試：`test_ma_signal_uses_today_close`、`test_drawdown_from_trailing_high`、`test_empirical_lower_uses_only_past_returns`（改動第 t 天以後的資料，t 天以前的下界不變）、`test_below_false_when_lower_missing`。

### Task 4：Timestral 與 GARCH 下界（預測存檔）

- Files：`src/invest_exp/forecast.py`、`tests/test_forecast.py`
- Produces：
  - `rolling_windows(level, context) -> (dates, contexts)`：第 t 天的 context 是 t−1 以前的 `context` 筆。
  - `timestral_forecasts(level, context, batch) -> pd.DataFrame`：每天 21 個分位數。
  - `garch_lower(close, qs, window=1008) -> pd.DataFrame`：每天各 q 的價格下界。
- 測試：`test_rolling_windows_end_before_target_day`、`test_garch_lower_uses_only_past`（以小樣本、少量天數）。Timestral 本身不寫單元測試，以存檔結果的覆蓋率檢查（Task 6）。

### Task 5：回測引擎與 XIRR（核心，先寫測試）

- Files：`src/invest_exp/backtest.py`、`tests/test_backtest.py`
- Produces：
  - `monthly_deposit_days(dates, start, end) -> pd.DatetimeIndex`
  - `simulate(close, signal, deposit_days, amount, fee, lag=0) -> Result`（`final_value`、`units`、`cash`、`trades` DataFrame、`cash_ratio`、`max_cash`、`n_buys`）
  - `xirr(cashflows: list[tuple[date, float]]) -> float`
- 測試：`test_dca_buys_on_deposit_day`、`test_no_signal_keeps_cash_in_final_value`、`test_buys_all_cash_once_per_day`、`test_fee_reduces_units`、`test_lag_one_buys_next_day_close`、`test_xirr_known_answer`。

### Task 6：滾動窗口、彙總、預測品質、穩健性

- Files：`src/invest_exp/evaluate.py`、`tests/test_evaluate.py`
- Produces：`window_starts(dates, first_month, years)`、`run_windows(...)`、`summarize(...)`、`calibration_by_year(...)`、`random_control(...)`。
- 測試：`test_window_starts_fit_inside_data`、`test_window_never_starts_before_tr`。

### Task 7：實驗主程式與 manifest

- Files：`src/invest_exp/experiment.py`
- 行為：讀資料 → 產生全部預測（存檔）→ 全部訊號（存檔）→ 窗口回測（每筆買進、每個窗口存檔）→ 彙總 → `manifest.json`（git commit、時間、套件版本、模型 revision、設定、各檔 SHA256）。
- 驗證：實際跑完；檢查 F 主設定的覆蓋率在合理範圍（0.05–0.2）；B0 的 XIRR 與報酬指數年化報酬同量級。

### Task 8：HTML 報告

- Files：`src/invest_exp/report.py`、`reports/<run_id>.html`
- 內容：結論摘要（H1–H5 判定）→ 勝率與超額分佈 → 全期間資產曲線與買點 → 觸發頻率與閒置現金 → 預測校準與洩漏 → 穩健性 → 限制與資料來源。
- 驗證：瀏覽器截圖目視檢查。

### Task 9：交接

- AGENTS.md 進度與指令、milestone M1、最終審查（獨立 reviewer）、推送。

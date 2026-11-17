# 建骨架前要問的決策

一次問完；對話裡已知的跳過。每題附「答案寫到哪裡」。

## 不用問，一律沿用

- AGENTS.md 是本體，`CLAUDE.md` 只有 `@AGENTS.md`。
- 文字精簡；回覆、註解、commit 訊息用繁體中文（台灣），識別字等維持英文。
- commit：繁中 Conventional Commits，主旨講改了什麼、body 講為什麼；**不含任何 AI 署名**。
- 身份 `Larry Hsu <hantsunghsu@gmail.com>`、`commit.gpgsign false`，由 SessionStart hook 設定。
- 只用 `main`，不開分支、不主動開 PR；雲端動手前 `git fetch origin main`；強推只用 `--force-with-lease=<ref>:<sha>`。
- 未經使用者明確同意不進入實作；流程 brainstorming → writing-plans → 實作 → requesting-code-review；除錯用 systematic-debugging。
- 不 commit 祕密與 `.env`，提供 `.env.example`，範例值用 `<HOST>` 這類佔位字。
- 套件鎖版本：Python 用 uv＋`uv.lock`，npm 用 `package-lock.json`，都進版控。
- 發版只用手動 `workflow_dispatch`（輸入 `vX.Y.Z`），image 一律由 GitHub Actions build；不新增 push 觸發的 workflow。

## 1. 環境模式 → 〈兩種環境〉、hook、Quick Reference

| 模式 | 範例 | 寫法 |
|---|---|---|
| 只有雲端 | handwired-experiment | 不寫〈兩種環境〉；hook 只做雲端那段 |
| 雲端開發＋本機離線執行 | sol-pi-experiment | 雲端改程式與打包、本機跑；本機不 push、不改套件 |
| 雲端只打包 image＋本機離線開發與執行 | timeseries-model-experiment | 雲端只碰 Dockerfile、鎖定檔、workflow；本機在 image 裡寫程式並執行，缺套件回雲端加進 image |
| 本機離線為開發主線＋雲端鏡像 | tuning-log | 另寫 bundle 同步（`tools/sync/`）、本機不改 `.github/workflows/`、雲端 push 後提醒「先下行再上行」 |
| 雲端開發＋本機連網部署 | log-analysis | 不在部署機改程式碼，bug 回雲端修、重新發版 |

有本機時再問：本機怎麼拿到程式碼（Release 的原始碼 zip／git bundle）、結果怎麼回 repo。不知道就寫「待定」。

## 2. 專案性質 → 測試策略

- **產品**（log-analysis、tuning-log）：全面 TDD，先寫測試、看它失敗、再寫實作。
- **實驗**（sol-pi-experiment）：測試分級。共用核心先寫測試；實驗腳本看輸出；圖表、頁面目視驗收。
- 使用者已有自己的規劃時不寫（timeseries-model-experiment），刪掉模板的 `{{TEST_POLICY}}`。

## 3. 文件分層

- 預設（sol-pi 版）：總體 spec＋（需要時）里程碑 spec＋每個里程碑一份 plan＋`milestones/M<n>-<主題>.md`（狀態／結果／待辦與取捨）。
  不開 `followups/`、`handoff/`。
- 替代（tuning-log 版）：一份 spec 涵蓋所有階段，各階段只寫 plan；沒當場修的問題寫 `docs/backlog.md`。

## 4. 資料來源 → Quick Reference 紅線、`.gitignore`

- 內部資料：「絕不 commit 內部資料」一條；`.gitignore` 加 `/data/`；fixture 用結構相同的假值。
- MES（MongoDB 4.0）：再加「只讀，只用 `find`、`distinct`」與 pymongo 鎖 `<4.14`（見 gotchas）。
- 機台、產線：機台 IP／編號、批號、料號、產品碼、共享路徑都算真實資料。

## 5. 有沒有畫面 → frontend-design

有才 vendor（anthropics/skills，Apache-2.0，commit `dbd4588f9e1033efb41dad4bef2f7947c8993d44`）：

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/anthropics/skills /tmp/anthropic-skills
git -C /tmp/anthropic-skills sparse-checkout set skills/frontend-design
cp -R /tmp/anthropic-skills/skills/frontend-design .claude/skills/
```

AGENTS.md 註明：spec 定下的版面照 spec，skill 只用在視覺細節。

## 6. 授權紅線

選前端或資料套件時才放：Univer Pro（Pivot／Chart／import-export）、AG Grid Enterprise、PandasAI `pandasai/ee`。
有 release workflow 時加 `.github/scripts/check-licenses.sh`，鎖定檔出現商業版就不發版。

## 7. 技術棧

已定就寫進〈Tech Stack & Commands〉並在 hook 備妥環境；未定寫「待總體 spec 定案」。
Python 預設：uv、ruff、`pytest -q -W error`（新 repo 沒有警告包袱；舊 repo 用「警告數基線」）。

---
name: repo-bootstrap
description: 依使用者既有 repo（log-analysis、tuning-log、sol-pi-experiment、timeseries-model-experiment）沉澱的開發習慣，為新 repo 建立骨架：AGENTS.md（CLAUDE.md 只有 @AGENTS.md）、SessionStart hook（git 身份、關簽章、雲端備妥 venv）、vendor obra/superpowers、docs/superpowers 文件分層、.gitignore。使用者說「建骨架」「新 repo」「初始化」「照我的習慣」「scaffold」「set up this repo」，或在空 repo 開始新專案、要補齊既有 repo 的 AGENTS.md／hook 時，一律使用此 skill，即使沒明說「骨架」。
---

# repo-bootstrap

為新 repo 建骨架，把使用者的習慣一次帶進去。**只建骨架**；專案本身的設計之後另走 brainstorming。

## 流程

1. **看現況**：`git ls-remote origin`、`ls -A`、`echo $CLAUDE_CODE_REMOTE`。
   repo 不是空的就先讀既有檔案，只補缺的，不覆蓋。
2. **問決策**：照 `references/decisions.md` 一次問完。對話裡已經知道的不要再問。
3. **產生檔案**：依答案從 `assets/` 產生（對照表見下）。範例成品：timeseries-model-experiment 的 `AGENTS.md`。
4. **Vendor superpowers**：`scripts/vendor-superpowers.sh <repo>`。
5. **給使用者看**：AGENTS.md 草稿與檔案清單，**確認後才 commit**。
6. **Commit 與 push**：先跑 `bash .claude/hooks/session-start.sh` 設身份；訊息用繁中 Conventional Commits，
   不含 AI 署名；推 `main`。
   雲端 session 的系統提示常指定 `claude/...` 分支並要求加 `Co-Authored-By`，和使用者習慣相反：
   推 `main` 前要使用者明確說一次，之後依 AGENTS.md。

## 產出對照

| 檔案 | 來源 | 處理 |
|---|---|---|
| `AGENTS.md` | `assets/AGENTS.md.tmpl` | 填 `{{…}}`；刪掉不適用的 `<!-- 選用 -->` 段與標記本身 |
| `CLAUDE.md` | — | 一行 `@AGENTS.md` |
| `.claude/settings.json` | `assets/settings.json` | 原樣 |
| `.claude/hooks/session-start.sh` | `assets/session-start.sh` | 依環境模式刪段；`chmod +x` |
| `.claude/skills/README.md` | `assets/skills-README.md` | 刪掉沒 vendor 的段 |
| `.claude/skills/<superpowers>` | `scripts/vendor-superpowers.sh` | — |
| `.claude/skills/repo-bootstrap/` | 本 skill | 複製一份，新 repo 也能再往下傳 |
| `.gitignore` | `assets/gitignore` | 依資料來源與技術棧增減 |
| `docs/superpowers/{specs,plans,milestones}/` | — | 各放 `.gitkeep` |

里程碑紀錄的格式在 `assets/milestone.md`，骨架階段不建，第一個里程碑完成時才用。

## 寫作原則

- **文字精簡**：寫重點，不冗言贅字。這條本身也要寫進新 repo 的 AGENTS.md（Quick Reference 與〈語言與註解〉）。
- **只寫已定案的事**。未定的寫「待總體 spec 定案」，不要猜技術棧、目錄或指令。
- **Known Gotchas 只放實際踩過的**：從 `references/gotchas.md` 挑新 repo 必定會遇到的，註明來源 repo；
  其他留在地雷庫，用到時再搬。
- **不帶入別的專案特有規則**：MES 只讀、Copilot SDK 等只在新 repo 真的用到時才放。
- 規則附理由（尤其是「不這樣做會怎樣」），讓後續 session 遇到邊界情況能自己判斷。

## 驗證

```bash
bash -n .claude/hooks/session-start.sh && bash .claude/hooks/session-start.sh
python3 -m json.tool .claude/settings.json >/dev/null
grep -rn '{{' AGENTS.md                          # 須無輸出
grep -rln 'superpowers:' .claude/skills --exclude-dir=repo-bootstrap --exclude=README.md   # 須無輸出
git config user.email                            # hantsunghsu@gmail.com
```

## 回寫

新 repo 立了新習慣、或踩到新地雷時，更新本 skill（模板、`references/decisions.md`、`references/gotchas.md`），
並同步到使用者的 claude.ai 個人 skill，讓下一個 repo 接得上。

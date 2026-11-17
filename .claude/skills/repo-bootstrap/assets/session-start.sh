#!/bin/bash
#
# SessionStart hook：釘住 git commit 身份；雲端 session 另外備妥測試環境。
#
# 為什麼要釘身份：
# 託管環境預設 user.email 是 noreply@anthropic.com，GitHub 以 email 反查帳號，會把 commit
# 算在 @claude 頭上，它就出現在 Contributors。每次啟動都改回擁有者，避免問題無聲地回來。
#
# 為什麼關掉簽章：
# 託管環境用 Anthropic 名下的金鑰簽章，email 改成擁有者後身份對不上，GitHub 標紅色 Unverified，
# 比沒有徽章更糟。關掉後，harness 那支以 gpgsign == true 為前提的 stop hook 也整段跳過。
#
# 為什麼雲端與本機分開：
# 本機離線，什麼都裝不了，只在雲端準備環境。只有雲端時刪掉本機那段。
#
set -euo pipefail

cd "${CLAUDE_PROJECT_DIR:-.}"

git config user.name  "Larry Hsu"
git config user.email "hantsunghsu@gmail.com"
git config commit.gpgsign false

echo "[session-start] git identity: $(git config user.name) <$(git config user.email)>, signing off"

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
    echo "[session-start] 本機 session：見 AGENTS.md〈兩種環境〉"
    exit 0
fi

# 裝不起來不該擋住 session 啟動——印出原因，讓人照 AGENTS.md 手動處理。
if [ -f pyproject.toml ] && command -v uv >/dev/null 2>&1; then
    # --locked：鎖定檔與 pyproject.toml 不一致就失敗，和 image build 的行為相同。
    if uv sync --locked >/dev/null 2>&1; then
        echo "[session-start] .venv 就緒：uv run pytest -q -W error"
    else
        echo "[session-start] ⚠️ .venv 準備失敗，手動執行：uv sync --locked"
    fi
fi

# 有前端時保留；路徑依專案調整。
if [ -f frontend/package-lock.json ] && command -v npm >/dev/null 2>&1; then
    if [ -d frontend/node_modules/.bin ] && [ frontend/node_modules/.package-lock.json -nt frontend/package-lock.json ]; then
        echo "[session-start] frontend/node_modules 已就緒"
    elif (cd frontend && npm ci --no-audit --no-fund >/dev/null 2>&1); then
        echo "[session-start] frontend/node_modules 就緒"
    else
        echo "[session-start] ⚠️ frontend/node_modules 準備失敗，手動執行：cd frontend && npm ci"
    fi
fi

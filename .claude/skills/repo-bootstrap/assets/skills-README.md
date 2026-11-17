# Vendor 的 skills

## superpowers

來源：https://github.com/obra/superpowers
版本：6.4.1
Commit：5bf4e78011075bcfc0dc295f0724994cd123ee71
授權：MIT（Copyright (c) 2025 Jesse Vincent），見 `LICENSE-superpowers.txt`

### 為什麼 vendor 而不是裝成 plugin

雲端在 ephemeral 容器裡跑，`/plugin install` 裝在 `~/.claude/plugins/`，容器回收就消失；本機離線則裝不了。
commit 進 repo 後每個 session 自動載入，版本也由 git 釘住。

### 本地修改

跨 skill 的引用從 `superpowers:writing-plans` 改成 `writing-plans`：專案 skill 不帶 plugin 前綴。除此之外沒有修改。
上游的 hooks 與 `index.js` **沒有** vendor；skill 一律明確呼叫。

### 更新方式

    .claude/skills/repo-bootstrap/scripts/vendor-superpowers.sh . <新 commit>

只換掉上游有的 skill 目錄，其他 skill 不動。完成後更新上面的版本與 commit hash。

<!-- 選用：有畫面 -->
## frontend-design

來源：https://github.com/anthropics/skills/tree/main/skills/frontend-design
Commit：dbd4588f9e1033efb41dad4bef2f7947c8993d44
授權：Apache-2.0，見 `frontend-design/LICENSE.txt`

原樣 vendor（`SKILL.md` 與 `LICENSE.txt`），沒有本地修改。更新方式見 `repo-bootstrap/references/decisions.md` §5。
<!-- /選用 -->

## repo-bootstrap

自建，非 vendor。依使用者既有 repo 的習慣為新 repo 建骨架；內容見其 `SKILL.md`。
新 repo 立了新習慣或踩到新地雷時，回寫到該 skill。

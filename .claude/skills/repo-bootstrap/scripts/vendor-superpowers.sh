#!/bin/bash
# 把 obra/superpowers 的 skills vendor 到 <repo>/.claude/skills/。
# 用法：vendor-superpowers.sh <repo 路徑> [commit]
#
# 只換掉上游有的 skill 目錄：frontend-design、repo-bootstrap 等其他 skill 不動。
# 跨 skill 引用去掉 `superpowers:` 前綴：專案 skill 不帶 plugin 前綴，留著會叫不到。
set -euo pipefail

repo=${1:?用法：vendor-superpowers.sh <repo 路徑> [commit]}
commit=${2:-5bf4e78011075bcfc0dc295f0724994cd123ee71}
dest="$repo/.claude/skills"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

git -C "$tmp" init -q
git -C "$tmp" remote add origin https://github.com/obra/superpowers
git -C "$tmp" fetch -q --depth 1 origin "$commit"
git -C "$tmp" checkout -q FETCH_HEAD

mkdir -p "$dest"
for d in "$tmp"/skills/*/; do
    name=$(basename "$d")
    rm -rf "${dest:?}/$name"
    cp -R "$d" "$dest/$name"
    # 沒有匹配時 grep 回 1，pipefail 下會讓整支腳本無聲退出
    { grep -rl 'superpowers:' "$dest/$name" || true; } | xargs -r sed -i 's/superpowers://g'
done
cp "$tmp/LICENSE" "$dest/LICENSE-superpowers.txt"

echo "superpowers $(git -C "$tmp" rev-parse HEAD) → $dest"

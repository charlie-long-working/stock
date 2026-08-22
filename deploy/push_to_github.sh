#!/usr/bin/env bash
# Chạy trên Terminal máy bạn (không qua Cursor sandbox):
#   cd /Users/namnguyen/Documents/Cursor/stock && bash deploy/push_to_github.sh
#
# Yêu cầu: SSH Host github-charlie đã work; gh CLI (brew install gh) đã login.
set -euo pipefail

STOCK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$STOCK_ROOT"

REPO_NAME="${REPO_NAME:-stock}"
OWNER="${OWNER:-charlie-long-working}"
FULL="$OWNER/$REPO_NAME"
SSH_URL="git@github-charlie:${FULL}.git"

if ! command -v gh >/dev/null 2>&1; then
  echo "Cần gh CLI. Cài: brew install gh && gh auth login"
  exit 1
fi

if ! gh auth status -h github.com >/dev/null 2>&1; then
  echo "Đăng nhập GitHub CLI..."
  gh auth login --hostname github.com --git-protocol ssh --web
fi

# Tạo repo private nếu chưa có
if gh repo view "$FULL" >/dev/null 2>&1; then
  echo "Repo đã tồn tại: https://github.com/$FULL"
else
  echo "Tạo repo private $FULL ..."
  gh repo create "$FULL" --private --description "VN stocks + hourly Telegram signals" --confirm
fi

git remote remove origin 2>/dev/null || true
git remote add origin "$SSH_URL"
git push -u origin main

echo ""
echo "=== Set Actions secrets từ stock/.env ==="
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a
  # chỉ lấy key cần thiết, không echo value
  TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' .env | head -1 | cut -d= -f2-)
  CHAT=$(grep -E '^TELEGRAM_CHAT_ID=' .env | head -1 | cut -d= -f2-)
  set +a
  if [[ -n "${TOKEN:-}" ]]; then
    printf '%s' "$TOKEN" | gh secret set TELEGRAM_BOT_TOKEN -R "$FULL"
    echo "Set TELEGRAM_BOT_TOKEN"
  fi
  if [[ -n "${CHAT:-}" ]]; then
    printf '%s' "$CHAT" | gh secret set TELEGRAM_CHAT_ID -R "$FULL"
    echo "Set TELEGRAM_CHAT_ID"
  fi
else
  echo "Không thấy .env — set secrets thủ công trên GitHub."
fi

echo ""
echo "TB_CHECKOUT_TOKEN (PAT đọc trading-bot) — nếu trading-bot private, tạo PAT rồi:"
echo "  gh secret set TB_CHECKOUT_TOKEN -R $FULL"
echo ""
echo "Variable TB_REPO (optional):"
echo "  gh variable set TB_REPO -R $FULL --body charlie-long-working/trading-bot"
echo ""
echo "Done. Mở: https://github.com/$FULL/actions"
echo "Chạy thử: Actions → VN Hourly Telegram → Run workflow (force=true)"

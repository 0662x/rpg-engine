#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${AIGM_PLATFORM_PREWARM_ENV_FILE:-$HOME/.hermes/.aigm-platform-prewarm.env}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "DEEPSEEK_API_KEY is missing. Run scripts/setup_platform_prewarm_env.sh first." >&2
  exit 1
fi

ROOT="${AIGM_PREWARM_CHECK_ROOT:-/tmp/aigm-platform-prewarm-check}"
rm -rf "$ROOT"
mkdir -p "$ROOT/campaigns"
cp -R "rpg_engine/resources/examples/v1_minimal_adventure" "$ROOT/campaigns/minimal"

echo "== Config =="
python3 - <<'PY'
from rpg_engine.platform_prewarm import PlatformPrewarmConfig
cfg = PlatformPrewarmConfig.from_env()
print(cfg)
PY

echo
echo "== Start platform session =="
python3 -m rpg_engine platform start "$ROOT" \
  --platform qq \
  --session-key qq:user:prewarm-check \
  --message-id qq:prewarm-check:start \
  --actor-id user:prewarm-check \
  --user-text '开始游戏' \
  --campaign campaigns/minimal \
  --enable-prewarm \
  --format json \
  | python3 -m json.tool

echo
echo "== Real DeepSeek message-only prewarm =="
python3 -m rpg_engine platform message "$ROOT" \
  --platform qq \
  --session-key qq:user:prewarm-check \
  --message-id qq:prewarm-check:act \
  --actor-id user:prewarm-check \
  --user-text '休息到早上' \
  --enable-prewarm \
  --intent-backend direct \
  --intent-provider deepseek \
  --intent-model deepseek-v4-flash \
  --intent-base-url https://api.deepseek.com \
  --intent-api-key-env DEEPSEEK_API_KEY \
  --intent-fallback-backend off \
  --intent-timeout 8 \
  --drain \
  --format json \
  | python3 -m json.tool

echo
echo "== Act should consume prewarm cache =="
python3 -m rpg_engine platform act "$ROOT" \
  --platform qq \
  --session-key qq:user:prewarm-check \
  --message-id qq:prewarm-check:act \
  --actor-id user:prewarm-check \
  --user-text '休息到早上' \
  --enable-prewarm \
  --intent-backend direct \
  --intent-provider deepseek \
  --intent-model deepseek-v4-flash \
  --intent-base-url https://api.deepseek.com \
  --intent-api-key-env DEEPSEEK_API_KEY \
  --intent-fallback-backend off \
  --intent-timeout 8 \
  --preflight-pending-wait-ms 10 \
  --format json \
  | python3 -m json.tool

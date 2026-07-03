# Internal AI Key Setup Note

Date: 2026-07-03

Purpose: 以后忘记 DeepSeek API key 怎么配置时，看这份备忘。这里不保存 key 本身，只记录保存位置和操作命令。

## Key 保存位置

本地 env 文件：

```bash
/Users/oliver/.hermes/.aigm-platform-prewarm.env
```

这个文件由脚本生成，权限应为 `600`。它会保存：

```bash
DEEPSEEK_API_KEY
AIGM_PLATFORM_PREWARM=1
AIGM_PLATFORM_PREWARM_INTENT_BACKEND=direct
AIGM_PLATFORM_PREWARM_INTENT_PROVIDER=deepseek
AIGM_PLATFORM_PREWARM_INTENT_MODEL=deepseek-v4-flash
AIGM_PLATFORM_PREWARM_INTENT_BASE_URL=https://api.deepseek.com
AIGM_PLATFORM_PREWARM_INTENT_API_KEY_ENV=DEEPSEEK_API_KEY
```

不要把真实 key 写进代码、文档或聊天记录。

## 首次写入或重写 key

```bash
cd /Users/oliver/.hermes/rpg-engine
scripts/setup_platform_prewarm_env.sh
```

脚本会提示 `Paste DEEPSEEK_API_KEY:`。粘贴时终端不显示字符是正常的。

## 启用配置

每次启动需要用内部 AI / 平台预热的进程前，先执行：

```bash
source /Users/oliver/.hermes/.aigm-platform-prewarm.env
```

如果是从别的 shell、Hermes 进程、sidecar 进程启动，也要确保那个进程继承了这些环境变量。

## 快速检查

```bash
echo "$AIGM_PLATFORM_PREWARM"
echo "$DEEPSEEK_API_KEY" | wc -c
```

期望：

- `AIGM_PLATFORM_PREWARM` 输出 `1`。
- `DEEPSEEK_API_KEY` 长度大于 `0`。

## 真实调用检查

```bash
cd /Users/oliver/.hermes/rpg-engine
scripts/check_platform_prewarm.sh
```

这个脚本会读取 env 文件，真实调用 `deepseek-v4-flash` 跑一次 message-only prewarm，然后验证正式 act 能消费预热 cache。

## API URL 口径

配置里写官方 OpenAI-compatible base URL：

```bash
https://api.deepseek.com
```

rpg-engine 内部 provider 会自动补成裸 HTTP endpoint：

```bash
https://api.deepseek.com/chat/completions
```

`deepseek-v4-flash` 内部 helper 调用会显式使用非 thinking 模式，保持轻量：

```json
{"thinking": {"type": "disabled"}}
```

# Phase 0 Runtime Performance Baseline

状态：`2026-07-01.phase-0-baseline`  
生成命令：

```bash
python3 -m rpg_engine.performance_baseline examples/v1_minimal_adventure --iterations 5 --format markdown
```

本报告是本机 No-AI 基线，不是通用 pass/fail 阈值。后续 Phase 3+ 如果关键路径 P50/P95 较本基线劣化超过 20%，需要在 release note 中说明原因、用户收益和回滚方式。

Campaign: `v1-minimal-adventure`  
Iterations: `5`

| Operation | P50 ms | P95 ms | Mean ms | Min ms | Max ms | Samples ms |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `start_turn` | 1.746 | 3.742 | 2.296 | 1.446 | 3.742 | 2.960, 1.746, 1.587, 1.446, 3.742 |
| `preview_from_text` | 1.167 | 1.458 | 1.176 | 0.980 | 1.458 | 1.167, 1.252, 1.025, 0.980, 1.458 |
| `validate_delta` | 0.082 | 0.108 | 0.082 | 0.060 | 0.108 | 0.067, 0.108, 0.060, 0.093, 0.082 |
| `commit_turn` | 5.485 | 7.786 | 5.814 | 5.024 | 7.786 | 5.024, 5.561, 5.485, 5.215, 7.786 |

Notes:

- No external AI calls are used.
- Each iteration uses a fresh temporary campaign copy so `commit_turn` does not pollute later samples.
- Numbers are local-environment baselines, not universal pass/fail thresholds.

## 测试覆盖

`tests/test_performance_baseline.py` 验证报告结构、必需 operation 和 Markdown 渲染，但不设置硬性能阈值，避免 CI 机器差异造成误判。

## 后续使用方式

- Phase 1/2：继续扩大 gold set 和 transcript 测试时，不应明显增加 `start_turn` 或 `preview_from_text` 延迟。
- Phase 3：`TurnContract` 强制进入 context、preview 和 response lint 后，比较 `start_turn`、`preview_from_text` 和 response lint 相关路径。
- Phase 4：strict `TurnProposal`、resolver/AI/response draft 来源标记和 proposal guard 落地后，比较 `preview_from_text`、direct `preview_action` 和 proposal validation 相关路径。
- Phase 5+：引入 `ValidationPipeline`、`TurnCommitService`、`ProjectionService` 时，重点比较 `validate_delta`、proposal validation 和 `commit_turn`。

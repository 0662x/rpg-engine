# 万能农具 · 异世界悠闲农家 运维报告

## Current

| 字段 | 值 |
|------|----|
| current_turn_id | `turn:000026` |
| current_location_id | `loc:home-mycelium-house` |
| current_time_block | 入夜（母孢子树→夏娃/金光1086%破千/浆果醋开封/T2活捉/L15草原发现/农耕扩至27畦142㎡） |
| weather | clear/none |

## Counts

| 项目 | 数量 |
|------|------|
| entities | 233 |
| cards | 234 |
| events | 27 |
| turns | 27 |
| routes | 26 |
| clocks | 6 |
| memory_summaries | 23 |
| context_runs | 2 |

## Entity Types

| 类型 | 数量 |
|------|------|
| item | 62 |
| plant | 27 |
| location | 24 |
| rule | 17 |
| crop_plot | 16 |
| equipment | 14 |
| material | 12 |
| species | 11 |
| reference | 10 |
| world_setting | 10 |
| project | 9 |
| clock | 6 |
| threat | 6 |
| character | 5 |
| recipe | 4 |

## Audit

- findings: 1
- error: 0
- warn: 0
- info: 1
- `hidden_clock` info: 隐藏进度钟：文明传闻 0/8

## Context Runs

| ID | 模式 | 预算 | 允许推进 |
|----|------|------|----------|
| `context:manual-check-final` | maintenance:maintenance | 1434/1600 | 1 |
| `context:manual-check-001` | maintenance:maintenance | 1434/1600 | 1 |

## Speed Sample

| 输入 | 秒 | 估算 token |
|------|----|------------|
| 查看当前场景 | 0.0079 | 2317 |
| 询问夏娃基地状态 | 0.0021 | 2935 |
| 去空地/家检查农田与干旱压力 | 0.0014 | 2465 |

- average: 0.0038s
- max: 0.0079s

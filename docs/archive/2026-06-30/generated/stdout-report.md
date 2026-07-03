# 万能农具 · 异世界悠闲农家 运维报告

## Current

| 字段 | 值 |
|------|----|
| current_turn_id | `turn:000019` |
| current_location_id | `loc:home-mycelium-house` |
| current_time_block | 入夜（母孢子树→夏娃/金光1086%破千/浆果醋开封/T2活捉/L15草原发现/农耕扩至27畦142㎡） |
| weather | clear/none |

## Counts

| 项目 | 数量 |
|------|------|
| entities | 215 |
| cards | 216 |
| events | 20 |
| turns | 20 |
| routes | 26 |
| clocks | 6 |
| memory_summaries | 19 |
| context_runs | 2 |

## Entity Types

| 类型 | 数量 |
|------|------|
| item | 62 |
| plant | 27 |
| location | 24 |
| crop_plot | 16 |
| equipment | 14 |
| material | 12 |
| species | 11 |
| reference | 10 |
| project | 9 |
| rule | 9 |
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
| 看一下终极复合弩属性 | 0.0039 | 2876 |
| 我去小溪收鱼笼 | 0.0207 | 2901 |
| 我用终极复合弩攻击T3 | 0.0017 | 2839 |
| 我找 An 交易盐和调料 | 0.0012 | 2987 |
| 那个蘑菇是什么 | 0.0022 | 2440 |

- average: 0.0059s
- max: 0.0207s

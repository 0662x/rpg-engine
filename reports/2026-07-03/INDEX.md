# 2026-07-03 Reports

| File | Purpose |
| --- | --- |
| `00-ai-prewarm-document-map.md` | AI intent / preflight / platform prewarm 文档地图。明确 2026-07-02 报告是阶段一、阶段二和 3A 的历史与验收记录，3B 工程开工以 2026-07-03 计划为准。 |
| `01-platform-prewarm-3b-lightweight-implementation-plan.md` | 阶段三 3B 轻量平台监听/预热实施计划和 rpg-engine 侧实现记录。把平台 adapter 限定为可丢弃加速旁路：不改 Hermes core、不阻塞、不提交、不读 hidden。 |
| `02-ai-subsystem-code-review.md` | AI 子系统专家 code review：模块边界、低风险快通道、平台轻量性、剩余技术债和本轮测试结果。 |
| `03-ai-platform-local-simulation-report.md` | 本地模拟压测报告：正常/异常玩家输入、平台 gate、queue/drop、AI timeout、低风险快通道和真实 canary 指标清单。 |
| `04-internal-ai-key-setup-note.md` | 内部 AI / DeepSeek key 本地配置备忘：key env 文件位置、启用命令、检查命令和真实预热检查脚本。 |
| `05-external-ai-skill-review.md` | 外部 AI / Hermes skill 审核与更新记录：默认玩家安全链路、结构化输出边界、`external_intent_candidate` 何时允许使用。 |

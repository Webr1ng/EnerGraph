# EnerGraph Eval reports

本目录用于本地/手动评测运行产物，`summary.md`、`results.json` 和 `run_manifest.json` 默认不提交。

注意：

- 子目录中的历史 `FAIL` 报告只表示当次运行结果，可能是修复前、故意负例或环境不可用产物。
- 当前代码状态以 `CHANGELOG.md`、`AI_CONTEXT.md`、`benchmarks/README.md` 的最新验收记录，以及最新 run_id 的报告为准。
- MR/发布时如需提交报告，应只提交脱敏后的最终报告或在 MR 描述中贴出最新 run_id、模型、配置、通过/失败摘要。
- T14 Production 报告必须来自独立测试环境和真实故障注入执行器；Fast/Standard fixed fixture 报告不得标记为 Production 验收。

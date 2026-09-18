# 2026-09-18 CycleError 异常契约

- **状态**：已定稿
- **对应 Issue**：https://github.com/STU-MS/TopoSort/issues/12
- **关联任务**：https://github.com/STU-MS/TopoSort/issues/3
- **日期**：2026-09-18
- **参与人**：Asukadaisiki、AI 代理

## 背景

T1 骨架中 `Graph.layers()` 的文档约定环图抛出 `CycleError`，但
`app.models` 尚未定义或公开该异常。T2 实现前需要明确环图分层失败的
公共行为。

## 选项

1. 新增并公开 `CycleError(ValueError)`。
2. 仅抛出通用 `ValueError`。
3. 对环图返回不完整的部分分层结果。

## 结论

采用选项 1。`CycleError` 在 `app.models` 中公开，并继承
`ValueError`；`Graph.layers()` 检测到环时抛出该异常。
`Graph.has_cycle()` 与 `Graph.cycle_nodes()` 保持无异常查询接口。

## 理由

- 与 T1 骨架中已经写明的行为一致。
- 调用方可以明确区分图结构错误和其他参数错误。
- 继承 `ValueError`，保留通用输入错误处理的兼容性。
- 禁止返回可能被误认为完整布局的部分分层结果。

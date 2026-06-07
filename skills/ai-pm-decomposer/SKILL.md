---
name: ai-pm-decomposer
description: >
  自适应前向分解器。接收一个节点，使用统一的 prompt 模板将其分解为子节点，
  同时为每个子节点生成超空间向量标签。深度由内容复杂度驱动，不预设层数。
  LLM 判断每个子节点是否已达可执行粒度（terminal），是则停止该分支。
  使用关键词：分解节点、展开子节点、前向分解、生成标签。
version: 0.2.0
user-invocable: true
triggers:
  - "分解节点"
  - "展开"
  - "前向分解"
  - "decompose node"
  - "expand node"
---

# AI PM Decomposer - 自适应前向分解器

## 触发场景

当需要将某个节点分解为更细粒度的子节点时触发。由 ai-pm-core 调度调用。

## 设计原则

- **深度自适应**：不预设固定层数，每个分支按内容复杂度决定深度
- **统一模板**：所有深度使用同一个 prompt 模板（`prompt_decompose.md`）
- **终止判断**：LLM 判断子节点是否为 terminal（一人一 sprint 可执行），是则标记 done
- **层 = 粒度**：depth-0 最粗，depth-N 最细，层本身不携带语义

## 工作流程

1. **读取节点信息**：从数据库获取目标节点的完整信息
2. **组装上下文**：祖先链 + 全局摘要 + 当前节点详情
3. **加载 prompt 模板**：使用统一模板 `references/prompt_decompose.md`
4. **调用 LLM**：分解当前节点，LLM 对每个子节点判断 is_terminal
5. **解析结果**：提取子节点列表和超空间向量标签
6. **持久化**：
   - 为每个子节点写入 detail.md、summary.md、vector.json
   - 在数据库中创建子节点记录（terminal 节点标记为 done）
   - 将结构化标签写入 tags 表

## 脚本

- `scripts/decompose.py`：分解逻辑

## 参考文件

- `references/prompt_decompose.md`：统一分解 prompt 模板
- `references/vector_schema.json`：超空间标签 JSON Schema

## 输入

- node_id：待分解的节点 ID
- project：项目名称

## 输出

- 子节点列表（已写入数据库和文件系统）
- 每个子节点的超空间向量标签（已索引）
- terminal 节点标记为 done，非 terminal 标记为 pending

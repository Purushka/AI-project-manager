---
name: ai-pm-decomposer
description: >
  前向分解器。接收一个节点，根据其层级使用对应的prompt模板将其分解为子节点，
  同时为每个子节点生成超空间向量标签。支持L0-L9十个层级的分解。
  使用关键词：分解节点、展开子节点、前向分解、生成标签。
version: 0.1.0
user-invocable: true
triggers:
  - "分解节点"
  - "展开"
  - "前向分解"
  - "decompose node"
  - "expand node"
---

# AI PM Decomposer - 前向分解器

## 触发场景

当需要将某个节点按其层级分解为子节点时触发。由 ai-pm-core 调度调用。

## 工作流程

1. **读取节点信息**：从数据库获取目标节点的完整信息
2. **组装上下文**：调用 ai-pm-context 构建该节点的 LLM 调用上下文
3. **加载 prompt 模板**：根据节点层级选择 `references/prompt_L{n}_*.md`
4. **调用 LLM**：将上下文填充到模板中，调用 Claude API 进行分解
5. **解析结果**：从 LLM 输出中提取子节点列表和每个子节点的超空间向量标签
6. **持久化**：
   - 为每个子节点写入 detail.md、summary.md、vector.json
   - 在数据库中创建子节点记录和 parent edge
   - 将结构化标签写入 tags 表
   - 将 summary embedding 写入 ChromaDB

## 脚本

- `scripts/decompose.py`：分解逻辑

## 参考文件

- `references/prompt_L0_vision.md` ~ `prompt_L9_deploy.md`：每层的 prompt 模板
- `references/vector_schema.json`：超空间标签 JSON Schema

## 输入

- node_id：待分解的节点 ID
- project：项目名称

## 输出

- 子节点列表（已写入数据库和文件系统）
- 每个子节点的超空间向量标签（已索引）

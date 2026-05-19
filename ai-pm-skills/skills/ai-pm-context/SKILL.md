---
name: ai-pm-context
description: >
  上下文组装器。根据目标节点的角色和层级，从全局摘要、祖先链、共享组件接口、
  当前任务详情四个来源组装LLM调用上下文，确保总token数不超过150K。
  使用关键词：组装上下文、上下文预算、上下文窗口管理。
version: 0.1.0
user-invocable: true
triggers:
  - "组装上下文"
  - "构建上下文"
  - "context assembly"
  - "build context"
---

# AI PM Context - 上下文组装器

## 触发场景

任何需要调用 LLM 的场景都需要先通过上下文组装器构建合适的上下文。

## 工作流程

1. **确定预算**：根据 config 中的 context_budget 分配四层预算
   - 全局摘要：≤10K tokens
   - 祖先链摘要：≤20K tokens
   - 依赖的共享组件接口：≤30K tokens
   - 当前任务详情：≤60K tokens
2. **组装全局摘要**：读取项目的 global_summary.md
3. **组装祖先链**：沿 parent 边向上遍历，收集每个祖先的 summary.md
4. **组装共享组件接口**：查找当前节点依赖的共享组件，收集其接口定义
5. **组装当前任务**：读取当前节点的 detail.md
6. **裁剪**：如果某层超出预算，进行智能截断（保留开头和结尾）

## 脚本

- `scripts/assemble.py`：上下文组装逻辑

## 输入

- node_id：目标节点 ID
- project：项目名称
- purpose：上下文用途（decompose/cluster/compare/challenge）

## 输出

- 组装好的上下文字典：{global_summary, ancestor_chain, shared_interfaces, current_task}
- token 使用统计

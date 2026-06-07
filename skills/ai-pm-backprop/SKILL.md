---
name: ai-pm-backprop
description: >
  内容重写反向优化引擎。对聚类发现的重叠节点执行实际内容重写：
  检测内容重叠 → 提取共享组件 → 重写原始节点 → 解决卡死冲突 → 重新推导父摘要。
  使用写锁保证并发安全，同步知识库。不依赖挑刺 Agent 批准即可执行。
  使用关键词：反向优化、内容重写、提取共享、冲突解决、回传修正。
version: 0.2.0
user-invocable: true
triggers:
  - "反向优化"
  - "内容重写"
  - "提取共享组件"
  - "backpropagate"
  - "backward optimize"
---

# AI PM Backprop - 内容重写反向优化引擎

## 触发场景

前向分解完成后，聚类引擎发现节点间内容重叠。Backprop 对重叠节点执行实际内容修改（不仅仅是创建边）。

## 核心原则

- **实际重写内容**：不只是标记关系，而是修改节点 detail.md/summary.md
- **写锁保护**：修改任何节点前必须获取锁，防止并发冲突
- **知识库同步**：每次内容变更自动同步到 KB
- **收敛控制**：alignment_count > 4 时强制 LLM 生成具体解决方案

## 工作流程

```
detect_overlap → extract_shared_component → rewrite_node_content → resolve_conflict → rederive_parent
```

1. **检测重叠** (detect_overlap)：LLM 分析同一聚类中两个节点的内容，识别共享部分
   - 输入：node_a detail + node_b detail
   - 输出：shared_content 描述 + overlap_type (data_model/api_interface/business_logic/user_flow)

2. **提取共享组件** (extract_shared_component)：
   - 获取写锁
   - 创建新的共享节点（包含公共内容）
   - 写入 detail.md 和 summary.md
   - 同步到知识库
   - 创建 shared_ref 边

3. **重写原始节点** (rewrite_node_content)：
   - 获取写锁
   - 从原始节点中移除已提取的内容
   - 添加对共享组件的引用
   - 更新 summary.md
   - 同步知识库

4. **解决卡死冲突** (resolve_conflict)：
   - 当 edge.alignment_count > 4：两个节点反复对齐但无法收敛
   - LLM 生成具体的解决方案（不是抽象建议）
   - 获取写锁，应用解决方案到两个节点
   - 重置 alignment_count

5. **重新推导父摘要** (rederive_parent)：
   - 收集所有子节点的当前 summary
   - LLM 重新生成父节点摘要
   - 约束向上传播（constraints 不丢失）

## 写锁协议

```python
CALLER_ID = "backprop"

with db.locked(node_id, CALLER_ID):
    db.update_node_content(node_id, new_detail, new_summary, CALLER_ID)
    kb.sync_node(node_id, project, title, new_content)
```

- TTL: 300 秒（默认）
- 获取失败：等待并重试，不跳过
- 释放：操作完成后立即释放

## 脚本

- `scripts/propagate.py`：完整的反向优化管线

## 输入

- project：项目名称
- clusters：聚类结果列表（来自 ai-pm-hyperspace）
- config：LLM 和数据库配置

## 输出

- 新创建的共享组件节点列表
- 被重写的原始节点列表
- 解决的冲突列表
- 重新推导的父节点列表

---
name: ai-pm-comparator
description: >
  对比Agent。分析超空间聚类产生的每个聚类簇，深入对比簇内节点的异同，
  决定最佳合并策略（提取共享组件/合并重复/参数化/保持独立）。
  使用关键词：对比分析、合并策略、共享组件设计、去重。
version: 0.1.0
user-invocable: true
triggers:
  - "对比分析"
  - "合并策略"
  - "分析聚类"
  - "compare clusters"
  - "merge strategy"
---

# AI PM Comparator - 对比 Agent

## 触发场景

超空间聚类完成后，对每个聚类簇进行深度分析，决定合并策略。

## 工作流程

1. **加载簇信息**：读取聚类结果中每个簇的成员节点
2. **深度对比**：为每个簇调用 LLM 分析成员间的异同
   - 共同的业务逻辑
   - 差异化的部分
   - 可参数化的维度
3. **策略决策**：根据分析结果选择合并策略
   - EXTRACT_SHARED：提取共同部分为共享组件
   - MERGE_DUPLICATES：完全合并为一个组件
   - PARAMETERIZE：通过参数化统一接口
   - KEEP_SEPARATE：保持独立（差异太大）
4. **设计共享组件**：对于需要合并的簇，设计共享组件的接口

## 脚本

- `scripts/compare.py`：对比和策略决策逻辑

## 输入

- 聚类簇列表（Cluster 对象）
- project：项目名称

## 输出

- MergePlan 列表，每个包含策略和共享组件设计

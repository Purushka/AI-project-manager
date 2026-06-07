---
name: ai-pm-hyperspace
description: >
  超空间聚类引擎。利用节点的超空间向量标签进行多维聚类，发现跨子系统的复用机会。
  支持基于结构化标签的集合运算和基于embedding的语义聚类两种模式。
  在反向优化阶段对叶节点进行聚类，不依赖固定检查点层级。
  使用关键词：聚类、复用发现、超空间分析、相似节点、标签聚类。
version: 0.2.0
user-invocable: true
triggers:
  - "聚类分析"
  - "复用发现"
  - "超空间聚类"
  - "find reuse"
  - "cluster nodes"
---

# AI PM Hyperspace - 超空间聚类引擎

## 触发场景

在反向优化阶段，对叶节点或指定深度的节点进行聚类分析，发现潜在的共享组件和复用机会。不依赖固定的检查点层级，可在任意深度运行。

## 工作流程

1. **收集标签**：从数据库中提取目标节点的超空间向量标签
2. **结构化聚类**：基于 tags 表做 Jaccard 集合运算 + DBSCAN
   - 相同 domain 标签的节点
   - 相同 entities 的节点
   - 相似 api_shape 的节点
   - 相同 patterns 的节点
3. **语义聚类**：基于 ChromaDB 中的 summary embedding 做 KNN 聚类
4. **交叉验证**：将结构化聚类和语义聚类的结果交叉比对，提高精度
5. **输出聚类簇**：每个簇包含成员节点、共同特征、建议的合并策略

## 脚本

- `scripts/cluster.py`：聚类逻辑

## 输入

- project：项目名称
- depth：目标聚类深度（可选，默认对叶节点聚类）

## 输出

- 聚类簇列表（Cluster 对象）

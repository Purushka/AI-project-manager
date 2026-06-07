---
name: ai-pm-hyperspace
description: >
  混合聚类引擎。使用加权 Jaccard（轴权重 domain=3.0 → complexity=0.3）和
  自适应 DBSCAN（eps=median*0.7）两种模式发现跨子系统复用机会。
  在反向优化阶段对叶节点进行聚类，不依赖固定检查点层级。
  使用关键词：聚类、复用发现、超空间分析、相似节点、标签聚类。
version: 0.3.0
user-invocable: true
triggers:
  - "聚类分析"
  - "复用发现"
  - "超空间聚类"
  - "find reuse"
  - "cluster nodes"
---

# AI PM Hyperspace - 混合聚类引擎

## 触发场景

在反向优化阶段，对叶节点或指定深度的节点进行聚类分析，发现潜在的共享组件和复用机会。不依赖固定的检查点层级，可在任意深度运行。

## 聚类方法

### 1. 加权 Jaccard 聚类 (tag_cluster)

按轴权重计算节点间相似度，高权重轴的匹配贡献更大：

| 轴 | 权重 | 信号强度 |
|----|------|----------|
| domain | 3.0 | 最强：同领域 = 很可能相关 |
| entity | 2.5 | 强：共享数据模型 |
| pattern | 2.0 | 中强：共享架构模式 |
| actor | 1.5 | 中：面向同一用户群 |
| nfr / biz_metrics | 1.0 | 中 |
| tech_stack | 0.8 | 弱："backend" 太常见 |
| complexity | 0.3 | 最弱：几乎无区分力 |

阈值：0.35。低于此值的节点对不会被聚在一起。

使用 single-link agglomeration 从高相似度对开始合并。

### 2. 自适应 DBSCAN 语义聚类 (semantic_cluster)

基于 ChromaDB 中的 summary embedding：
- eps = `median(pairwise_cosine_distance) × 0.7`
- clamped to [0.1, 0.5]
- min_samples = 2

### 3. 混合聚类 (hybrid_cluster)

组合两种方法的结果：
- 如果语义簇是标签簇的超集 → 保留语义簇
- 否则两者都保留

## 工作流程

1. **收集标签**：从数据库提取目标节点的 tags
2. **加权 Jaccard 聚类**：计算 pairwise 相似度 → agglomeration
3. **语义聚类**：ChromaDB embedding → adaptive DBSCAN
4. **合并去重**：交叉验证，合并重叠簇
5. **输出**：每个簇包含成员节点、共同特征、建议合并策略

## 脚本

- `scripts/cluster.py`：完整聚类逻辑（tag_cluster, semantic_cluster, hybrid_cluster）

## 输入

- project：项目名称
- depth：目标聚类深度（可选，默认对叶节点聚类）

## 输出

- 聚类簇列表（Cluster 对象），每个包含：
  - members：节点 ID 列表
  - shared_features：共同标签
  - reason：聚类原因描述
  - suggested_action：建议策略（extract_shared / merge_duplicates）

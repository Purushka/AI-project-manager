---
name: ai-pm-context
description: >
  上下文组装器。根据目标节点的位置，按三档优先级组装 LLM 调用上下文。
  Tier 1 必选（项目摘要+当前节点+父节点），Tier 2 重要（相关节点接口+合约），
  Tier 3 辅助（兄弟标题+祖先接口）。质量底线：Tier 1 不足则停止而非降级。
  使用关键词：组装上下文、上下文预算、上下文窗口管理。
version: 0.2.0
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

## 三档预算模型

| 档位 | 优先级 | 估算 | 内容 |
|------|--------|------|------|
| Tier 1 | 必选 | ~850 tokens | 项目摘要 + 当前节点完整内容 + 父节点 compacted |
| Tier 2 | 重要 | ~800 tokens | Top-5 相关节点接口 + 边合约 |
| Tier 3 | 辅助 | 剩余空间 | 兄弟节点标题 + 祖先接口 |

**质量底线**：如果 Tier 1 无法装入上下文窗口，系统停止并报告，不进行降质操作。

## 工作流程

1. **计算可用空间**：模型上下文窗口 - 系统 prompt - 预留输出
2. **组装 Tier 1**（必须全量装入）：
   - 读取项目 session_brief.md（~300 tokens cold-start 摘要）
   - 读取当前节点 detail.md（full 压缩级别）
   - 读取父节点 summary.md（compacted 压缩级别）
3. **质量检查**：Tier 1 是否完整？不完整则终止
4. **组装 Tier 2**（按相关度排序截断）：
   - 查询 top-5 相关节点（通过边或 KB 语义搜索）
   - 收集其 interface 压缩级别内容 + edge contracts
5. **组装 Tier 3**（填满剩余空间）：
   - 兄弟节点标题列表
   - 祖先链接口（从近到远，装不下就停）
6. **返回**：组装结果 + token 使用统计

## 压缩级别对应

| 级别 | ~大小 | 内容 |
|------|-------|------|
| full | ~500t | 完整描述、决策、标签 |
| compacted | ~150t | 摘要 + 接口 + 约束 + 关键决策 |
| interface | ~80t | 标题 + 接口签名 + 约束 |

**约束在所有级别中都保留。**

## 脚本

- `scripts/assemble.py`：上下文组装逻辑

## 输入

- node_id：目标节点 ID
- project：项目名称
- purpose：上下文用途（decompose / backward_optimize / export）

## 输出

- 组装好的上下文字典：{tier1, tier2, tier3}
- token 使用统计：{tier1_tokens, tier2_tokens, tier3_tokens, total, budget_remaining}
- 如果 Tier 1 不足：返回 error 而非降质结果

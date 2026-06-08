# 自适应节点分解

你是一位资深产品/技术架构师。你的任务是将一个节点分解为更细粒度的子节点。

## 关键规则

1. **层只是深度，没有语义**：depth-0 是最粗的，depth-N 是最细的。层本身不代表"愿景"、"子系统"、"模块"等固定概念。
2. **分解由内容复杂度驱动**：简单的分支可能 depth-2 就到底了，复杂的分支可能需要 depth-12。
3. **终止条件**：子节点达到"接口级"就停止 —— 输入、输出、副作用、约束条件明确即可。
4. **禁止输出代码**：分解到接口定义为止。不要生成任何实现代码、伪代码、代码骨架、函数体、SQL语句、配置文件内容。描述"做什么"和"接口是什么"，不描述"怎么实现"。
5. **不要机械拆分**：按功能边界和交付单元划分，不是按文档章节。
6. **粒度均匀**：同一个父节点下的子节点粒度应大致相当。

## 上下文

### 全局摘要
{{ global_summary }}

### 祖先链（从根到当前节点）
{{ ancestor_chain }}

### 当前节点
**标题**: {{ parent_title }}
**深度**: {{ current_depth }}
**内容**:
{{ current_task }}

## 你的任务

将当前节点分解为子节点。对每个子节点：
1. 判断它是否已经到"接口级"（terminal）还是需要进一步分解
2. 对 terminal 节点，评估其**代码可实现性** —— 基于当前技术栈，这个接口定义是否能被一个工程师直接实现

输出严格的 JSON，不要任何其他文字：

```json
{
  "children": [
    {
      "title": "子节点标题",
      "description": "详细描述这个子节点做什么",
      "summary": "一句话摘要",
      "is_terminal": false,
      "terminal_reason": "",
      "feasibility": {
        "implementable": true,
        "risk": "none / low / medium / high",
        "concerns": ""
      },
      "vector": {
        "domain": "业务领域 (kebab-case, e.g. user-auth, payment, content-mgmt)",
        "entity": ["核心数据实体 (e.g. user, order, subscription)"],
        "pattern": ["架构模式 (e.g. crud, event-driven, batch-pipeline)"],
        "actor": ["参与角色 (e.g. end-user, admin, system-scheduler)"],
        "nfr": ["非功能需求 (e.g. low-latency, high-availability, audit-trail)"],
        "tech_stack": "技术栈 (e.g. react, postgresql, redis)",
        "user_facing": "user-facing / internal / hybrid",
        "complexity": "low / medium / high / very-high",
        "dependency": "independent / light / heavy",
        "data_sensitivity": "public / internal / sensitive / critical",
        "revenue_impact": "direct / indirect / supporting / none",
        "timeline_priority": "mvp / phase-1 / phase-2 / phase-3",
        "biz_metrics": "核心业务指标 (e.g. conversion-rate, dau, arpu)"
      }
    }
  ]
}
```

- `is_terminal`: true 表示这个子节点已经到接口级了（输入/输出/副作用/约束明确），不需要继续分解
- `terminal_reason`: 如果 is_terminal=true，简述为什么它已经是接口级可交付的
- `feasibility`: 可实现性自查（对所有节点填写，terminal 节点必填）
  - `implementable`: 基于声明的技术栈，这个接口能否被直接编码实现
  - `risk`: 实现风险等级。high = 依赖未验证技术、性能要求超常规、或需要尚不存在的外部能力
  - `concerns`: 如果 risk 不是 none，说明具体顾虑（如"需要实时双向同步但无现成方案"、"依赖第三方 API 无 SLA 保证"）
- 子节点数量通常 3-8 个，视内容复杂度而定
- **如果某个 terminal 节点 implementable=false 或 risk=high，你应该继续分解它直到每个子节点都可实现，或在 concerns 中明确标注需要人工决策的点**

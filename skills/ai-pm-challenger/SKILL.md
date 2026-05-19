---
name: ai-pm-challenger
description: >
  挑刺Agent。对对比Agent提出的合并方案进行对抗性验证，
  从可维护性、性能、耦合度、团队认知负荷等角度挑战合并决策。
  使用关键词：验证合并、挑战方案、对抗性审查、质疑合并。
version: 0.1.0
user-invocable: true
triggers:
  - "验证合并"
  - "挑战方案"
  - "对抗性审查"
  - "challenge merge"
  - "validate plan"
---

# AI PM Challenger - 挑刺 Agent

## 触发场景

对比 Agent 产出合并方案后，由挑刺 Agent 进行对抗性验证。

## 工作流程

1. **审查合并方案**：阅读 MergePlan 的策略和设计
2. **对抗性分析**：从多个维度挑战合并决策
   - 耦合度：合并后是否引入不必要的耦合？
   - 性能：共享组件是否成为性能瓶颈？
   - 可维护性：合并后的组件是否过于复杂？
   - 团队分工：合并是否跨越团队边界？
   - 变更频率：被合并的部分是否有不同的变更节奏？
3. **裁决**：批准或否决，给出理由
4. **改进建议**：如果否决，提出改进方向

## 脚本

- `scripts/challenge.py`：对抗性验证逻辑

## 输入

- MergePlan 列表
- project：项目名称

## 输出

- 更新后的 MergePlan（含 challenger_verdict 和 approved 字段）

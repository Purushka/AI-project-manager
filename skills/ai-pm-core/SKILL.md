---
name: ai-pm-core
description: >
  AI产品经理主入口。接收产品idea后，先进行多轮需求访谈（目标用户、核心价值、
  范围边界、技术约束、业务上下文），确认需求后再启动十层递归分解。
  管理状态机调度，协调前向分解、超空间聚类、对比验证、反向传播等阶段。
  使用关键词：产品分解、idea分析、AI PM、启动项目、项目规划。
version: 0.2.0
user-invocable: true
triggers:
  - "产品分解"
  - "分解这个idea"
  - "启动AI PM"
  - "项目规划"
  - "开始分析产品"
  - "decompose product"
  - "start ai pm"
---

# AI PM Core - 主调度入口

## 触发场景

当用户提供一个产品 idea 并希望将其分解为可执行落地方案时触发。

## 核心原则

**不要拿到 idea 就开始拆。** 先通过多轮访谈确认需求，再动手分解。

## 工作流程

### 阶段一：需求访谈（INTERVIEWING）

收到 idea 后，依次就 5 个维度向用户提问：

1. **目标用户**：用户画像、角色划分、痛点和替代方案
2. **核心价值**：核心问题、差异化优势、商业模式
3. **范围边界**：MVP 范围、排除项、优先级分期
4. **技术约束**：技术栈偏好、外部依赖、性能预期
5. **业务上下文**：团队规模、时间线、合规要求、预算

每个维度收到回答后推进到下一个。5 个维度全部收集完毕后，LLM 分析完整度：
- 完整度 ≥ 阈值：进入确认阶段
- 完整度不足：生成追问列表，继续访谈

### 阶段二：需求确认（CONFIRMING）

基于访谈记录生成结构化**需求确认书**（requirements.md），包含：
- 产品概述、目标用户、核心功能范围
- 明确不做的事、技术约束、业务约束
- 关键风险、成功指标

用户审阅后可以：
- **确认**：进入分解阶段
- **提修改意见**：更新记录后重新生成确认书

### 阶段三：十层分解（DECOMPOSING -> CLUSTERING -> ... -> DONE）

确认后才创建根节点并启动前向分解。后续阶段同原流程：
- V1 前向分解（L0-L9）
- V3 超空间聚类 + 对比验证（检查点 L2/L4/L6/L9）
- V2 反向传播

## 状态机

```
INIT -> INTERVIEWING -> CONFIRMING -> DECOMPOSING -> CLUSTERING -> COMPARING -> CHALLENGING -> BACKPROP -> DECOMPOSING -> ... -> DONE
```

每个状态转换都持久化到数据库，支持断点续跑。

## API

### init_project(idea_text, project_name) -> dict
初始化项目并返回第一个访谈问题。**不会**立即开始分解。

### submit_interview_answer(project, answer) -> dict
提交用户对当前访谈问题的回答，返回下一个问题或分析结果。

### confirm_requirements(project, user_response) -> dict
用户确认或修订需求确认书。确认后才进入分解阶段。

### run_decomposition_step(project) -> dict
执行一步分解。如果还在访谈/确认阶段会返回错误提示。

### get_project_status(project) -> dict
获取项目当前状态，包括访谈进度或分解进度。

## 执行方式

```bash
cd "D:\github repositories\AI_pm\ai-pm-skills"

# 1. 初始化项目（返回第一个访谈问题）
python -c "
import sys; sys.path.insert(0, '.')
from skills.ai_pm_core.scripts.main import init_project
import json; print(json.dumps(init_project('你的产品idea...', 'my_project'), indent=2, ensure_ascii=False))
"

# 2. 提交访谈回答（循环调用直到进入确认阶段）
python -c "
import sys; sys.path.insert(0, '.')
from skills.ai_pm_core.scripts.main import submit_interview_answer
import json; print(json.dumps(submit_interview_answer('my_project', '用户的回答...'), indent=2, ensure_ascii=False))
"

# 3. 确认需求（回复'确认'开始分解，或提修改意见）
python -c "
import sys; sys.path.insert(0, '.')
from skills.ai_pm_core.scripts.main import confirm_requirements
import json; print(json.dumps(confirm_requirements('my_project', '确认'), indent=2, ensure_ascii=False))
"
```

## 输入

- 产品 idea 文本（自然语言描述）
- 用户对访谈问题的逐一回答
- 需求确认书的确认/修改意见

## 输出

- 多轮访谈问题（5 个维度 + 可能的追问）
- 结构化需求确认书（requirements.md）
- 确认后：完整的十层分解树

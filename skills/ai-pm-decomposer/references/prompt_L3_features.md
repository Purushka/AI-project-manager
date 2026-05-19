# L3 功能清单

## 全局背景
{{ global_summary }}

## 祖先链
{{ ancestor_chain }}

## 当前任务
你正在为一个模块定义具体的功能点。

父节点：{{ parent_title }}
详情：
{{ current_task }}

## 你的任务

将该模块拆分为具体的功能点（Feature），每个功能点包含：

1. **用户故事**：As a [角色], I want to [行为], so that [价值]
2. **验收标准**：具体的可测试条件（Given-When-Then）
3. **业务规则**：该功能涉及的业务逻辑规则
4. **边界情况**：需要处理的异常和边界情况
5. **优先级**：P0（核心）/ P1（重要）/ P2（nice-to-have）

## 输出格式

```json
{
  "children": [
    {
      "title": "功能名称",
      "description": "用户故事、验收标准、业务规则、边界情况的完整描述",
      "summary": "一句话概括",
      "priority": "P0/P1/P2",
      "acceptance_criteria": ["Given..When..Then.."],
      "vector": {
        "domain": [],
        "entities": [],
        "patterns": [],
        "api_shape": { "inputs": [], "outputs": [], "side_effects": [] },
        "tech_traits": [],
        "actors": [],
        "nfr": [],
        "rule_fingerprint": ""
      }
    }
  ]
}
```

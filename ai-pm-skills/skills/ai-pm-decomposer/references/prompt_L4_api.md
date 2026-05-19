# L4 数据模型与 API 设计

## 全局背景
{{ global_summary }}

## 祖先链
{{ ancestor_chain }}

## 当前任务
你正在为一个功能点设计数据模型和 API。

父节点：{{ parent_title }}
详情：
{{ current_task }}

## 你的任务

为该功能设计完整的数据层和接口层：

1. **数据模型（ER 描述）**：
   - 实体定义（字段、类型、约束）
   - 实体间关系（1:1, 1:N, M:N）
   - 索引设计
2. **API 设计**：
   - RESTful 端点或 GraphQL 查询/变更
   - 请求/响应格式（含字段类型）
   - 认证/授权要求
   - 限流策略
3. **数据流**：数据从输入到持久化的完整流转路径

## 输出格式

```json
{
  "children": [
    {
      "title": "API/数据模型名称",
      "description": "完整的数据模型定义和API设计",
      "summary": "一句话概括",
      "api_spec": {
        "method": "GET/POST/PUT/DELETE",
        "path": "/api/v1/...",
        "request_body": {},
        "response": {}
      },
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

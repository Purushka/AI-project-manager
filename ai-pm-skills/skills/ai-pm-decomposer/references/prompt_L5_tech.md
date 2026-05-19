# L5 技术选型与架构决策

## 全局背景
{{ global_summary }}

## 祖先链
{{ ancestor_chain }}

## 当前任务
你正在为一个 API/数据模型做技术选型和架构决策。

父节点：{{ parent_title }}
详情：
{{ current_task }}

## 你的任务

为该组件做关键技术决策：

1. **技术选型**：
   - 编程语言和框架
   - 数据库类型（关系型/文档型/图/时序）
   - 缓存策略（本地缓存/Redis/CDN）
   - 消息队列（如需要）
2. **架构决策**：
   - 同步 vs 异步处理
   - 分布式策略（分片/副本/一致性级别）
   - 容错机制（重试/熔断/降级）
3. **ADR（Architecture Decision Record）**：
   - 决策背景
   - 考虑的方案
   - 选择的方案及理由
   - 后果和权衡

## 输出格式

```json
{
  "children": [
    {
      "title": "技术决策名称",
      "description": "完整的ADR格式描述",
      "summary": "一句话概括选择和理由",
      "adr": {
        "context": "",
        "options": [],
        "decision": "",
        "consequences": ""
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

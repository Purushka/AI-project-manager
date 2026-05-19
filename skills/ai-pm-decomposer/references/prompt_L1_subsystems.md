# L1 子系统划分

## 全局背景
{{ global_summary }}

## 祖先链
{{ ancestor_chain }}

## 当前任务
你正在将一个子系统进一步拆分为更细粒度的子系统或大模块。

父节点：{{ parent_title }}
详情：
{{ current_task }}

## 你的任务

将该子系统拆分为 5-8 个子部分，重点关注：

1. **边界定义**：每个子系统的职责范围和边界
2. **通信方式**：子系统间如何通信（同步 API / 异步消息 / 事件驱动）
3. **数据所有权**：每个子系统拥有哪些数据
4. **外部依赖**：需要哪些外部服务或第三方集成
5. **共享能力识别**：哪些能力可能被多个子系统复用

## 输出格式

```json
{
  "children": [
    {
      "title": "子部分名称",
      "description": "职责描述、边界定义、与其他子系统的交互方式",
      "summary": "一句话概括",
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

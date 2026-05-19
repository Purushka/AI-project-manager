# L2 模块定义

## 全局背景
{{ global_summary }}

## 祖先链
{{ ancestor_chain }}

## 当前任务
你正在为一个子系统定义具体的软件模块。

父节点：{{ parent_title }}
详情：
{{ current_task }}

## 你的任务

将该子系统拆分为具体的软件模块，每个模块是一个内聚的功能单元：

1. **模块职责**：每个模块负责什么
2. **模块间依赖图**：哪些模块依赖哪些模块（单向依赖，避免循环）
3. **接口边界**：模块对外暴露的接口定义（方法签名级别）
4. **数据模型归属**：每个模块管理哪些数据模型
5. **事件定义**：模块发布/订阅的领域事件

## 输出格式

```json
{
  "children": [
    {
      "title": "模块名称",
      "description": "模块职责、依赖的其他模块、对外接口概述、管理的数据模型",
      "summary": "一句话概括",
      "dependencies": ["依赖的模块名称"],
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

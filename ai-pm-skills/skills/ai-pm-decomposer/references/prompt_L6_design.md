# L6 详细设计

## 全局背景
{{ global_summary }}

## 祖先链
{{ ancestor_chain }}

## 当前任务
你正在为一个技术方案做详细设计。

父节点：{{ parent_title }}
详情：
{{ current_task }}

## 你的任务

产出可以直接指导编码的详细设计文档：

1. **时序图**：核心流程的参与者交互序列（用 Mermaid 语法描述）
2. **状态机**：关键实体的状态转换图
3. **算法描述**：核心算法的伪代码或步骤说明
4. **错误处理**：异常分类和处理策略
5. **并发控制**：锁策略、乐观/悲观并发控制
6. **性能设计**：热点识别和优化策略

## 输出格式

```json
{
  "children": [
    {
      "title": "设计单元名称",
      "description": "包含时序图、状态机、算法描述的完整详细设计",
      "summary": "一句话概括",
      "sequence_diagram": "Mermaid语法的时序图",
      "state_machine": "状态转换描述",
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

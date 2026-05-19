# L8 核心代码实现

## 全局背景
{{ global_summary }}

## 祖先链
{{ ancestor_chain }}

## 当前任务
你正在根据代码骨架实现核心代码。

父节点：{{ parent_title }}
详情：
{{ current_task }}

## 你的任务

为代码骨架填充完整实现：

1. **核心业务逻辑**：完整的方法实现
2. **数据验证**：输入校验和业务规则校验
3. **错误处理**：异常捕获、日志记录、错误码定义
4. **单元测试**：覆盖正常路径、边界情况、异常路径
5. **集成点**：外部服务调用的具体实现
6. **性能优化**：关键路径的优化实现

## 输出格式

```json
{
  "children": [
    {
      "title": "实现单元名称",
      "description": "完整的代码实现，包含业务逻辑、验证、错误处理",
      "summary": "一句话概括实现内容",
      "code": "完整的代码文本",
      "tests": "对应的单元测试代码",
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

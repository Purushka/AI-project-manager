# L7 代码骨架

## 全局背景
{{ global_summary }}

## 祖先链
{{ ancestor_chain }}

## 当前任务
你正在根据详细设计生成代码骨架。

父节点：{{ parent_title }}
详情：
{{ current_task }}

## 你的任务

输出可以直接用作开发脚手架的代码骨架：

1. **文件目录结构**：完整的目录树
2. **类/接口定义**：类名、方法签名、关键属性（带类型注解）
3. **函数签名**：参数类型、返回类型、简要说明
4. **依赖注入点**：哪些组件需要注入
5. **配置项**：需要的环境变量和配置参数
6. **测试骨架**：对应的测试文件结构

## 输出格式

```json
{
  "children": [
    {
      "title": "文件/类名",
      "description": "文件路径、类定义、方法签名、职责说明",
      "summary": "一句话概括",
      "file_path": "src/modules/.../file.py",
      "skeleton": "类和函数签名的代码文本",
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

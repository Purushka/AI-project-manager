# L9 部署方案

## 全局背景
{{ global_summary }}

## 祖先链
{{ ancestor_chain }}

## 当前任务
你正在为一个代码实现设计部署方案。

父节点：{{ parent_title }}
详情：
{{ current_task }}

## 你的任务

设计完整的部署和运维方案：

1. **CI/CD 流水线**：构建、测试、部署的完整流程
2. **Docker 配置**：Dockerfile、docker-compose 配置
3. **基础设施**：云资源清单（计算/存储/网络）
4. **部署策略**：蓝绿部署 / 金丝雀发布 / 滚动更新
5. **监控告警**：
   - 关键指标定义（延迟/错误率/吞吐量）
   - 告警阈值和通知策略
   - 日志收集和分析
6. **回滚方案**：出问题时如何快速回滚
7. **扩容策略**：水平/垂直扩容的触发条件和步骤

## 输出格式

```json
{
  "children": [
    {
      "title": "部署单元名称",
      "description": "完整的部署配置和运维方案",
      "summary": "一句话概括",
      "dockerfile": "Dockerfile内容（如适用）",
      "ci_config": "CI/CD配置内容",
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

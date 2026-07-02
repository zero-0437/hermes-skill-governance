# Route-Map 关键词补齐 Changelog

**日期**: 2026-07-02
**范围**: 12个路由规则文件

## programmer.yaml — 新增修改操作段
- 改(代码|文件|配置|bug|逻辑|函数|接口|功能|一下|成) regex 0.7
- 修改 phrase 0.8
- 优化 phrase 0.7
- 调整 phrase 0.7
- 修正 phrase 0.8
- 更新 phrase 0.7
- 删除 phrase 0.6

## synology-helper.yaml — 新增
- 系统备份 phrase 1.0 fuzzy

## data-analyst.yaml — 新增
- 查一下 phrase 0.6 fuzzy
- 搜一下 phrase 0.6 fuzzy
- 分析 phrase 0.6

## error-analyst.yaml — 新增
- 报错 phrase 0.8 fuzzy
- 日志 phrase 0.7
- 分析代码 phrase 0.8 fuzzy（双审补充）

## ui-designer.yaml — 新增
- 设计 phrase 0.6 fuzzy（动效段与原型段之间）

## memory-agent.yaml — 新增
- 记录 phrase 0.7 fuzzy
- 保存 phrase 0.5 fuzzy
- 回顾 phrase 0.7 fuzzy
- 总结 phrase 0.7 fuzzy

## reality-checker.yaml — 新增
- 试试 phrase 0.5 fuzzy
- 验一下 phrase 0.5 fuzzy
- 测一下 phrase 0.5 fuzzy
- 验证一下 phrase 0.6 fuzzy

## file-ops.yaml — 新增
- 复制 phrase 0.7
- 移动 phrase 0.5
- 删除 phrase 0.6
- 解压 phrase 0.7 fuzzy
- 压缩 phrase 0.7 fuzzy
- 下载 phrase 0.7 fuzzy
- 上传 phrase 0.7 fuzzy
- 重命名 phrase 0.7 fuzzy

## document-processor.yaml — 新增
- 合并文档 phrase 0.9 fuzzy
- 拆分文档 phrase 0.7 fuzzy

## prompt-engineer.yaml — 新增
- 指令 phrase 0.6 fuzzy
- 角色设定 phrase 0.8 fuzzy

## docs-writer.yaml — 新增
- 更新日志 phrase 0.8 fuzzy
- 注释 phrase 0.6 fuzzy

## 审核流程
- spec 合规评审: error-analyst（7处 weight 调整建议）
- 任务拆解: pm-agent（10个 delegation）
- 批量修复: programmer
- 双审: error-analyst spec 合规评审（1处补充）+ programmer 代码质量评审（1处 weight 调整）

合计新增约 36 条短语规则，全部为纯新增不修改现有规则。

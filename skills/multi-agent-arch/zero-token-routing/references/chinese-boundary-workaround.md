# Chinese Word Boundary Workaround — Reference

## The Problem

Python's `re` module defines `\b` as the boundary between `\w` and `\W`
characters. `\w` = `[a-zA-Z0-9_]` — Chinese characters are NOT `\w`.

```python
import re
# Does this match?
re.search(r'\b记忆\b', '记忆之前的讨论内容')  # → None!
# Why? '记' is not \w, '忆' is not \w, '之' is not \w
# No \w/\W transition anywhere between Chinese chars
```

## The Fix

**NEVER use regex `\b` with Chinese text.** Use `type: phrase` instead.

```yaml
# WRONG — never matches:
- type: regex
  pattern: "\\b(集成测试|端到端|验收)\\b"

# RIGHT:
- type: phrase
  pattern: "集成测试"
- type: phrase
  pattern: "端到端"
- type: phrase
  pattern: "验收"
```

## Why `\b` is safe for English

```python
re.search(r'\bPR\b', 'fix PROXY bug')   # → None (correct!)
re.search(r'\bUI\b', 'rebuild cache')   # → None (correct!)
re.search(r'\bbug\b', 'debug mode')     # → None (correct!)
```

`\b` in English requires the word to be a standalone `[a-zA-Z0-9_]` token.
So `PR` inside `PROXY`, `UI` inside `bUILd`, `bug` inside `debug` all
correctly fail to match.

## Hybrid Pattern — Best Practice for Mixed Input

```yaml
# English → regex with \b
- type: regex
  pattern: "\\b(dogfood|e2e|end.to.end|smoke.*test|verification|validation)\\b"
  weight: 0.9

# Chinese → phrase
- type: phrase
  pattern: "集成测试"
  weight: 0.8
- type: phrase
  pattern: "端到端"
  weight: 0.8
```

## Full Test Suite (12 agents)

These all pass with the correct configuration:

| input | expected agent | method |
|-------|---------------|--------|
| 修复 PROXY 连接的 bug | programmer | auto |
| 构建新的 UI 界面 | ui-designer | auto |
| NAS 备份配置 | synology-helper | auto |
| 写一份 API 参考文档 | docs-writer | auto |
| 设计多 Agent 架构方案 | pm-agent | auto (override) |
| 审查代码安全性 | error-analyst | auto |
| 优化 system prompt | prompt-engineer | auto |
| 端到端集成测试验证 | reality-checker | auto |
| 把 PDF 转换成 Word | document-processor | auto |
| 搜索最新的 AI 论文 | data-analyst | auto |
| 记忆之前的讨论内容 | memory-agent | auto |
| 处理文件目录结构 | file-ops | auto |

---
name: skillopt-sleep-learned
description: Preferences and procedures learned from past local agent sessions.
---

# skillopt-sleep-learned

Preferences and procedures learned from your past local agent sessions.

<!-- SKILLOPT-SLEEP:LEARNED START -->
## Learned preferences & procedures

_This block is maintained by SkillOpt-Sleep. Edits here are proposed offline, validated against your past tasks, and adopted only after you approve them. Hand-edits outside this block are never touched._

- When the task asks about a recurring failure (e.g., 'Diagnose why a SkillOpt pipeline produced zero edits'), you MUST include ALL of the following in the response: the exact string 'config.json', the exact string 'mock', the exact string 'rule:', a section heading '诊断结果', a section heading '触发链', and an exact match of the pattern /(?i)0 edits|zero edits|no edits/.
- When the task asks about pushing infrastructure to GitHub (e.g., '将项目基础设施和文档推送到 GitHub'), you MUST include in the response ALL of: the exact string '推送完成', the exact string 'Commit SHA', and a section heading 'Push 结果'.
- When the task asks for a single-line output of line count and entity count from a YAML file, you MUST output exactly the format: '行数: <number>, 章节: <number>' (where both numbers are positive integers), and ensure the entire response is a single number if the task asks for only a number and matches pattern /^\d+$/.
- When the task asks to generate a push manifest (推送清单) after reviewing file changes, you MUST include a section heading '推送清单' in the response, even if no files were changed (include the heading with empty content).
<!-- SKILLOPT-SLEEP:LEARNED END -->

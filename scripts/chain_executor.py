#!/usr/bin/env python3
"""
chain_executor.py — chain 编排引擎（状态机）

调用方式：
  python3 scripts/chain_executor.py advance \\
    --task_id T-001 \\
    --chain_def '[{"agent":"programmer","goal":"..."},{"agent":"error-analyst","goal":"..."}]' \\
    --chain_step_skills '{"programmer_0":["test-driven-development"]}' \\
    --last_result '{"agent":"programmer","status":"DONE","output_path":"..."}'

  python3 scripts/chain_executor.py start \\
    --task_id T-001 \\
    --chain_def '[{"agent":"programmer","goal":"TDD 实现 + self-review"},...]' \\
    --chain_step_skills '{"programmer@0":[...]}' \\
    --chain_owner programmer

  python3 scripts/chain_executor.py run \\
    --task_id T-001 \\
    --chain_agent programmer \\
    --last_result '{"status":"init"}'

chain_executor 不调用 delegate_task — 只产出决策 JSON。
主 Agent 读 JSON → delegate_task → 拿到结果后再调 chain_executor。
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys

try:
    import yaml
except ImportError:
    yaml = None

import copy
import sys as _sys

# 确保 scripts 目录在 sys.path 中（供 from briefer import ... 使用）
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in _sys.path:
    _sys.path.insert(0, _SCRIPTS_DIR)

# Checker engine for structured completion verification
from checker_engine import run_check, run_shell

# briefer — 共享 brief 文件写入工具
try:
    from briefer import (
        write_brief,
        write_chain_step_brief,
        write_sub_brief,
        write_branch_brief,
        write_loop_item_brief,
        get_brief_path,
        ensure_brief_dir,
    )
except ImportError:
    # briefer 未就绪时降级：定义空函数
    def write_brief(*a, **kw): return a[0] if a else ""
    def write_chain_step_brief(*a, **kw): return ""
    def write_sub_brief(*a, **kw): return ""
    def write_branch_brief(*a, **kw): return ""
    def write_loop_item_brief(*a, **kw): return ""
    def get_brief_path(task_id, step_idx=0, suffix=""): return ""
    def ensure_brief_dir(): return

# ── Shell 命令白名单（用于 pipe 模式安全校验）──
SHELL_WHITELIST = frozenset({
    "git", "ls", "cat", "head", "tail", "echo", "find", "grep", "test",
    "sort", "wc", "diff", "cut", "tr", "uniq", "which", "dirname", "basename",
    "pwd", "date", "printf", "env", "mkdir", "touch", "cp", "mv", "rm",
})

from chain_config import SCRIPT_DIR, load_yaml_safe, load_chain, load_index

# ── 路径计算 ────────────────────────────────────

# ── 默认配置 ────────────────────────────────────
MAX_RETRY = 3
MAX_TOTAL_ITERATIONS = 100    # 全局迭代次数上限
CHAIN_TIMEOUT = 3600           # 链执行 wall-clock 超时（秒）
STATE_DIR = "/opt/data/.shared"
INDEX_YAML_PATH = os.path.join(SCRIPT_DIR, "..", "route-map", "index.yaml")

# ── verification 常量 ────────────────────────────
VERIFICATION_TIMEOUT = 30          # 每个 verify_command 的超时秒数
MAX_OUTPUT_LENGTH = 2000           # stdout/stderr 截断长度
VERIFY_COMMAND_BASENAMES = frozenset({
    "test", "true", "false", "git", "head", "cat", "grep",
    "wc", "diff", "echo", "ls", "sort", "uniq", "cut", "tr",
    "sed", "awk", "find", "xargs",
})

# ── per-step 合法回报状态映射 ────────────────────
STEP_VALID_STATUSES = {
    "tdd":           ["DONE", "APPROVE", "BLOCKED", "NEEDS_FIX", "NEEDS_CONTEXT", "DONE_WITH_CONCERNS"],
    "spec-review":   ["DONE", "NEEDS_FIX", "BLOCKED", "NEEDS_CONTEXT", "DONE_WITH_CONCERNS"],
    "quality-review":["APPROVE", "DONE", "NEEDS_FIX", "BLOCKED", "NEEDS_CONTEXT"],
    "fix":           ["DONE", "BLOCKED", "NEEDS_CONTEXT"],
}

# ── 新增 step type 常量 ───────────────────────────────────
STEP_TYPE_SERIAL = "serial"
STEP_TYPE_PARALLEL = "parallel"
STEP_TYPE_INTERACTIVE = "interactive"
STEP_TYPE_LOOP = "loop"

# 新状态码（返回给主 Agent 的决策）
STATUS_CONTINUE_PARALLEL = "CONTINUE_PARALLEL"
STATUS_CONTINUE_LOOP = "CONTINUE_LOOP"
STATUS_BRANCHES_COMPLETE = "BRANCHES_COMPLETE"
STATUS_LOOP_COMPLETE = "LOOP_COMPLETE"

# Verification gate 状态码
STATUS_VERIFIED = "VERIFIED"
STATUS_VERIFICATION_FAILED = "VERIFICATION_FAILED"
STATUS_NO_CONTRACT = "NO_CONTRACT"

# goal 中是否包含这些关键词来推断步骤类型
STEP_TYPE_KEYWORDS = {
    "quality-review":["质量", "quality"],      # 先匹配（更精确）
    "spec-review":  ["spec", "合规", "规范", "评审"],
    "tdd":          ["tdd", "实现", "implement"],
    "fix":          ["fix", "修复", "根据 review"],
}


def _infer_step_type(goal: str) -> str:
    """从 goal 推断步骤类型（用于合法性校验）"""
    goal_lower = goal.lower()
    for stype, keywords in STEP_TYPE_KEYWORDS.items():
        if any(kw in goal_lower for kw in keywords):
            return stype
    return "tdd"  # 默认


def _get_step_type(step: dict) -> str:
    """判断 step 类型：serial / parallel / interactive / loop"""
    stype = step.get("type", STEP_TYPE_SERIAL)
    if stype == STEP_TYPE_SERIAL and step.get("interactive") is True:
        return STEP_TYPE_INTERACTIVE
    return stype


def _build_parallel_result(step: dict, step_idx: int, task_id: str = "") -> dict:
    """为 parallel 步骤构建 CONTINUE_PARALLEL 响应。

    返回结构包含 branches 列表和 join_strategy，
    主 Agent 收到后需并行 delegate_task 所有 branches。

    同时为每个 branch 写入 brief 文件：
      {task_id}-step{step_idx}-branch{i}.md
    """
    branches = step.get("branches", [])
    if not branches:
        return {"status": "ERROR", "diagnosis": f"step[{step_idx}] parallel 没有 branches"}

    branch_tasks = []
    for i, b in enumerate(branches):
        task = {
            "agent": b["agent"],
            "goal": b["goal"],
            "context": b.get("context", ""),
        }
        if b.get("keywords"):
            task["keywords"] = b["keywords"]
        branch_tasks.append(task)

        # ── 写 branch brief 文件 ──
        if task_id:
            try:
                brief_path = write_sub_brief(
                    task_id=task_id,
                    agent=b["agent"],
                    goal=b["goal"],
                    step_idx=step_idx,
                    suffix=f"-branch{i}",
                    skills=b.get("skills"),
                    keywords=b.get("keywords"),
                )
                task["brief_file"] = brief_path
            except Exception:
                pass  # 不阻塞 parallel 执行

    return {
        "status": STATUS_CONTINUE_PARALLEL,
        "next": branch_tasks,
        "join_strategy": step.get("join_strategy", "separate"),
        "branch_count": len(branches),
        "context": {"chain_step": step_idx, "step_type": STEP_TYPE_PARALLEL},
    }


def _build_interactive_result(step: dict, step_idx: int, task_id: str = "") -> dict:
    """为 interactive 步骤构建 NEEDS_CONTEXT 响应（带 interactive 标记）。

    主 Agent 收到后应暂停链并询问用户确认。
    同时写入 step brief 文件。
    """
    result = {
        "status": "NEEDS_CONTEXT",
        "step_idx": step_idx,
        "agent": step["agent"],
        "goal": step["goal"],
        "question": f"[{step['agent']}] 已完成: {step['goal']}\n"
                    f"请确认结果，或补充修改意见后继续下一步。",
        "interactive": True,
    }
    if step.get("keywords"):
        result["keywords"] = step["keywords"]
    if step.get("jump_map"):
        result["jump_map"] = step["jump_map"]

    # ── 写 step brief 文件 ──
    if task_id:
        try:
            brief_path = write_chain_step_brief(
                task_id=task_id, step=step, step_idx=step_idx, skills=[]
            )
            result["brief_file"] = brief_path
        except Exception:
            pass  # 不阻塞 interactive 执行

    return result


def _build_loop_result(step: dict, step_idx: int, context: dict,
                        task_id: str = "") -> dict:
    """为 loop 步骤构建 CONTINUE_LOOP 响应。

    从 context 取出 source 数据展开为多个 loop items，
    主 Agent 收到后需逐个执行并按 loop_complete 回传。

    同时为每个 loop item 写入 brief 文件：
      {task_id}-step{step_idx}-loop{i}.md
    """
    source = step.get("source", "previous_output")
    items = context.get(source, [])

    if not items:
        # 没有数据源 → 返回空循环（主 Agent 可跳过）
        return {
            "status": STATUS_CONTINUE_LOOP,
            "next": [],
            "loop_count": 0,
            "context": {"chain_step": step_idx, "step_type": STEP_TYPE_LOOP},
        }

    loop_items = []
    for i, item in enumerate(items):
        lo = {
            "agent": step["agent"],
            "goal": step["goal"],
            "loop_context": item,
            "loop_index": i,
        }
        if step.get("keywords"):
            lo["keywords"] = step["keywords"]
        loop_items.append(lo)

        # ── 写 loop item brief 文件 ──
        if task_id:
            try:
                brief_path = write_sub_brief(
                    task_id=task_id,
                    agent=step["agent"],
                    goal=step["goal"],
                    step_idx=step_idx,
                    suffix=f"-loop{i}",
                    skills=step.get("skills"),
                    keywords=step.get("keywords"),
                )
                lo["brief_file"] = brief_path
            except Exception:
                pass  # 不阻塞 loop 执行

    return {
        "status": STATUS_CONTINUE_LOOP,
        "next": loop_items,
        "loop_count": len(loop_items),
        "context": {"chain_step": step_idx, "step_type": STEP_TYPE_LOOP},
    }


def _should_skip_step(step: dict, state: dict, step_idx: int) -> dict | None:
    """检查下一步是否应因 retry 计数达到 skip_threshold 而跳过。

    解析 step 中的 skip_threshold（int，默认 0=不跳过），
    从 state 中获取当前 step 的 retry 计数（spec_retry / quality_retry），
    若 retry 计数 ≥ skip_threshold，返回 SKIPPED 决策。

    参数:
        step: 下一步的 chain_def 元素
        state: 当前状态字典
        step_idx: 下一步的索引

    返回:
        SKIPPED 决策字典，或 None（不跳过）
    """
    skip_threshold = step.get("skip_threshold", 0)
    if skip_threshold <= 0:
        return None  # 不跳过

    spec_retry = state.get("spec_retry", 0)
    quality_retry = state.get("quality_retry", 0)
    max_retry = max(spec_retry, quality_retry)

    if max_retry >= skip_threshold:
        return {
            "status": "SKIPPED",
            "step_idx": step_idx,
            "diagnosis": f"达到 skip_threshold {skip_threshold} 次，跳过",
        }
    return None


def aggregate_parallel_results(branch_results: list[dict], join_strategy: str) -> dict:
    """聚合并行分支的结果。

    导出的公共函数，供主 Agent 在收集所有并行委托后调用。

    参数:
        branch_results: 每个元素为 {name, summary, findings, ...}
        join_strategy: "separate" — 不交叉排序，保留各轴完整性
                       "synthesize" — 对比合成

    返回:
        聚合后的结果 dict
    """
    if join_strategy == "separate":
        return {
            "status": "DONE",
            "output_type": "separate_report",
            "reports": {
                r.get("name", f"branch_{i}"): {
                    "content": r.get("summary", ""),
                    "findings": r.get("findings", []),
                }
                for i, r in enumerate(branch_results)
            },
            "summary": "并行结果已按轴独立输出，未做交叉排序",
        }
    elif join_strategy == "synthesize":
        return {
            "status": "DONE",
            "output_type": "synthesized_report",
            "individual_reports": {
                r.get("name", f"branch_{i}"): r.get("summary", "")
                for i, r in enumerate(branch_results)
            },
            "comparison": {
                "common_points": [],
                "divergences": [],
                "_warning": "synthesize 聚合策略为简化实现，仅保留各分支独立报告，未做自动对比合成。如需完整对比，请在主 Agent 层自行实现。",
            },
        }
    else:
        return {"status": "ERROR", "diagnosis": f"未知聚合策略: {join_strategy}"}


def _validate_skills(chain_def: list, chain_step_skills: dict, chain_owner: str) -> list:
    """验证所有 serial chain step 都有对应的 skills key。返回错误列表，空列表表示无错误。

    跳过 parallel / interactive / loop 类型步骤，它们不需要 skills key。
    支持两种 key 格式：
      - {chain_owner}@{idx}（单 Agent 链）
      - {agent}@{idx}（多 Agent 链，如 pub-chain）
    """
    errors = []
    for i, step in enumerate(chain_def):
        step_type = _get_step_type(step)
        if step_type != STEP_TYPE_SERIAL:
            continue  # 非 serial 步骤无需 skills key
        owner_key = f"{chain_owner}@{i}"
        agent_key = f"{step['agent']}@{i}"
        if owner_key not in chain_step_skills and agent_key not in chain_step_skills:
            errors.append(f"缺少 skills key: '{owner_key}' 或 '{agent_key}' (step {i}: {step['agent']} → {step['goal']})")
    return errors


def _sanitize_task_id(task_id: str) -> str:
    """净化 task_id，防止路径遍历攻击"""
    if not re.match(r'^[a-zA-Z0-9_.-]+$', task_id):
        raise ValueError(f"非法 task_id: {task_id}（仅允许字母、数字、下划线、点、连字符）")
    return task_id


def _state_path(task_id: str) -> str:
    """构建状态文件的完整路径。

    参数:
        task_id: 任务标识符（仅允许字母、数字、下划线、点、连字符）

    返回:
        状态文件的绝对路径

    异常:
        ValueError: task_id 包含非法字符时由 _sanitize_task_id 抛出
    """
    _sanitize_task_id(task_id)
    return os.path.join(STATE_DIR, task_id, "chain-state.json")


def _try_recover_from_checkpoint(task_id: str) -> dict | None:
    """尝试从最近的有效 checkpoint 重建 state。

    Checkpoint 存储在 state 同一目录下的 chain-checkpoint.json 文件中。
    如果 checkpoint 存在且完整，重建包含 current_step、completed_outputs 等字段的 state。

    参数:
        task_id: 任务标识符

    返回:
        重建的状态字典，如果 checkpoint 不存在或损坏则返回 None
    """
    ckpt_path = os.path.join(STATE_DIR, task_id, "chain-checkpoint.json")
    if not os.path.exists(ckpt_path):
        return None
    try:
        with open(ckpt_path) as f:
            ckpt = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[RECOVERY] checkpoint JSON 解析失败: {ckpt_path} — {e}", file=sys.stderr)
        return None

    step_idx = ckpt.get("step_idx")
    if step_idx is None:
        print(f"[RECOVERY] checkpoint 缺少 step_idx 字段 (task_id={task_id})", file=sys.stderr)
        return None

    completed_outputs = ckpt.get("completed_outputs", [])
    print(f"[RECOVERY] 从 checkpoint 重建 state: task_id={task_id}, step={step_idx}", file=sys.stderr)

    # 重建 context，保留 checkpoint 中的 diff_path 和 last_output（如有）
    context = {"completed_outputs": completed_outputs}
    if ckpt.get("context_diff_path"):
        context["diff_path"] = ckpt["context_diff_path"]
    if ckpt.get("context_last_output"):
        context["last_output"] = ckpt["context_last_output"]

    return {
        "current_step": step_idx,
        "spec_retry": ckpt.get("spec_retry", 0),
        "quality_retry": ckpt.get("quality_retry", 0),
        "concerns": ckpt.get("concerns", []),
        "context": context,
        "total_iterations": ckpt.get("total_iterations", 0),
        "chain_started_at": None,
        "last_checkpoint": ckpt,
    }


def _load_state(task_id: str) -> dict | None:
    """从磁盘加载指定 task 的状态数据。

    如果状态文件不存在，返回默认初始状态（current_step=0, retry 计数器归零, concerns=[]）。

    如果状态文件损坏或关键字段缺失，尝试从 checkpoint 恢复。
    如果 checkpoint 也存在但损坏，返回 None 让调用方重新 init。

    参数:
        task_id: 任务标识符

    返回:
        状态字典，包含 current_step、spec_retry、quality_retry、concerns、context 等字段。
        返回 None 表示状态完全损坏且无法恢复，调用方应重新 init。
    """
    path = _state_path(task_id)
    if not os.path.exists(path):
        return {
            "current_step": 0,
            "spec_retry": 0,
            "quality_retry": 0,
            "concerns": [],
            "context": {},
            "total_iterations": 0,
            "chain_started_at": None,
            "last_checkpoint": None,
        }
    state = None
    try:
        with open(path) as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[RECOVERY] state JSON 解析失败: {path} — {e}", file=sys.stderr)
        state = None

    # 检查关键字段是否完整
    if state is not None and "current_step" not in state:
        print(f"[RECOVERY] state 缺少关键字段 current_step (task_id={task_id})", file=sys.stderr)
        state = None

    if state is not None:
        return state

    # ── 尝试从 checkpoint 恢复 ──
    state = _try_recover_from_checkpoint(task_id)
    if state is not None:
        return state

    return None


def _save_state(task_id: str, state: dict):
    """将状态数据原子化写入磁盘。

    使用临时文件 + os.replace 确保写入原子性，避免断电/崩溃导致文件损坏。
    写入前会创建目标目录（如果不存在）。

    参数:
        task_id: 任务标识符
        state: 要持久化的状态字典

    异常:
        OSError: 目录创建或文件写入失败时抛出
    """
    path = _state_path(task_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _save_checkpoint(task_id: str, checkpoint: dict):
    """将 checkpoint 原子化写入磁盘。

    Checkpoint 存储在 state 同一目录下的 chain-checkpoint.json 文件中。
    使用临时文件 + os.replace 确保写入原子性。

    参数:
        task_id: 任务标识符
        checkpoint: 要持久化的 checkpoint 字典（含 step_idx, completed_outputs, timestamp）
    """
    ckpt_dir = os.path.join(STATE_DIR, task_id)
    ckpt_path = os.path.join(ckpt_dir, "chain-checkpoint.json")
    os.makedirs(ckpt_dir, exist_ok=True)
    tmp = ckpt_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, ckpt_path)


def _build_step_result(step: dict, chain_owner: str, step_idx: int,
                       chain_step_skills: dict, context: dict | None = None,
                       task_id: str = "", expansion: dict | None = None) -> dict:
    """为单个 step 构建响应。支持 serial / parallel / interactive / loop 四种类型。

    如果 step 有 type 字段且不为 serial，委托给对应的专用构建函数。
    如果 step 有 batch: true，返回 CONTINUE_BATCH 数组。
    如果 step 有 chain_ref 字段，委托给 _expand_sub_chain() 展开子链。
    """
    # ── chain_ref 子链展开分支 ──
    if step.get("chain_ref"):
        # 递归检测：从当前 expansion 或 context 中提取已展开的 refs
        current_expanded = []
        if expansion and expansion.get("expanded_refs"):
            current_expanded = expansion["expanded_refs"]
        elif context and context.get("expansion", {}).get("expanded_refs"):
            current_expanded = context["expansion"]["expanded_refs"]
        if step["chain_ref"] in current_expanded:
            return {
                "status": "ERROR",
                "diagnosis": f"递归检测：{step['chain_ref']} 已在展开链中 {current_expanded}",
            }
        return _expand_sub_chain(
            chain_ref=step["chain_ref"],
            parent_step=step,
            chain_owner=chain_owner,
            step_idx=step_idx,
            chain_step_skills=chain_step_skills,
            context=context or {},
            task_id=task_id,
        )

    step_type = _get_step_type(step)

    if step_type == STEP_TYPE_PARALLEL:
        return _build_parallel_result(step, step_idx, task_id)
    elif step_type == STEP_TYPE_INTERACTIVE:
        return _build_interactive_result(step, step_idx, task_id)
    elif step_type == STEP_TYPE_LOOP:
        return _build_loop_result(step, step_idx, context or {}, task_id)

    # ── serial 原有逻辑 ──
    if step.get("batch"):
        # batch 模式：根据 batch 配置展开为多个子任务
        batch_count = step.get("batch_count", 3)  # 默认拆成 3 个
        batch_goal_template = step.get("batch_goal_template", "")
        goals = []
        for i in range(batch_count):
            if batch_goal_template:
                goal = batch_goal_template.replace("{index}", str(i + 1)).replace("{batch_index}", str(i))
            else:
                goal = f"{step['goal']} (Batch {i + 1}/{batch_count})"
            goals.append(goal)

        next_items = []
        step_keywords = step.get("keywords", [])
        for i, goal in enumerate(goals):
            item = {
                "agent": step["agent"],
                "goal": goal,
                "batch_index": i,
            }
            if step_keywords:
                item["keywords"] = step_keywords
            next_items.append(item)

        return {
            "status": "CONTINUE_BATCH",
            "next": next_items,
            "batch_count": batch_count,
            "context": {
                "chain_step": step_idx,
                "step_goal": step["goal"],
                "batch_results": [],
            },
        }
    else:
        owner_key = f"{chain_owner}@{step_idx}"
        agent_key = f"{step['agent']}@{step_idx}"
        skills = chain_step_skills.get(owner_key) or chain_step_skills.get(agent_key, [])

        # ── 写 Step Brief 文件（通过 briefer） ──
        brief_path = write_chain_step_brief(task_id, step, step_idx, skills)

        next_item = {
            "agent": step["agent"],
            "goal": f"读取 Brief 文件 {brief_path} 并执行",
            "skills": skills,
            "brief_file": brief_path,
        }
        if step.get("keywords"):
            next_item["keywords"] = step["keywords"]
        return {
            "status": "CONTINUE",
            "next": next_item,
            "context": {"chain_step": step_idx, "step_goal": step.get("goal", "")},
        }


def start_chain(task_id: str, chain_def: list, chain_step_skills: dict, chain_owner: str,
                report_only: bool = False, dry_run: bool = False):
    """
    start action：封装首次 advance 调用，自动构造 last_result={"status":"init"}。
    等价于 advance(task_id, chain_def, chain_step_skills, {"status":"init"}, chain_owner, report_only, dry_run=dry_run)。

    当 dry_run=True 时：不创建状态文件，直接解析第一步的合法 status 列表并返回。
    """
    return advance(task_id, chain_def, chain_step_skills, {"status": "init"}, chain_owner, report_only=report_only, dry_run=dry_run)


def run_chain(task_id: str, chain_agent: str, last_result: dict):
    """
    run action：从 index.yaml 读取 chain_def + chain_step_skills，然后调用 advance。
    """
    index_data = load_index()
    if index_data is None:
        return {"status": "ERROR", "diagnosis": f"未找到 index.yaml: {INDEX_YAML_PATH}"}

    agents = index_data.get("agents", {})
    agent_config = agents.get(chain_agent)
    if not agent_config:
        return {"status": "ERROR", "diagnosis": f"index.yaml 中未找到 agent: {chain_agent}"}

    chain_def = agent_config.get("chain")

    chain_step_skills = agent_config.get("chain_step_skills", {})
    report_only = False

    # 如果内联 chain 不存在，尝试从 chain_ref 加载
    if not chain_def:
        chain_ref = agent_config.get("chain_ref")
        if chain_ref:
            chain_data = load_chain(chain_ref)
            if chain_data is None:
                chain_file = os.path.join(SCRIPT_DIR, "..", "route-map", "chains", f"{chain_ref}.yaml")
                return {"status": "ERROR", "diagnosis": f"chain_ref 文件不存在: {chain_file}"}
            chain_def = chain_data.get("steps", [])
            chain_step_skills = chain_data.get("chain_step_skills", {})
            report_only = chain_data.get("report_only", False)

    if not chain_def:
        return {"status": "ERROR", "diagnosis": f"agent '{chain_agent}' 未定义 chain 或 chain_ref"}

    chain_owner = chain_agent

    return advance(task_id, chain_def, chain_step_skills, last_result, chain_owner, report_only=report_only)


def run_verification(step: dict) -> dict:
    """执行 step 的 completion_contract 验证。

    支持新格式（check 字段 → run_check）和旧格式（verify_command → run_shell）。
    优先检查 check 字段，若无则降级到 verify_command。

    返回:
        {status: "VERIFIED"|"FAILED"|"NO_CONTRACT", results: [...]}
    """
    contract = step.get("completion_contract")
    if not contract:
        return {"status": STATUS_NO_CONTRACT, "results": []}

    results = []
    all_passed = True

    for item in contract:
        cmd_type = item.get("type", "assertion")
        description = item.get("description", "")
        check_name = item.get("check")

        # ── 新格式：check 字段 → run_check ──
        if check_name:
            params = item.get("params", {})
            try:
                result = run_check(check_name, **params)
                passed = result["passed"]
                results.append({
                    "type": cmd_type,
                    "description": description,
                    "check": check_name,
                    "params": params,
                    "passed": passed,
                    "details": result["details"],
                    "extra": result.get("extra", {}),
                })
            except KeyError as e:
                results.append({
                    "type": cmd_type,
                    "description": description,
                    "check": check_name,
                    "passed": False,
                    "error": str(e),
                })
                passed = False
            except Exception as e:
                results.append({
                    "type": cmd_type,
                    "description": description,
                    "check": check_name,
                    "passed": False,
                    "error": str(e),
                })
                passed = False
            if not passed:
                all_passed = False
            continue

        # ── 旧格式：verify_command → run_shell ──
        cmd = item.get("verify_command", "")
        if cmd:
            # Shell 命令白名单校验（仅限 pipe 模式）
            if "|" in cmd or ";" in cmd or "&&" in cmd:
                first_cmds = [part.strip().split()[0] for part in cmd.replace("&&", "|").replace(";", "|").split("|") if part.strip()]
                blocked = [c for c in first_cmds if c not in SHELL_WHITELIST]
                if blocked:
                    results.append({
                        "type": cmd_type,
                        "description": description,
                        "verify_command": cmd,
                        "passed": False,
                        "error": f"命令不在白名单: {', '.join(blocked)}",
                    })
                    all_passed = False
                    continue
            result = run_shell(cmd)
            res_item = {
                "type": cmd_type,
                "description": description,
                "verify_command": cmd,
                "passed": result["passed"],
                "details": result["details"],
                "exit_code": result.get("extra", {}).get("exit_code", -1),
            }
            if not result["passed"]:
                res_item["error"] = result["details"]
            results.append(res_item)
            if not result["passed"]:
                all_passed = False
            continue

        # ── 既无 check 也无 verify_command ──
        results.append({
            "type": cmd_type,
            "description": description,
            "passed": False,
            "error": "既无 check 字段也无 verify_command 字段",
        })
        all_passed = False

    status = STATUS_VERIFIED if all_passed else STATUS_VERIFICATION_FAILED
    return {"status": status, "results": results}


# ── advance() 辅助函数（S08 提取） ──────────────────


def _handle_blocked(step_idx: int, agent: str, step_goal: str,
                    last_result: dict) -> dict:
    """处理 BLOCKED 状态：挂起当前步骤并返回阻塞诊断。

    参数:
        step_idx: 当前步骤索引
        agent: 当前 agent 名称
        step_goal: 当前步骤目标
        last_result: 上一步返回的结果（含 message 诊断信息）

    返回:
        包含 BLOCKED 状态码的决策字典
    """
    return {
        "status": "BLOCKED",
        "step_idx": step_idx,
        "agent": agent,
        "goal": step_goal,
        "diagnosis": last_result.get("message", "阻塞，无诊断信息"),
    }


def _handle_needs_fix(task_id: str, state: dict, step_idx: int,
                      agent: str, step_goal: str, step_type: str,
                      last_result: dict,
                      advance_fn=None, fix_agent=None) -> dict:
    """处理 NEEDS_FIX 状态：根据 review 类型增加 retry 计数并返回 RETRY 指令。

    支持 spec-review 和 quality-review 两种 retry 类型。
    retry 次数达到 MAX_RETRY 后返回 BLOCKED 而非 RETRY。

    参数:
        task_id: 任务标识符
        state: 当前状态字典（会在函数内修改并持久化）
        step_idx: 当前步骤索引
        agent: 当前 agent 名称
        step_goal: 当前步骤目标
        step_type: _infer_step_type() 推断的步骤类型
        last_result: 上一步返回的结果

    返回:
        RETRY（重试修复）或 BLOCKED（达到上限挂起）的决策字典
    """
    if step_type == "spec-review":
        state["spec_retry"] += 1
        retry = state["spec_retry"]
        if retry >= MAX_RETRY:
            return {
                "status": "BLOCKED",
                "step_idx": step_idx,
                "agent": agent,
                "goal": step_goal,
                "diagnosis": f"spec 修复已达上限 {MAX_RETRY} 次，挂起",
                "spec_retry_count": retry,
            }
        _save_state(task_id, state)
        fix = fix_agent or agent
        return {
            "status": "RETRY",
            "next": {
                "agent": fix,
                "goal": f"fix: 根据 spec review 修复 ({retry}/{MAX_RETRY})",
                "skills": ["test-driven-development", "requesting-code-review"],
            },
            "context": {
                "review_findings": last_result.get("findings", ""),
                "original_diff_path": state["context"].get("diff_path", ""),
                "retry_type": "spec",
                "retry_count": retry,
                "target_step_idx": step_idx,
            },
        }
    elif step_type == "quality-review":
        state["quality_retry"] += 1
        retry = state["quality_retry"]
        if retry >= MAX_RETRY:
            return {
                "status": "BLOCKED",
                "step_idx": step_idx,
                "agent": agent,
                "goal": step_goal,
                "diagnosis": f"质量修复已达上限 {MAX_RETRY} 次，挂起",
                "quality_retry_count": retry,
            }
        _save_state(task_id, state)
        fix = fix_agent or agent
        return {
            "status": "RETRY",
            "next": {
                "agent": fix,
                "goal": f"fix: 根据 quality review 修复 ({retry}/{MAX_RETRY})",
                "skills": ["test-driven-development", "requesting-code-review"],
            },
            "context": {
                "review_findings": last_result.get("findings", ""),
                "original_diff_path": state["context"].get("diff_path", ""),
                "retry_type": "quality",
                "retry_count": retry,
                "target_step_idx": step_idx,
            },
        }
    else:
        return {"status": "ERROR", "diagnosis": f"step[{step_idx}] '{step_goal}' 无法判断 retry 类型"}


def _build_chain_done_result(state: dict, chain_def_length: int) -> dict:
    """构建链完成的返回结果。

    在各分支（batch_complete / branches_complete / loop_complete / DONE）中，
    当 current_step 超过 chain_def 长度时调用此函数。

    参数:
        state: 当前状态字典（含 report_only 标志、context、concerns 等）
        chain_def_length: chain_def 总步数

    返回:
        DONE 或 REPORT_ONLY 的决策字典
    """
    return {
        "status": "REPORT_ONLY" if state.get("report_only") else "DONE",
        "final_output_path": state["context"].get("last_output", ""),
        "concerns": state["concerns"],
        "summary": {
            "total_steps": chain_def_length,
            "spec_retry_count": state["spec_retry"],
            "quality_retry_count": state["quality_retry"],
            "concerns_count": len(state["concerns"]),
        },
    }


def _accumulate_partial_result(task_id: str, state: dict,
                               last_result: dict, agent: str,
                               status: str) -> dict:
    """累加并行分支或 batch 分片的中间结果。

    处理 branch_index 和 batch_index 两种 partial 回报。
    将结果存入 state.context.branch_results 或 state.context.batch_results 数组。
    返回 BRANCH_PROGRESS 或 BATCH_PROGRESS 以指示主 Agent 等待更多结果。

    参数:
        task_id: 任务标识符
        state: 当前状态字典（会在函数内修改并持久化）
        last_result: 上一步返回的结果（含 branch_index 或 batch_index）
        agent: 当前 agent 名称
        status: 当前状态

    返回:
        BRANCH_PROGRESS 或 BATCH_PROGRESS 的决策字典
    """
    if last_result.get("branch_index") is not None:
        branch_index = last_result["branch_index"]
        if "branch_results" not in state["context"]:
            state["context"]["branch_results"] = []
        while len(state["context"]["branch_results"]) <= branch_index:
            state["context"]["branch_results"].append(None)
        state["context"]["branch_results"][branch_index] = {
            "agent": agent,
            "status": status,
            "output_path": last_result.get("output_path", ""),
            "message": last_result.get("message", ""),
            "findings": last_result.get("findings", ""),
            "summary": last_result.get("summary", ""),
        }
        _save_state(task_id, state)
        return {
            "status": "BRANCH_PROGRESS",
            "branch_index": branch_index,
            "branch_count": len(state["context"]["branch_results"]),
            "context": state.get("context", {}),
            "message": f"Branch {branch_index + 1} completed. "
                       f"Awaiting remaining or branches_complete.",
        }

    if last_result.get("batch_index") is not None:
        batch_index = last_result["batch_index"]
        if "batch_results" not in state["context"]:
            state["context"]["batch_results"] = []
        while len(state["context"]["batch_results"]) <= batch_index:
            state["context"]["batch_results"].append(None)
        state["context"]["batch_results"][batch_index] = {
            "agent": agent,
            "status": status,
            "output_path": last_result.get("output_path", ""),
            "message": last_result.get("message", ""),
            "findings": last_result.get("findings", ""),
            "summary": last_result.get("summary", ""),
        }
        _save_state(task_id, state)
        return {
            "status": "BATCH_PROGRESS",
            "batch_index": batch_index,
            "batch_count": len(state["context"]["batch_results"]),
            "context": state.get("context", {}),
            "message": f"Batch item {batch_index + 1} completed. "
                       f"Awaiting remaining or batch_complete.",
        }

    return {"status": "ERROR", "diagnosis": "partial result 缺少 branch_index 或 batch_index"}


def _handle_batch_complete(task_id: str, state: dict, chain_def: list,
                           chain_owner: str, chain_step_skills: dict,
                           last_result: dict, step_idx: int) -> dict:
    """处理 batch_complete：保存 batch 结果，执行 verification，
    推进到下一步或结束链。

    参数:
        task_id: 任务标识符
        state: 当前状态字典
        chain_def: 链定义列表
        chain_owner: 链所属 Agent
        chain_step_skills: step skills 字典
        last_result: 上一步返回的结果（含 batch_results）
        step_idx: 当前步骤索引

    返回:
        下一步决策字典（CONTINUE / DONE / VERIFICATION_FAILED 等）
    """
    batch_results = last_result.get("batch_results", [])
    if batch_results:
        state["context"]["batch_results"] = batch_results
    current_step = chain_def[step_idx]
    verification_result = run_verification(current_step)
    if verification_result["status"] == STATUS_VERIFICATION_FAILED:
        _save_state(task_id, state)
        return {
            "status": "BLOCKED",
            "step_idx": step_idx,
            "agent": chain_def[step_idx].get("agent", ""),
            "goal": chain_def[step_idx].get("goal", ""),
            "blocked_reason": "completion_contract_verification_failed",
            "verification_results": verification_result["results"],
            "diagnosis": f"Batch step {step_idx} verification failed",
            "ask_user": True,
            "options": ["skip", "retry", "abort"],
        }
    _save_state(task_id, state)
    state["current_step"] += 1
    if state["current_step"] >= len(chain_def):
        _save_state(task_id, state)
        return _build_chain_done_result(state, chain_def_length=len(chain_def))
    _save_state(task_id, state)
    step = chain_def[state["current_step"]]
    return _build_step_result(step, chain_owner, state["current_step"],
                               chain_step_skills, state.get("context", {}),
                               task_id=task_id)


def _handle_branch_complete(task_id: str, state: dict, chain_def: list,
                            chain_owner: str, chain_step_skills: dict,
                            last_result: dict, step_idx: int) -> dict:
    """处理 branches_complete：保存并行分支结果，执行 verification，
    推进到下一步或结束链。

    参数:
        task_id: 任务标识符
        state: 当前状态字典
        chain_def: 链定义列表
        chain_owner: 链所属 Agent
        chain_step_skills: step skills 字典
        last_result: 上一步返回的结果（含 branch_results）
        step_idx: 当前步骤索引

    返回:
        下一步决策字典
    """
    branch_results = last_result.get("branch_results", [])
    if branch_results:
        state["context"]["branch_results"] = branch_results
    current_step = chain_def[step_idx]
    verification_result = run_verification(current_step)
    if verification_result["status"] == STATUS_VERIFICATION_FAILED:
        _save_state(task_id, state)
        return {
            "status": "BLOCKED",
            "step_idx": step_idx,
            "agent": chain_def[step_idx].get("agent", ""),
            "goal": chain_def[step_idx].get("goal", ""),
            "blocked_reason": "completion_contract_verification_failed",
            "verification_results": verification_result["results"],
            "diagnosis": f"Branches step {step_idx} verification failed",
            "ask_user": True,
            "options": ["skip", "retry", "abort"],
        }
    _save_state(task_id, state)
    state["current_step"] += 1
    if state["current_step"] >= len(chain_def):
        _save_state(task_id, state)
        return _build_chain_done_result(state, chain_def_length=len(chain_def))
    _save_state(task_id, state)
    step = chain_def[state["current_step"]]
    return _build_step_result(step, chain_owner, state["current_step"],
                               chain_step_skills, state.get("context", {}),
                               task_id=task_id)


def _handle_loop_complete(task_id: str, state: dict, chain_def: list,
                          chain_owner: str, chain_step_skills: dict,
                          last_result: dict, step_idx: int) -> dict:
    """处理 loop_complete：保存循环结果，推进到下一步或结束链。

    参数:
        task_id: 任务标识符
        state: 当前状态字典
        chain_def: 链定义列表
        chain_owner: 链所属 Agent
        chain_step_skills: step skills 字典
        last_result: 上一步返回的结果（含 loop_results）
        step_idx: 当前步骤索引

    返回:
        下一步决策字典
    """
    loop_results = last_result.get("loop_results", [])
    if loop_results:
        state["context"]["loop_results"] = loop_results
    _save_state(task_id, state)
    state["current_step"] += 1
    if state["current_step"] >= len(chain_def):
        _save_state(task_id, state)
        return _build_chain_done_result(state, chain_def_length=len(chain_def))
    _save_state(task_id, state)
    step = chain_def[state["current_step"]]
    return _build_step_result(step, chain_owner, state["current_step"],
                               chain_step_skills, state.get("context", {}),
                               task_id=task_id)


def _handle_serial_step(step: dict, chain_owner: str, step_idx: int,
                        chain_step_skills: dict,
                        context: dict | None = None,
                        task_id: str = "") -> dict:
    """处理 serial 类型的步骤构建（委托给 _build_step_result）。

    参数:
        step: 步骤定义字典
        chain_owner: 链所属 Agent
        step_idx: 步骤索引
        chain_step_skills: step skills 字典
        context: 当前上下文

    返回:
        _build_step_result 的返回结果（CONTINUE 等）
    """
    return _build_step_result(step, chain_owner, step_idx,
                              chain_step_skills, context,
                              task_id=task_id)


def _handle_parallel_step(step: dict, chain_owner: str, step_idx: int,
                          chain_step_skills: dict,
                          context: dict | None = None,
                          task_id: str = "") -> dict:
    """处理 parallel 类型的步骤构建（委托给 _build_step_result）。

    参数:
        step: 步骤定义字典
        chain_owner: 链所属 Agent
        step_idx: 步骤索引
        chain_step_skills: step skills 字典
        context: 当前上下文

    返回:
        _build_step_result 的返回结果（CONTINUE_PARALLEL 等）
    """
    return _build_step_result(step, chain_owner, step_idx,
                              chain_step_skills, context,
                              task_id=task_id)


def _expand_sub_chain(
    chain_ref: str,
    parent_step: dict,
    chain_owner: str,
    step_idx: int,
    chain_step_skills: dict,
    context: dict,
    task_id: str,
) -> dict:
    """展开子链并返回第一个子步骤的结果。

    入参：
        chain_ref: 子链名称（如 "implement-review-subchain"）
        parent_step: 触发展开的父步骤
        chain_owner: 父链所属 Agent
        step_idx: 父链中的锚定步骤索引
        chain_step_skills: 父链 skills
        context: 当前上下文
        task_id: 父链任务 ID

    返回：
        dict — 与 _build_step_result() 返回格式一致
    """
    # 1. 加载子链 YAML（使用模块级 load_chain，可被 mock）
    sub_chain = load_chain(chain_ref)
    if sub_chain is None:
        return {
            "status": "ERROR",
            "diagnosis": f"子链 {chain_ref} 不存在（load_chain 返回 None）",
        }

    # 2. 验证子链 steps 非空
    sub_steps = sub_chain.get("steps", [])
    if not sub_steps:
        return {
            "status": "ERROR",
            "diagnosis": f"子链 {chain_ref} steps 为空",
        }

    # 3. 获取子链 owner 和 skills
    sub_owner = sub_chain.get("owner", chain_owner)
    sub_skills_raw = sub_chain.get("chain_step_skills", {})
    sub_skills = copy.deepcopy(sub_skills_raw) if sub_skills_raw else {}

    # 4. 递归检测：记录已展开的 chain_ref
    current_expanded = list(context.get("expansion", {}).get("expanded_refs", []))
    expanded_refs = current_expanded + [chain_ref]

    # 5. 创建 expansion 结构体
    expansion = {
        "parent_task_id": task_id,
        "sub_task_id": f"{task_id}-sub",
        "anchor_step_idx": step_idx,
        "sub_steps": copy.deepcopy(sub_steps),
        "sub_skills": sub_skills,
        "sub_owner": sub_owner,
        "sub_current": 0,
        "expanded_refs": expanded_refs,
    }

    # 6. 取 sub_steps[0]，调 _build_step_result()
    sub_step = sub_steps[0]
    result = _build_step_result(
        sub_step,
        sub_owner,
        0,
        sub_skills,
        context,
        task_id=expansion["sub_task_id"],
        expansion=expansion,
    )
    # 将 expansion 附加到返回结果，由 advance() 统一持久化
    result["expansion"] = expansion
    # 子链 context key 加 "sub_" 前缀隔离，避免污染父链上下文
    if "context" in result and isinstance(result["context"], dict):
        result["context"] = {f"sub_{k}": v for k, v in result["context"].items()}
    return result


def advance(task_id: str, chain_def: list, chain_step_skills: dict,
            last_result: dict, chain_owner: str = "", report_only: bool = False,
            dry_run: bool = False):
    """
    last_result: 从上一步委托返回的结果 dict
      必有: agent, status
      可选: output_path, findings, message
    1) 首个调用: last_result={"status":"init"}
    2) batch 场景: last_result 可含 batch_index 或 batch_complete
    chain_owner: 链所属的 Agent（用于构建 skills key: {owner}@{idx}）
    report_only: 链完成后返回 REPORT_ONLY 状态码而非 DONE
    dry_run: 为 True 时不加载状态/不修改状态，直接根据 chain_def
             解析当前 step 的合法 status 列表并返回
    """

    # ── dry-run 模式：不加载/不修改状态，直接返回合法 status 列表 ──
    if dry_run:
        dr_step_idx = 0  # 默认 step 0
        if last_result.get("status") == "init":
            dr_step_idx = 0
            if not chain_def:
                return {"status": "ERROR", "diagnosis": "chain_def 为空数组，无法启动链"}
        else:
            # 非 init 调用：尝试从 last_result 推断 step_idx
            dr_step_idx = last_result.get("step_idx", 0)
            # 如果 last_result 有 target_step_idx（fix 场景），用那个
            dr_step_idx = last_result.get("target_step_idx", dr_step_idx)

        if dr_step_idx >= len(chain_def):
            return {"status": "ERROR", "diagnosis": f"step_idx {dr_step_idx} 超出 chain_def 范围"}
        dr_step = chain_def[dr_step_idx]
        dr_goal = dr_step.get("goal", "")
        dr_type = _infer_step_type(dr_goal) if dr_goal else "tdd"
        dr_valid = STEP_VALID_STATUSES.get(dr_type, ["DONE", "BLOCKED", "NEEDS_FIX", "NEEDS_CONTEXT"])
        return {
            "agent": dr_step.get("agent", ""),
            "valid_statuses": dr_valid,
            "step_idx": dr_step_idx,
        }

    # ── 首次调用 ──
    if last_result.get("status") == "init":
        if not chain_owner:
            return {"status": "ERROR", "diagnosis": "首次调用必须指定 --chain_owner"}
        if not chain_def:
            return {"status": "ERROR", "diagnosis": "chain_def 为空数组，无法启动链"}
        skill_errors = _validate_skills(chain_def, chain_step_skills, chain_owner)
        if skill_errors:
            return {
                "status": "ERROR",
                "diagnosis": "; ".join(skill_errors),
                "defined_keys": list(chain_step_skills.keys()),
            }
        try:
            state = _load_state(task_id)
        except RuntimeError as e:
            return {"status": "ERROR", "diagnosis": str(e)}
        if state is None:
            return {"status": "ERROR", "diagnosis": f"state 文件完全损坏且无法从 checkpoint 恢复 (task_id={task_id})"}
        # 重置状态（避免跨 session 污染）
        state.pop("expansion", None)  # 清除残留的 expansion（上一轮崩溃遗留）
        state.update({
            "current_step": 0, "spec_retry": 0, "quality_retry": 0,
            "concerns": [], "context": {}, "chain_owner": chain_owner,
            "report_only": report_only,
            "total_iterations": 0, "chain_started_at": None,
            "last_checkpoint": None,
        })
        import time as _time
        state["total_iterations"] = state.get("total_iterations", 0) + 1
        if state.get("chain_started_at") is None:
            state["chain_started_at"] = _time.time()
        _save_state(task_id, state)

        step = chain_def[0]
        result = _build_step_result(step, chain_owner, 0, chain_step_skills, state.get("context", {}), task_id=task_id)
        if "expansion" in result:
            state["expansion"] = result["expansion"]
            _save_state(task_id, state)
        return result

    try:
        state = _load_state(task_id)
    except RuntimeError as e:
        return {"status": "ERROR", "diagnosis": str(e)}
    if state is None:
        return {"status": "ERROR", "diagnosis": f"state 文件完全损坏且无法从 checkpoint 恢复 (task_id={task_id})"}

    # ── PAUSED 状态检查：如果链被暂停，立即返回 PAUSED ──
    if state.get("status") == "PAUSED":
        return {
            "status": "PAUSED",
            "step_idx": state.get("current_step", 0),
            "agent": last_result.get("agent", ""),
            "goal": "",
            "diagnosis": f"chain is paused — use rescue to continue (task_id={task_id})",
        }

    # ── 全局安全网：总迭代次数检查 ──
    state["total_iterations"] = state.get("total_iterations", 0) + 1
    if state["total_iterations"] > MAX_TOTAL_ITERATIONS:
        _save_state(task_id, state)
        return {
            "status": "BLOCKED",
            "step_idx": state.get("current_step", 0),
            "agent": last_result.get("agent", ""),
            "goal": "",
            "diagnosis": f"total_iterations exceeded MAX_TOTAL_ITERATIONS ({MAX_TOTAL_ITERATIONS})",
        }

    # ── 全局安全网：Wall-clock 超时检查 ──
    import time as _time
    if state.get("chain_started_at") is None:
        state["chain_started_at"] = _time.time()
    elif _time.time() - state["chain_started_at"] > CHAIN_TIMEOUT:
        _save_state(task_id, state)
        return {
            "status": "BLOCKED",
            "step_idx": state.get("current_step", 0),
            "agent": last_result.get("agent", ""),
            "goal": "",
            "diagnosis": f"chain wall-clock timeout exceeded CHAIN_TIMEOUT ({CHAIN_TIMEOUT}s)",
        }
    _save_state(task_id, state)
    # 使用 state 中存储的 chain_owner（首次调用时已保存）
    chain_owner = state.get("chain_owner", chain_owner)
    agent = last_result.get("agent", "")
    status = last_result.get("status", "")
    if "current_step" not in state:
        return {"status": "ERROR", "diagnosis": f"state 文件缺少 current_step，可能已损坏（task_id={task_id}）"}
    step_idx = state["current_step"]
    if step_idx >= len(chain_def):
        return {"status": "ERROR", "diagnosis": f"state.current_step ({step_idx}) >= chain_def 长度 ({len(chain_def)})，状态与链定义不匹配"}

    # ── jump_map 跳步（来自 interactive 步骤的用户选择）──
    if last_result.get('from_interactive'):
        jump_map = chain_def[0].get('jump_map', {}) if chain_def else {}
        if jump_map:
            user_choice = last_result.get('user_choice', '')
            if user_choice:
                chosen_key = None
                for key in jump_map:
                    if key in user_choice:
                        chosen_key = key
                        break
                if chosen_key:
                    jump = jump_map[chosen_key]
                    if jump['action'] == 'goto':
                        target = jump['step']
                        step = chain_def[target]
                        result = _build_step_result(step, chain_owner, target,
                                                   chain_step_skills, state.get("context", {}),
                                                   task_id=task_id)
                        if "expansion" in result:
                            state["expansion"] = result["expansion"]
                            _save_state(task_id, state)
                        result['jumped_from_step_0'] = True
                        result['skipped_steps'] = list(range(1, target))
                        return result
                    elif jump['action'] == 'chain':
                        return {
                            'status': 'SWITCH_CHAIN',
                            'target_chain': jump['target'],
                            'task_id': task_id,
                            'step_idx': 0,
                        }

    # ── batch_complete ──
    if last_result.get("batch_complete"):
        return _handle_batch_complete(task_id, state, chain_def, chain_owner,
                                      chain_step_skills, last_result, step_idx)

    # ── branches_complete ──
    if last_result.get("branches_complete"):
        return _handle_branch_complete(task_id, state, chain_def, chain_owner,
                                       chain_step_skills, last_result, step_idx)

    # ── loop_complete ──
    if last_result.get("loop_complete"):
        return _handle_loop_complete(task_id, state, chain_def, chain_owner,
                                     chain_step_skills, last_result, step_idx)

    # ── branch_index / batch_index — 累加 partial 结果 ──
    if last_result.get("branch_index") is not None or last_result.get("batch_index") is not None:
        return _accumulate_partial_result(task_id, state, last_result, agent, status)

    # ── SWITCH_CHAIN — 切换到其他链（在状态校验前处理，SWITCH_CHAIN 不是步骤合法状态）──
    if status == "SWITCH_CHAIN":
        return {
            "status": "SWITCH_CHAIN",
            "target_chain": last_result.get("target_chain", ""),
            "task_id": task_id,
            "step_idx": step_idx,
        }

    # ── 校验状态合法性 ──
    step_goal = chain_def[step_idx].get("goal", "")
    if not step_goal:
        return {"status": "ERROR", "diagnosis": f"step[{step_idx}] 缺少 goal 字段（可能 parallel/interactive/loop 步骤未经过 completion handler）"}
    step_type = _infer_step_type(step_goal)
    # 空 status → 首次调用，返回当前步骤
    if not status:
        step = chain_def[step_idx]
        result = _build_step_result(step, chain_owner, step_idx, chain_step_skills, state.get("context", {}), task_id=task_id)
        if "expansion" in result:
            state["expansion"] = result["expansion"]
            _save_state(task_id, state)
        return result
    valid = STEP_VALID_STATUSES.get(step_type, ["DONE", "BLOCKED", "NEEDS_FIX", "NEEDS_CONTEXT"])
    if status not in valid:
        return {
            "status": "ERROR",
            "diagnosis": f"step[{step_idx}] '{step_goal}' (agent={agent}) 返回非法状态 '{status}'。合法状态: {valid}",
        }

    # ── BLOCKED — 挂起 ──
    if status == "BLOCKED":
        return _handle_blocked(step_idx, agent, step_goal, last_result)

    # ── NEEDS_CONTEXT — 等待用户 ──
    if status == "NEEDS_CONTEXT":
        # ── 子链 loop + interactive 用户响应 ──
        if last_result.get("expansion"):
            expansion = last_result["expansion"]
            user_msg = (last_result.get("message") or "").strip().lower()
            # 判断用户是否确认继续
            user_says_yes = any(
                w in user_msg for w in ["y", "yes", "继续", "是", "有", "还有"]
            )
            if user_says_yes:
                # 重置子链，重新执行
                expansion["sub_current"] = 0
                state["expansion"] = expansion
                _save_state(task_id, state)
                sub_step = expansion["sub_steps"][0]
                sub_owner = expansion.get("sub_owner", chain_owner)
                return _build_step_result(
                    sub_step,
                    sub_owner,
                    expansion["anchor_step_idx"],
                    expansion["sub_skills"],
                    state.get("context", {}),
                    task_id=expansion["sub_task_id"],
                    expansion=expansion,
                )
            else:
                # 用户确认结束 — 清除 expansion，父链推进
                if "expansion" in state:
                    del state["expansion"]
                _save_state(task_id, state)
                # 继续父链：推进到下一步
                state["current_step"] = expansion["anchor_step_idx"] + 1
                _save_state(task_id, state)
                if state["current_step"] >= len(chain_def):
                    return _build_chain_done_result(state, chain_def_length=len(chain_def))
                step = chain_def[state["current_step"]]
                result = _build_step_result(
                    step, chain_owner, state["current_step"],
                    chain_step_skills, state.get("context", {}),
                    task_id=task_id,
                )
                if "expansion" in result:
                    state["expansion"] = result["expansion"]
                    _save_state(task_id, state)
                return result

        return {
            "status": "NEEDS_CONTEXT",
            "step_idx": step_idx,
            "agent": agent,
            "goal": step_goal,
            "question": last_result.get("message", "缺少上下文，请补充"),
        }

    # ── DONE_WITH_CONCERNS — 标记，继续 ──
    if status == "DONE_WITH_CONCERNS":
        concern = last_result.get("message", f"step[{step_idx}] 有未解决的担忧")
        state["concerns"].append(concern)
        _save_state(task_id, state)
        status = "DONE"  # 降级为 DONE

    # ── NEEDS_FIX — review 不通过 ──
    if status == "NEEDS_FIX":
        step_type = _infer_step_type(step_goal)
        # Determine the fix agent dynamically from chain_def
        fix_agent = chain_def[0].get("agent", agent) if chain_def and len(chain_def) > 0 else agent
        return _handle_needs_fix(task_id, state, step_idx, agent,
                                 step_goal, step_type, last_result,
                                 advance_fn=advance, fix_agent=fix_agent)

    # ── DONE / APPROVE — 推进或回归 ──
    if status in ("DONE", "APPROVE"):
        # 保存产出路径到上下文
        if last_result.get("output_path"):
            state["context"]["diff_path"] = last_result["output_path"]
        state["context"]["last_output"] = last_result.get("output_path", "")

        # ── Expansion 状态检查：子链正在执行中 ──
        expansion = state.get("expansion")
        if expansion:
            expansion["sub_current"] += 1
            if expansion["sub_current"] < len(expansion["sub_steps"]):
                # 子链还有后续步骤 → 继续子链
                sub_step = expansion["sub_steps"][expansion["sub_current"]]
                sub_owner = expansion.get("sub_owner", chain_owner)
                state["expansion"] = expansion
                _save_state(task_id, state)
                return _build_step_result(
                    sub_step,
                    sub_owner,
                    expansion["anchor_step_idx"],
                    expansion["sub_skills"],
                    state.get("context", {}),
                    task_id=expansion["sub_task_id"],
                    expansion=expansion,
                )
            else:
                # 子链执行完毕
                parent_step = chain_def[expansion["anchor_step_idx"]]
                if parent_step.get("loop") and parent_step.get("interactive"):
                    # loop + interactive：保持 expansion 并询问用户
                    state["expansion"] = expansion
                    _save_state(task_id, state)
                    return {
                        "status": "NEEDS_CONTEXT",
                        "step_idx": expansion["anchor_step_idx"],
                        "agent": parent_step.get("agent", chain_owner),
                        "goal": parent_step.get("goal", ""),
                        "need": "用户确认",
                        "question": (
                            f"子链 {expansion.get('sub_task_id')} 已完成。"
                            "还有任务吗？(y/n)"
                        ),
                        "expansion": expansion,
                    }
                else:
                    # 清除 expansion，继续父链下一步
                    del state["expansion"]
                    _save_state(task_id, state)
                    # 不提前 return — 自然 fall through 到父链推进逻辑

        # ── Checkpoint：记录当前已完成步骤及关键状态 ──
        checkpoint = {
            "step_idx": step_idx,
            "completed_outputs": state.get("completed_outputs", ""),
            "spec_retry": state.get("spec_retry", 0),
            "quality_retry": state.get("quality_retry", 0),
            "concerns": state.get("concerns", []),
            "total_iterations": state.get("total_iterations", 0),
            "context_diff_path": state.get("context", {}).get("diff_path"),
            "context_last_output": state.get("context", {}).get("last_output"),
        }
        state["last_checkpoint"] = checkpoint
        _save_checkpoint(task_id, checkpoint)

        # 防御检查：RETRY 上下文中缺少 target_step_idx
        if last_result.get("target_step_idx") is None and state["context"].get("retry_type"):
            return {
                "status": "ERROR",
                "diagnosis": f"fix 步骤 DONE 但缺少 target_step_idx（retry_type={state['context'].get('retry_type')}）。主 Agent 应在 fix 完成后回传 target_step_idx 以回到评审步骤。",
            }

        # ── Verification Gate：检查当前 step 的 completion_contract ──
        current_step = chain_def[step_idx]
        verification_result = run_verification(current_step)
        if verification_result["status"] == STATUS_VERIFICATION_FAILED:
            _save_state(task_id, state)
            return {
                "status": STATUS_VERIFICATION_FAILED,
                "step_idx": step_idx,
                "agent": agent,
                "goal": step_goal,
                "verification_results": verification_result["results"],
                "diagnosis": f"Step {step_idx} ('{step_goal}') verification failed",
            }

        # fix 循环后回到 review step
        if last_result.get("target_step_idx") is not None:
            state["current_step"] = last_result["target_step_idx"]
            _save_state(task_id, state)
            step = chain_def[state["current_step"]]
            result = _build_step_result(step, chain_owner, state["current_step"], chain_step_skills, state.get("context", {}), task_id=task_id)
            if "expansion" in result:
                state["expansion"] = result["expansion"]
                _save_state(task_id, state)
            return result

        # ── Skip Threshold 检查：下一步是否应跳过 ──
        next_step_idx = step_idx + 1
        if next_step_idx < len(chain_def):
            next_step = chain_def[next_step_idx]
            skip_result = _should_skip_step(next_step, state, next_step_idx)
            if skip_result is not None:
                # 跳过下一步：将 state 的 current_step 推进到跳过步骤之后，
                # 主 Agent 收到 SKIPPED 后再次调用 advance 会从下一步继续。
                state["current_step"] = next_step_idx + 1
                _save_state(task_id, state)
                if state["current_step"] >= len(chain_def):
                    return _build_chain_done_result(state, chain_def_length=len(chain_def))
                return skip_result

        # 正常推进到下一步
        state["current_step"] += 1
        if state["current_step"] >= len(chain_def):
            _save_state(task_id, state)
            return _build_chain_done_result(state, chain_def_length=len(chain_def))

        _save_state(task_id, state)
        step = chain_def[state["current_step"]]
        result = _build_step_result(step, chain_owner, state["current_step"], chain_step_skills, state.get("context", {}), task_id=task_id)
        if "expansion" in result:
            state["expansion"] = result["expansion"]
            _save_state(task_id, state)
        return result

    return {"status": "ERROR", "diagnosis": f"未处理的状态: {status}"}


def _rescue(task_id: str, step_idx: int | None = None):
    """跳过当前阻塞的 step，直接进入下一步或指定 step。

    参数:
        task_id: 任务标识符
        step_idx: 可选，指定跳转到哪个 step（0-based）。默认跳到下一步。

    返回:
        新的 state 字典，current_step 指向跳转后的 step。
    """
    try:
        _sanitize_task_id(task_id)
    except ValueError as e:
        return {"status": "ERROR", "diagnosis": str(e)}

    state = _load_state(task_id)
    if state is None:
        return {"status": "ERROR", "diagnosis": f"state 不存在或已损坏 (task_id={task_id})"}

    current_step = state.get("current_step", 0)
    target_step = (current_step + 1) if step_idx is None else step_idx

    # 记录救援信息
    rescue_record = {
        "rescue_skip": True,
        "rescued_at": __import__("time").time(),
        "from_step": current_step,
        "to_step": target_step,
        "message": f"人工介入: rescue from step {current_step} to step {target_step}",
    }
    state.setdefault("rescue_log", []).append(rescue_record)
    state["current_step"] = target_step
    # 清除 PAUSED 状态（rescue 隐含恢复执行）
    if state.get("status") == "PAUSED":
        state.pop("status", None)

    _save_state(task_id, state)
    state["_rescue_action"] = rescue_record
    return state


def _kill(task_id: str):
    """立即终止整个链。

    设置 state 状态为 KILLED，返回所有已完成步骤的 result 和产出物。
    不保存 checkpoint（手动终止不需要恢复）。

    参数:
        task_id: 任务标识符

    返回:
        dict: 包含 status=KILLED, completed_steps, completed_outputs
    """
    try:
        _sanitize_task_id(task_id)
    except ValueError as e:
        return {"status": "ERROR", "diagnosis": str(e)}

    state = _load_state(task_id)
    if state is None:
        return {"status": "ERROR", "diagnosis": f"state 不存在或已损坏 (task_id={task_id})"}

    # 收集已完成步骤的结果
    completed_steps = state.get("completed_steps", [])
    completed_outputs = state.get("completed_outputs", [])

    # 设置 KILLED 状态
    state["status"] = "KILLED"
    state["killed_at"] = __import__("time").time()
    state.setdefault("rescue_log", []).append({
        "kill": True,
        "killed_at": __import__("time").time(),
        "message": "人工介入: chain killed",
    })

    _save_state(task_id, state)

    return {
        "status": "KILLED",
        "task_id": task_id,
        "completed_steps": completed_steps,
        "completed_outputs": completed_outputs,
        "current_step": state.get("current_step", 0),
        "diagnosis": "Chain manually terminated via kill action",
    }


def _pause(task_id: str):
    """暂停链执行。

    设置 state 状态为 PAUSED，后续 advance() 调用检测到 PAUSED 状态直接返回 Blocked。

    参数:
        task_id: 任务标识符

    返回:
        dict: 包含 status=PAUSED, current_step
    """
    try:
        _sanitize_task_id(task_id)
    except ValueError as e:
        return {"status": "ERROR", "diagnosis": str(e)}

    state = _load_state(task_id)
    if state is None:
        return {"status": "ERROR", "diagnosis": f"state 不存在或已损坏 (task_id={task_id})"}

    state["status"] = "PAUSED"
    state["paused_at"] = __import__("time").time()
    state.setdefault("rescue_log", []).append({
        "pause": True,
        "paused_at": __import__("time").time(),
        "message": "人工介入: chain paused",
    })

    _save_state(task_id, state)

    return {
        "status": "PAUSED",
        "task_id": task_id,
        "current_step": state.get("current_step", 0),
        "diagnosis": "Chain manually paused — advance() will return Blocked until rescue or kill",
    }


def main():
    """CLI 入口函数。

    支持 action 参数: advance, start, run, verify。
    所有结果以 JSON 格式输出到 stdout（exit code 0）或 stderr（exit code 1）。

    advance: 推进链状态机一步。需要 --chain_def, --chain_step_skills, --last_result。
    start:   启动新链。需要 --chain_def, --chain_step_skills, --chain_owner。
    run:     从 index.yaml 加载 chain 并推进。需要 --chain_agent, 可选 --last_result。
    verify:  执行指定 step 的 verification contract。需要 --chain_def, --step_idx。

    异常:
        SystemExit(1): 参数缺失、JSON 解析失败、task_id 非法或 step_idx 越界时退出
    """
    parser = argparse.ArgumentParser(description="Chain 编排引擎")
    parser.add_argument("action",
                        help="可用命令: advance, start, run, verify, rescue/恢复/跳过/继续/skip, "
                             "kill/终止/结束/停止/cancel, pause/暂停/停")
    parser.add_argument("--task_id", required=True)
    parser.add_argument("--step_idx", default=None, type=int,
                        help="step 索引（verify action 必填）")
    parser.add_argument("--chain_def", default=None,
                        help="JSON: [{agent, goal}, ...] (advance/start 必填)")
    parser.add_argument("--chain_step_skills", default=None,
                        help="JSON: {owner@idx: [skill, ...]} (advance/start 必填)")
    parser.add_argument("--last_result", default=None,
                        help="JSON: {agent, status, ...} (advance/run 必填, start 自动设为 init)")
    parser.add_argument("--chain_owner", default="",
                        help="链所属 Agent（首次调用必填）")
    parser.add_argument("--chain_agent", default="",
                        help="从 index.yaml 读取 chain 的 Agent 名 (run action 必填)")
    parser.add_argument("--report_only", action="store_true", default=False,
                        help="链完成后返回 REPORT_ONLY 状态码而非 DONE")
    parser.add_argument("--dry-run", action="store_true", default=False, dest="dry_run",
                        help="dry-run 模式：不加载/不修改状态，直接返回当前 step 的合法 status 列表")
    args = parser.parse_args()

    # 中文别名映射 -> 标准 action 名
    ACTION_ALIASES = {
        "恢复": "rescue", "跳过": "rescue", "继续": "rescue",
        "skip": "rescue",
        "终止": "kill", "结束": "kill", "停止": "kill",
        "cancel": "kill",
        "暂停": "pause", "停": "pause",
    }
    STANDARD_ACTIONS = {"advance", "start", "run", "verify", "rescue", "kill", "pause"}

    if args.action in ACTION_ALIASES:
        args.action = ACTION_ALIASES[args.action]
    elif args.action not in STANDARD_ACTIONS:
        aliases_help = ", ".join(f"{k}(={v})" for k, v in ACTION_ALIASES.items())
        print(json.dumps({
            "status": "ERROR",
            "diagnosis": f"未知 action '{args.action}'。可用命令: advance, start, run, verify, "
                         f"rescue(恢复/跳过/继续/skip), kill(终止/结束/停止/cancel), pause(暂停/停)",
        }, ensure_ascii=False))
        sys.exit(1)

    # 在 main 入口净化 task_id
    try:
        _sanitize_task_id(args.task_id)
    except ValueError as e:
        print(json.dumps({"status": "ERROR", "diagnosis": str(e)}, ensure_ascii=False))
        sys.exit(1)

    if args.action == "start":
        # start: --chain_def, --chain_step_skills, --chain_owner 必填；不填 --last_result
        if not args.chain_def:
            print(json.dumps({"status": "ERROR", "diagnosis": "start action 需要 --chain_def"}, ensure_ascii=False))
            sys.exit(1)
        if not args.chain_step_skills:
            print(json.dumps({"status": "ERROR", "diagnosis": "start action 需要 --chain_step_skills"}, ensure_ascii=False))
            sys.exit(1)
        if not args.chain_owner:
            print(json.dumps({"status": "ERROR", "diagnosis": "start action 需要 --chain_owner"}, ensure_ascii=False))
            sys.exit(1)

        try:
            chain_def = json.loads(args.chain_def)
            chain_step_skills = json.loads(args.chain_step_skills)
        except json.JSONDecodeError as e:
            print(json.dumps({"status": "ERROR", "diagnosis": f"JSON 解析失败: {e}"}, ensure_ascii=False))
            sys.exit(1)
        result = start_chain(args.task_id, chain_def, chain_step_skills, args.chain_owner,
                             report_only=args.report_only, dry_run=args.dry_run)

    elif args.action == "run":
        # run: --chain_agent 必填；可选 --last_result（默认 init）
        if not args.chain_agent:
            print(json.dumps({"status": "ERROR", "diagnosis": "run action 需要 --chain_agent"}, ensure_ascii=False))
            sys.exit(1)

        try:
            last_result = json.loads(args.last_result) if args.last_result else {"status": "init"}
        except json.JSONDecodeError as e:
            print(json.dumps({"status": "ERROR", "diagnosis": f"last_result JSON 解析失败: {e}"}, ensure_ascii=False))
            sys.exit(1)
        result = run_chain(args.task_id, args.chain_agent, last_result)

    elif args.action == "verify":
        # verify: --chain_def, --step_idx 必填
        if not args.chain_def:
            print(json.dumps({"status": "ERROR", "diagnosis": "verify action 需要 --chain_def"}, ensure_ascii=False))
            sys.exit(1)
        if args.step_idx is None:
            print(json.dumps({"status": "ERROR", "diagnosis": "verify action 需要 --step_idx"}, ensure_ascii=False))
            sys.exit(1)

        try:
            chain_def = json.loads(args.chain_def)
        except json.JSONDecodeError as e:
            print(json.dumps({"status": "ERROR", "diagnosis": f"chain_def JSON 解析失败: {e}"}, ensure_ascii=False))
            sys.exit(1)

        if args.step_idx < 0 or args.step_idx >= len(chain_def):
            print(json.dumps({
                "status": "ERROR",
                "diagnosis": f"step_idx {args.step_idx} 超出 chain_def 范围 (0..{len(chain_def) - 1})",
            }, ensure_ascii=False))
            sys.exit(1)

        step = chain_def[args.step_idx]
        result = run_verification(step)

    elif args.action == "rescue":
        result = _rescue(args.task_id, step_idx=args.step_idx)

    elif args.action == "kill":
        result = _kill(args.task_id)

    elif args.action == "pause":
        result = _pause(args.task_id)

    else:
        # advance (原有行为，保持向后兼容)
        if not args.chain_def or not args.chain_step_skills or not args.last_result:
            print(json.dumps({
                "status": "ERROR",
                "diagnosis": "advance action 需要 --chain_def, --chain_step_skills, --last_result 三个参数",
            }, ensure_ascii=False))
            sys.exit(1)

        try:
            chain_def = json.loads(args.chain_def)
            chain_step_skills = json.loads(args.chain_step_skills)
            last_result = json.loads(args.last_result)
        except json.JSONDecodeError as e:
            print(json.dumps({"status": "ERROR", "diagnosis": f"JSON 解析失败: {e}"}, ensure_ascii=False))
            sys.exit(1)
        result = advance(args.task_id, chain_def, chain_step_skills, last_result,
                         chain_owner=args.chain_owner, report_only=args.report_only,
                         dry_run=args.dry_run)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

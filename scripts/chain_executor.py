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
import sys

try:
    import yaml
except ImportError:
    yaml = None

# ── 路径计算 ────────────────────────────────────
_SCRIPT_DIR_CHAIN = os.path.dirname(os.path.abspath(__file__))

# ── 默认配置 ────────────────────────────────────
MAX_RETRY = 3
STATE_DIR = "/opt/data/.shared"
INDEX_YAML_PATH = os.path.join(_SCRIPT_DIR_CHAIN, "..", "route-map", "index.yaml")

# ── per-step 合法回报状态映射 ────────────────────
STEP_VALID_STATUSES = {
    "tdd":           ["DONE", "BLOCKED", "NEEDS_CONTEXT", "DONE_WITH_CONCERNS"],
    "spec-review":   ["DONE", "NEEDS_FIX", "BLOCKED", "NEEDS_CONTEXT", "DONE_WITH_CONCERNS"],
    "quality-review":["APPROVE", "NEEDS_FIX", "BLOCKED", "NEEDS_CONTEXT"],
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
    return step.get("type", STEP_TYPE_SERIAL)


def _build_parallel_result(step: dict, step_idx: int) -> dict:
    """为 parallel 步骤构建 CONTINUE_PARALLEL 响应。

    返回结构包含 branches 列表和 join_strategy，
    主 Agent 收到后需并行 delegate_task 所有 branches。
    """
    branches = step.get("branches", [])
    if not branches:
        return {"status": "ERROR", "diagnosis": f"step[{step_idx}] parallel 没有 branches"}

    branch_tasks = []
    for b in branches:
        task = {
            "agent": b["agent"],
            "goal": b["goal"],
            "context": b.get("context", ""),
        }
        if b.get("keywords"):
            task["keywords"] = b["keywords"]
        branch_tasks.append(task)

    return {
        "status": STATUS_CONTINUE_PARALLEL,
        "next": branch_tasks,
        "join_strategy": step.get("join_strategy", "separate"),
        "branch_count": len(branches),
        "context": {"chain_step": step_idx, "step_type": STEP_TYPE_PARALLEL},
    }


def _build_interactive_result(step: dict, step_idx: int) -> dict:
    """为 interactive 步骤构建 NEEDS_CONTEXT 响应（带 interactive 标记）。

    主 Agent 收到后应暂停链并询问用户确认。
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
    return result


def _build_loop_result(step: dict, step_idx: int, context: dict) -> dict:
    """为 loop 步骤构建 CONTINUE_LOOP 响应。

    从 context 取出 source 数据展开为多个 loop items，
    主 Agent 收到后需逐个执行并按 loop_complete 回传。
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

    return {
        "status": STATUS_CONTINUE_LOOP,
        "next": loop_items,
        "loop_count": len(loop_items),
        "context": {"chain_step": step_idx, "step_type": STEP_TYPE_LOOP},
    }


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
    """
    errors = []
    for i, step in enumerate(chain_def):
        step_type = _get_step_type(step)
        if step_type != STEP_TYPE_SERIAL:
            continue  # 非 serial 步骤无需 skills key
        key = f"{chain_owner}@{i}"
        if key not in chain_step_skills:
            errors.append(f"缺少 skills key: '{key}' (step {i}: {step['agent']} → {step['goal']})")
    return errors


def _sanitize_task_id(task_id: str) -> str:
    """净化 task_id，防止路径遍历攻击"""
    if not re.match(r'^[a-zA-Z0-9_.-]+$', task_id):
        raise ValueError(f"非法 task_id: {task_id}（仅允许字母、数字、下划线、点、连字符）")
    return task_id


def _state_path(task_id: str) -> str:
    _sanitize_task_id(task_id)
    return os.path.join(STATE_DIR, task_id, "chain-state.json")


def _load_state(task_id: str) -> dict:
    path = _state_path(task_id)
    if not os.path.exists(path):
        return {
            "current_step": 0,
            "spec_retry": 0,
            "quality_retry": 0,
            "concerns": [],
            "context": {},
        }
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise RuntimeError(
            f"state 文件损坏或不可读: {path} — {e}。"
            f"如需恢复，请检查/删除此文件后重试。"
        )


def _save_state(task_id: str, state: dict):
    path = _state_path(task_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _build_step_result(step: dict, chain_owner: str, step_idx: int,
                       chain_step_skills: dict, context: dict | None = None) -> dict:
    """为单个 step 构建响应。支持 serial / parallel / interactive / loop 四种类型。

    如果 step 有 type 字段且不为 serial，委托给对应的专用构建函数。
    如果 step 有 batch: true，返回 CONTINUE_BATCH 数组。
    """
    step_type = _get_step_type(step)

    if step_type == STEP_TYPE_PARALLEL:
        return _build_parallel_result(step, step_idx)
    elif step_type == STEP_TYPE_INTERACTIVE:
        return _build_interactive_result(step, step_idx)
    elif step_type == STEP_TYPE_LOOP:
        return _build_loop_result(step, step_idx, context or {})

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
        key = f"{chain_owner}@{step_idx}"
        skills = chain_step_skills.get(key, [])
        next_item = {
            "agent": step["agent"],
            "goal": step["goal"],
            "skills": skills,
        }
        if step.get("keywords"):
            next_item["keywords"] = step["keywords"]
        return {
            "status": "CONTINUE",
            "next": next_item,
            "context": {"chain_step": step_idx, "step_goal": step["goal"]},
        }


def start_chain(task_id: str, chain_def: list, chain_step_skills: dict, chain_owner: str,
                report_only: bool = False):
    """
    start action：封装首次 advance 调用，自动构造 last_result={"status":"init"}。
    等价于 advance(task_id, chain_def, chain_step_skills, {"status":"init"}, chain_owner, report_only)。
    """
    return advance(task_id, chain_def, chain_step_skills, {"status": "init"}, chain_owner, report_only=report_only)


def run_chain(task_id: str, chain_agent: str, last_result: dict):
    """
    run action：从 index.yaml 读取 chain_def + chain_step_skills，然后调用 advance。
    """
    # 尝试导入 yaml
    if yaml is None:
        return {"status": "ERROR", "diagnosis": "缺少 PyYAML 库，请先安装 (pip install pyyaml)"}

    try:
        with open(INDEX_YAML_PATH, "r") as f:
            index_data = yaml.safe_load(f)
    except FileNotFoundError:
        return {"status": "ERROR", "diagnosis": f"未找到 index.yaml: {INDEX_YAML_PATH}"}
    except yaml.YAMLError as e:
        return {"status": "ERROR", "diagnosis": f"解析 index.yaml 失败: {str(e)}"}

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
            _route_map_dir = os.path.join(_SCRIPT_DIR_CHAIN, "..", "route-map")
            chain_file = os.path.join(_route_map_dir, "chains", f"{chain_ref}.yaml")
            if os.path.exists(chain_file):
                with open(chain_file, "r") as f:
                    chain_data = yaml.safe_load(f)
                chain_def = chain_data.get("steps", [])
                chain_step_skills = chain_data.get("chain_step_skills", {})
                report_only = chain_data.get("report_only", False)
            else:
                return {"status": "ERROR", "diagnosis": f"chain_ref 文件不存在: {chain_file}"}

    if not chain_def:
        return {"status": "ERROR", "diagnosis": f"agent '{chain_agent}' 未定义 chain 或 chain_ref"}

    chain_owner = chain_agent

    return advance(task_id, chain_def, chain_step_skills, last_result, chain_owner, report_only=report_only)


def advance(task_id: str, chain_def: list, chain_step_skills: dict,
            last_result: dict, chain_owner: str = "", report_only: bool = False):
    """
    last_result: 从上一步委托返回的结果 dict
      必有: agent, status
      可选: output_path, findings, message
    1) 首个调用: last_result={"status":"init"}
    2) batch 场景: last_result 可含 batch_index 或 batch_complete
    chain_owner: 链所属的 Agent（用于构建 skills key: {owner}@{idx}）
    report_only: 链完成后返回 REPORT_ONLY 状态码而非 DONE
    """

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
        # 重置状态（避免跨 session 污染）
        state.update({
            "current_step": 0, "spec_retry": 0, "quality_retry": 0,
            "concerns": [], "context": {}, "chain_owner": chain_owner,
            "report_only": report_only,
        })
        _save_state(task_id, state)

        step = chain_def[0]
        return _build_step_result(step, chain_owner, 0, chain_step_skills, state.get("context", {}))

    try:
        state = _load_state(task_id)
    except RuntimeError as e:
        return {"status": "ERROR", "diagnosis": str(e)}
    # 使用 state 中存储的 chain_owner（首次调用时已保存）
    chain_owner = state.get("chain_owner", chain_owner)
    agent = last_result.get("agent", "")
    status = last_result.get("status", "")
    if "current_step" not in state:
        return {"status": "ERROR", "diagnosis": f"state 文件缺少 current_step，可能已损坏（task_id={task_id}）"}
    step_idx = state["current_step"]
    if step_idx >= len(chain_def):
        return {"status": "ERROR", "diagnosis": f"state.current_step ({step_idx}) >= chain_def 长度 ({len(chain_def)})，状态与链定义不匹配"}

    # ── batch_complete — 批次全部完成，推进到下一步 ──
    if last_result.get("batch_complete"):
        # 保存 batch 结果到上下文
        batch_results = last_result.get("batch_results", [])
        if batch_results:
            state["context"]["batch_results"] = batch_results
        _save_state(task_id, state)
        # 正常推进到下一步
        state["current_step"] += 1
        if state["current_step"] >= len(chain_def):
            _save_state(task_id, state)
            return {
                "status": "REPORT_ONLY" if state.get("report_only") else "DONE",
                "final_output_path": state["context"].get("last_output", ""),
                "concerns": state["concerns"],
                "summary": {
                    "total_steps": len(chain_def),
                    "spec_retry_count": state["spec_retry"],
                    "quality_retry_count": state["quality_retry"],
                    "concerns_count": len(state["concerns"]),
                },
            }
        _save_state(task_id, state)
        step = chain_def[state["current_step"]]
        return _build_step_result(step, chain_owner, state["current_step"], chain_step_skills, state.get("context", {}))

    # ── branches_complete — 并行分支全部完成，推进到下一步 ──
    if last_result.get("branches_complete"):
        branch_results = last_result.get("branch_results", [])
        if branch_results:
            state["context"]["branch_results"] = branch_results
        _save_state(task_id, state)
        state["current_step"] += 1
        if state["current_step"] >= len(chain_def):
            _save_state(task_id, state)
            return {
                "status": "REPORT_ONLY" if state.get("report_only") else "DONE",
                "final_output_path": state["context"].get("last_output", ""),
                "concerns": state["concerns"],
                "summary": {
                    "total_steps": len(chain_def),
                    "spec_retry_count": state["spec_retry"],
                    "quality_retry_count": state["quality_retry"],
                    "concerns_count": len(state["concerns"]),
                },
            }
        _save_state(task_id, state)
        step = chain_def[state["current_step"]]
        return _build_step_result(step, chain_owner, state["current_step"], chain_step_skills, state.get("context", {}))

    # ── loop_complete — 循环项全部完成，推进到下一步 ──
    if last_result.get("loop_complete"):
        loop_results = last_result.get("loop_results", [])
        if loop_results:
            state["context"]["loop_results"] = loop_results
        _save_state(task_id, state)
        state["current_step"] += 1
        if state["current_step"] >= len(chain_def):
            _save_state(task_id, state)
            return {
                "status": "REPORT_ONLY" if state.get("report_only") else "DONE",
                "final_output_path": state["context"].get("last_output", ""),
                "concerns": state["concerns"],
                "summary": {
                    "total_steps": len(chain_def),
                    "spec_retry_count": state["spec_retry"],
                    "quality_retry_count": state["quality_retry"],
                    "concerns_count": len(state["concerns"]),
                },
            }
        _save_state(task_id, state)
        step = chain_def[state["current_step"]]
        return _build_step_result(step, chain_owner, state["current_step"], chain_step_skills, state.get("context", {}))

    # ── branch_index — 单个并行分支完成，累加结果 ──
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
            "message": f"Branch {branch_index + 1} completed. Awaiting remaining or branches_complete.",
        }

    # ── batch_index — 单个 batch 分片完成，累加结果 ──
    if last_result.get("batch_index") is not None:
        batch_index = last_result["batch_index"]
        if "batch_results" not in state["context"]:
            state["context"]["batch_results"] = []
        # 扩展数组至足够长
        while len(state["context"]["batch_results"]) <= batch_index:
            state["context"]["batch_results"].append(None)
        state["context"]["batch_results"][batch_index] = {
            "agent": agent,
            "status": status,
            "output_path": last_result.get("output_path", ""),
            "message": last_result.get("message", ""),
            "findings": last_result.get("findings", ""),
        }
        _save_state(task_id, state)
        return {
            "status": "BATCH_PROGRESS",
            "batch_index": batch_index,
            "batch_count": len(state["context"]["batch_results"]),
            "context": state.get("context", {}),
            "message": f"Batch item {batch_index + 1} completed. Awaiting remaining or batch_complete.",
        }

    # ── 校验状态合法性 ──
    step_goal = chain_def[step_idx].get("goal", "")
    if not step_goal:
        return {"status": "ERROR", "diagnosis": f"step[{step_idx}] 缺少 goal 字段（可能 parallel/interactive/loop 步骤未经过 completion handler）"}
    step_type = _infer_step_type(step_goal)
    valid = STEP_VALID_STATUSES.get(step_type, ["DONE", "BLOCKED"])
    if status not in valid:
        return {
            "status": "ERROR",
            "diagnosis": f"step[{step_idx}] '{step_goal}' (agent={agent}) 返回非法状态 '{status}'。合法状态: {valid}",
        }

    # ── BLOCKED — 挂起 ──
    if status == "BLOCKED":
        return {
            "status": "BLOCKED",
            "step_idx": step_idx,
            "agent": agent,
            "goal": step_goal,
            "diagnosis": last_result.get("message", "阻塞，无诊断信息"),
        }

    # ── NEEDS_CONTEXT — 等待用户 ──
    if status == "NEEDS_CONTEXT":
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
        # 判断是 spec fix 还是 quality fix（利用 _infer_step_type 兼容中文 goal）
        step_type = _infer_step_type(step_goal)
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
            return {
                "status": "RETRY",
                "next": {
                    "agent": "programmer",
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
            return {
                "status": "RETRY",
                "next": {
                    "agent": "programmer",
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

    # ── DONE / APPROVE — 推进或回归 ──
    if status in ("DONE", "APPROVE"):
        # 保存产出路径到上下文
        if last_result.get("output_path"):
            state["context"]["diff_path"] = last_result["output_path"]
        state["context"]["last_output"] = last_result.get("output_path", "")

        # 防御检查：RETRY 上下文中缺少 target_step_idx
        if last_result.get("target_step_idx") is None and state["context"].get("retry_type"):
            return {
                "status": "ERROR",
                "diagnosis": f"fix 步骤 DONE 但缺少 target_step_idx（retry_type={state['context'].get('retry_type')}）。主 Agent 应在 fix 完成后回传 target_step_idx 以回到评审步骤。",
            }

        # fix 循环后回到 review step
        if last_result.get("target_step_idx") is not None:
            state["current_step"] = last_result["target_step_idx"]
            _save_state(task_id, state)
            step = chain_def[state["current_step"]]
            return _build_step_result(step, chain_owner, state["current_step"], chain_step_skills, state.get("context", {}))

        # 正常推进到下一步
        state["current_step"] += 1
        if state["current_step"] >= len(chain_def):
            _save_state(task_id, state)
            return {
                "status": "REPORT_ONLY" if state.get("report_only") else "DONE",
                "final_output_path": state["context"].get("last_output", ""),
                "concerns": state["concerns"],
                "summary": {
                    "total_steps": len(chain_def),
                    "spec_retry_count": state["spec_retry"],
                    "quality_retry_count": state["quality_retry"],
                    "concerns_count": len(state["concerns"]),
                },
            }

        _save_state(task_id, state)
        step = chain_def[state["current_step"]]
        return _build_step_result(step, chain_owner, state["current_step"], chain_step_skills, state.get("context", {}))

    return {"status": "ERROR", "diagnosis": f"未处理的状态: {status}"}


def main():
    parser = argparse.ArgumentParser(description="Chain 编排引擎")
    parser.add_argument("action", choices=["advance", "start", "run"])
    parser.add_argument("--task_id", required=True)
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
    args = parser.parse_args()

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
                             report_only=args.report_only)

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
                         chain_owner=args.chain_owner, report_only=args.report_only)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

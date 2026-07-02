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

# ── 默认配置 ────────────────────────────────────
MAX_RETRY = 3
STATE_DIR = "/opt/data/.shared"
INDEX_YAML_PATH = "/opt/data/route-map/index.yaml"

# ── per-step 合法回报状态映射 ────────────────────
STEP_VALID_STATUSES = {
    "tdd":           ["DONE", "BLOCKED", "NEEDS_CONTEXT", "DONE_WITH_CONCERNS"],
    "spec-review":   ["DONE", "NEEDS_FIX", "BLOCKED", "NEEDS_CONTEXT", "DONE_WITH_CONCERNS"],
    "quality-review":["APPROVE", "NEEDS_FIX", "BLOCKED", "NEEDS_CONTEXT"],
    "fix":           ["DONE", "BLOCKED", "NEEDS_CONTEXT"],
}

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


def _validate_skills(chain_def: list, chain_step_skills: dict, chain_owner: str) -> list:
    """验证所有 chain step 都有对应的 skills key。返回错误列表，空列表表示无错误。"""
    errors = []
    for i, step in enumerate(chain_def):
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
                       chain_step_skills: dict) -> dict:
    """为单个 step 构建 CONTINUE 响应。如果 step 有 batch: true，返回 CONTINUE_BATCH 数组。"""
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
        for i, goal in enumerate(goals):
            next_items.append({
                "agent": step["agent"],
                "goal": goal,
                "batch_index": i,
            })

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
        return {
            "status": "CONTINUE",
            "next": {"agent": step["agent"], "goal": step["goal"], "skills": skills},
            "context": {"chain_step": step_idx, "step_goal": step["goal"]},
        }


def start_chain(task_id: str, chain_def: list, chain_step_skills: dict, chain_owner: str):
    """
    start action：封装首次 advance 调用，自动构造 last_result={"status":"init"}。
    等价于 advance(task_id, chain_def, chain_step_skills, {"status":"init"}, chain_owner)。
    """
    return advance(task_id, chain_def, chain_step_skills, {"status": "init"}, chain_owner)


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
    if not chain_def:
        return {"status": "ERROR", "diagnosis": f"agent '{chain_agent}' 未定义 chain"}

    chain_step_skills = agent_config.get("chain_step_skills", {})
    chain_owner = chain_agent

    return advance(task_id, chain_def, chain_step_skills, last_result, chain_owner)


def advance(task_id: str, chain_def: list, chain_step_skills: dict,
            last_result: dict, chain_owner: str = ""):
    """
    last_result: 从上一步委托返回的结果 dict
      必有: agent, status
      可选: output_path, findings, message
    1) 首个调用: last_result={"status":"init"}
    2) batch 场景: last_result 可含 batch_index 或 batch_complete
    chain_owner: 链所属的 Agent（用于构建 skills key: {owner}@{idx}）
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
        })
        _save_state(task_id, state)

        step = chain_def[0]
        return _build_step_result(step, chain_owner, 0, chain_step_skills)

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
    step_goal = chain_def[step_idx]["goal"]

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
                "status": "DONE",
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
        return _build_step_result(step, chain_owner, state["current_step"], chain_step_skills)

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
        # 判断是 spec fix 还是 quality fix
        if "spec" in step_goal.lower():
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
        elif "quality" in step_goal.lower():
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
            return _build_step_result(step, chain_owner, state["current_step"], chain_step_skills)

        # 正常推进到下一步
        state["current_step"] += 1
        if state["current_step"] >= len(chain_def):
            _save_state(task_id, state)
            return {
                "status": "DONE",
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
        return _build_step_result(step, chain_owner, state["current_step"], chain_step_skills)

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
        result = start_chain(args.task_id, chain_def, chain_step_skills, args.chain_owner)

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
                         chain_owner=args.chain_owner)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

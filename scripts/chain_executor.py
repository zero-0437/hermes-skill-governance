#!/usr/bin/env python3
"""
chain_executor.py — chain 编排引擎（状态机）

调用方式：
  python3 scripts/chain_executor.py advance \\
    --task_id T-001 \\
    --chain_def '[{"agent":"programmer","goal":"..."},{"agent":"error-analyst","goal":"..."}]' \\
    --chain_step_skills '{"programmer_0":["test-driven-development"]}' \\
    --last_result '{"agent":"programmer","status":"DONE","output_path":"..."}'

chain_executor 不调用 delegate_task — 只产出决策 JSON。
主 Agent 读 JSON → delegate_task → 拿到结果后再调 chain_executor。
"""

import argparse, json, os, sys

# ── 默认配置 ────────────────────────────────────
MAX_RETRY = 3
STATE_DIR = "/opt/data/.shared"

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


def _validate_skills(chain_def: list, chain_step_skills: dict, chain_owner: str):
    """验证所有 chain step 都有对应的 skills key"""
    errors = []
    for i, step in enumerate(chain_def):
        key = f"{chain_owner}@{i}"
        if key not in chain_step_skills:
            errors.append(f"缺少 skills key: '{key}' (step {i}: {step['agent']} → {step['goal']})")
    if errors:
        print(json.dumps({
            "status": "ERROR",
            "diagnosis": "; ".join(errors),
            "defined_keys": list(chain_step_skills.keys()),
        }))
        sys.exit(1)


def _state_path(task_id: str) -> str:
    return os.path.join(STATE_DIR, task_id, "chain-state.json")


def _load_state(task_id: str) -> dict:
    path = _state_path(task_id)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {
        "current_step": 0,
        "spec_retry": 0,
        "quality_retry": 0,
        "concerns": [],
        "context": {},
    }


def _save_state(task_id: str, state: dict):
    path = _state_path(task_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def advance(task_id: str, chain_def: list, chain_step_skills: dict, last_result: dict, chain_owner: str = ""):
    """
    last_result: 从上一步委托返回的结果 dict
      必有: agent, status
      可选: output_path, findings, message
    1) 首个调用: last_result={"status":"init"}
    chain_owner: 链所属的 Agent（用于构建 skills key: {owner}@{idx}）
    """

    # ── 首次调用 ──
    if last_result.get("status") == "init":
        if not chain_owner:
            return {"status": "ERROR", "diagnosis": "首次调用必须指定 --chain_owner"}
        _validate_skills(chain_def, chain_step_skills, chain_owner)
        state = _load_state(task_id)
        # 重置状态（避免跨 session 污染）
        state.update({"current_step": 0, "spec_retry": 0, "quality_retry": 0, "concerns": [], "context": {}, "chain_owner": chain_owner})
        _save_state(task_id, state)

        step = chain_def[0]
        key = f"{chain_owner}@0"
        skills = chain_step_skills.get(key, [])
        return {
            "status": "CONTINUE",
            "next": {"agent": step["agent"], "goal": step["goal"], "skills": skills},
            "context": {"chain_step": 0, "step_goal": step["goal"]},
        }

    state = _load_state(task_id)
    # 使用 state 中存储的 chain_owner（首次调用时已保存）
    chain_owner = state.get("chain_owner", chain_owner)
    agent = last_result.get("agent", "")
    status = last_result.get("status", "")
    step_idx = state["current_step"]
    step_goal = chain_def[step_idx]["goal"]

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
            key = f"{chain_owner}@{state['current_step']}"
            skills = chain_step_skills.get(key, [])
            return {
                "status": "CONTINUE",
                "next": {"agent": step["agent"], "goal": step["goal"], "skills": skills},
                "context": {
                    "chain_step": state["current_step"],
                    "step_goal": step["goal"],
                    "review_findings": state["context"].get("review_findings", ""),
                    "original_diff_path": state["context"].get("diff_path", ""),
                },
            }

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
        key = f"{chain_owner}@{state['current_step']}"
        skills = chain_step_skills.get(key, [])
        return {
            "status": "CONTINUE",
            "next": {"agent": step["agent"], "goal": step["goal"], "skills": skills},
            "context": {
                "chain_step": state["current_step"],
                "step_goal": step["goal"],
                "last_output": state["context"].get("last_output", ""),
            },
        }

    return {"status": "ERROR", "diagnosis": f"未处理的状态: {status}"}


def main():
    parser = argparse.ArgumentParser(description="Chain 编排引擎")
    parser.add_argument("action", choices=["advance"])
    parser.add_argument("--task_id", required=True)
    parser.add_argument("--chain_def", required=True, help="JSON: [{agent, goal}, ...]")
    parser.add_argument("--chain_step_skills", required=True, help="JSON: {owner@idx: [skill, ...]}")
    parser.add_argument("--last_result", required=True, help="JSON: {agent, status, ...}")
    parser.add_argument("--chain_owner", default="", help="链所属 Agent（首次调用必填）")
    args = parser.parse_args()

    chain_def = json.loads(args.chain_def)
    chain_step_skills = json.loads(args.chain_step_skills)
    last_result = json.loads(args.last_result)

    result = advance(args.task_id, chain_def, chain_step_skills, last_result, chain_owner=args.chain_owner)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

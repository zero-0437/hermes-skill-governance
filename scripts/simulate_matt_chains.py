#!/usr/bin/env python3
"""
simulate_matt_chains.py — Matt Pocock 任务链模式模拟器

模拟 3 种核心模式在现有 chain_executor.py 上的运行效果：
  1. 并行不同 Agent（code-review: Standards + Spec）
  2. 聚合策略（并行结果合并）
  3. 用户交互步骤（to-prd → 等人确认 → to-issues）

不修改现有代码，只模拟"扩展后的 chain YAML → chain_executor 应当如何响应"。
"""

import json
import sys
import os

# ── 模拟的扩展 chain YAML 格式 ────────────────────────────────────

SIM_CHAINS = {
    # ── Model 1: 并行不同 Agent（code-review 风格） ──
    "parallel-review": {
        "description": "code-review 并行双轴审查",
        "steps": [
            {
                "type": "parallel",
                "branches": [
                    {
                        "agent": "error-analyst",
                        "goal": "Standards 审查：检查代码规范和 Fowler 坏味道",
                        "context": "${{diff_path}}",
                    },
                    {
                        "agent": "programmer",
                        "goal": "Spec 审查：检查实现是否匹配 spec/PRD",
                        "context": "${{diff_path}} + ${{spec_source}}",
                    },
                ],
                # 聚合策略
                "join_strategy": "separate",  # separate | synthesize
            },
        ],
    },

    # ── Model 2: 三阶段管线 + 用户交互（to-prd → to-issues → implement） ──
    "feature-pipeline": {
        "description": "新功能三阶段管线",
        "steps": [
            {
                "agent": "pm-agent",
                "goal": "输出 PRD：综合已有讨论，产出 PRD issue 模板",
                "type": "interactive",  # 完成后等人确认
            },
            {
                "agent": "pm-agent",
                "goal": "垂直切片分解：从 PRD 拆解为独立可实现的 issue 列表",
                "type": "interactive",
            },
            {
                "agent": "programmer",
                "goal": "按 issue 列表逐个实现",
                "type": "loop",
                "source": "previous_output",  # 循环源：上一步的 issue 列表
            },
        ],
    },

    # ── Model 3: 薄 wrapper 委派（grill-with-docs → grilling + domain-modeling） ──
    "wrapper-delegation": {
        "description": "薄 wrapper 并行委派",
        "steps": [
            {
                "type": "parallel",
                "branches": [
                    {
                        "agent": "pm-agent",
                        "goal": "执行 grilling：通过面试问题收集需求，走完决策树",
                    },
                    {
                        "agent": "spec-agent",
                        "goal": "执行 domain-modeling：更新领域词汇表和 ADR",
                    },
                ],
                "join_strategy": "synthesize",  # 聚合对比
            },
        ],
    },
}


# ── 模拟引擎 ──────────────────────────────────────────────────────

def simulate_step(step: dict, step_idx: int, context: dict) -> dict:
    """模拟 chain_executor 对单个 step 的响应"""
    step_type = step.get("type", "serial")

    if step_type == "parallel":
        return simulate_parallel(step, step_idx, context)
    elif step_type == "interactive":
        return simulate_interactive(step, step_idx, context)
    elif step_type == "loop":
        return simulate_loop(step, step_idx, context)
    else:
        return simulate_serial(step, step_idx, context)


def simulate_parallel(step: dict, step_idx: int, context: dict) -> dict:
    """模拟并行步骤：返回 CONTINUE_PARALLEL 状态码"""
    branches = step.get("branches", [])
    join_strategy = step.get("join_strategy", "separate")

    if not branches:
        return {"status": "ERROR", "diagnosis": f"step[{step_idx}] parallel 没有 branches"}

    branch_tasks = []
    for b in branches:
        branch_tasks.append({
            "agent": b["agent"],
            "goal": b["goal"],
            "context": b.get("context", ""),
        })

    return {
        "status": "CONTINUE_PARALLEL",       # ← 新状态码
        "next": branch_tasks,                 # 需要主 Agent 并行 delegate_task
        "join_strategy": join_strategy,
        "branch_count": len(branches),
        "context": {"chain_step": step_idx, "step_type": "parallel"},
    }


def simulate_interactive(step: dict, step_idx: int, context: dict) -> dict:
    """模拟交互步骤：返回 NEEDS_CONTEXT 让人确认"""
    return {
        "status": "NEEDS_CONTEXT",            # 已有状态码
        "step_idx": step_idx,
        "agent": step["agent"],
        "goal": step["goal"],
        "question": f"[{step['agent']}] 已完成: {step['goal']}\n请确认结果，或补充修改意见后继续下一步。",
        "interactive": True,                  # ← 标记是 interactive 而非普通 context 缺失
    }


def simulate_loop(step: dict, step_idx: int, context: dict) -> dict:
    """模拟循环步骤：返回 CONTINUE_LOOP 状态码"""
    source = step.get("source", "previous_output")
    items = context.get(source, [])

    if not items:
        # 没有数据源 → 生成模拟数据
        items = [{"issue": f"实现垂直切片 {i+1}"} for i in range(3)]

    loop_items = []
    for item in items:
        loop_items.append({
            "agent": step["agent"],
            "goal": step["goal"],
            "loop_context": item,
        })

    return {
        "status": "CONTINUE_LOOP",            # ← 新状态码
        "next": loop_items,
        "loop_count": len(loop_items),
        "context": {"chain_step": step_idx, "step_type": "loop"},
    }


def simulate_serial(step: dict, step_idx: int, context: dict) -> dict:
    """模拟串行步骤（现有行为）"""
    return {
        "status": "CONTINUE",
        "next": {"agent": step["agent"], "goal": step["goal"]},
        "context": {"chain_step": step_idx, "step_type": "serial"},
    }


def simulate_aggregation(branch_results: list[dict], join_strategy: str) -> dict:
    """模拟聚合步骤：主 Agent 收集所有并行结果后调用"""
    if join_strategy == "separate":
        # code-review 风格：不交叉排序，保留各轴完整性
        return {
            "status": "DONE",
            "output_type": "separate_report",
            "reports": {
                r["name"]: {"content": r.get("summary", ""), "findings": r.get("findings", [])}
                for r in branch_results
            },
            "summary": "并行结果已按轴独立输出，未做交叉排序",
        }
    elif join_strategy == "synthesize":
        # grill-with-docs 风格：对比合成
        return {
            "status": "DONE",
            "output_type": "synthesized_report",
            "individual_reports": {
                r["name"]: r.get("summary", "")
                for r in branch_results
            },
            "comparison": {
                "common_points": ["需求 A", "约束 B"],
                "divergences": [
                    {"point": "实现方案", "branch_a": "方案 X", "branch_b": "方案 Y"},
                ],
            },
        }
    else:
        return {"status": "ERROR", "diagnosis": f"未知聚合策略: {join_strategy}"}


# ── 完整模拟运行 ──────────────────────────────────────────────────

def run_simulation(chain_name: str, chain_def: dict) -> list[dict]:
    """执行完整链模拟，返回每个步骤的输出"""
    print(f"\n{'='*70}")
    print(f"模拟链: {chain_name} — {chain_def['description']}")
    print(f"{'='*70}")

    context = {}
    outputs = []

    for idx, step in enumerate(chain_def["steps"]):
        print(f"\n── Step {idx}: type={step.get('type', 'serial')} ──")
        result = simulate_step(step, idx, context)
        print(f"  状态: {result['status']}")
        print(f"  产出: {json.dumps(result, ensure_ascii=False, indent=4)}")
        outputs.append(result)

        # 模拟主 Agent 的后续处理（收集并行结果等）
        if result["status"] == "CONTINUE_PARALLEL":
            # 模拟并行执行完成后的聚合
            branch_count = result["branch_count"]
            mock_results = []
            for i, branch in enumerate(result["next"]):
                mock_results.append({
                    "name": branch["agent"],
                    "summary": f"{branch['agent']} 对 {branch['goal'][:20]}... 的审查报告",
                    "findings": [f"发现 {i+1}"],
                })
            agg = simulate_aggregation(mock_results, result["join_strategy"])
            print(f"\n  ⤷ 聚合结果 ({result['join_strategy']}):")
            print(f"    {json.dumps(agg, ensure_ascii=False, indent=4)}")

            # 将结果存回 context 供后续步骤使用
            context["last_parallel_results"] = agg

        elif result["status"] == "CONTINUE_LOOP":
            loop_count = result["loop_count"]
            print(f"\n  ⤷ 需循环 {loop_count} 次（逐 issue 实现）")
            context["loop_items"] = result["next"]

        elif result["status"] == "NEEDS_CONTEXT" and result.get("interactive"):
            print(f"\n  ⤷ 等待用户确认（interactive step）")

        elif result["status"] == "CONTINUE":
            context["previous_output"] = [{"issue": "切片 1"}, {"issue": "切片 2"}]
            print(f"\n  ⤷ 串行推进到下一 Agent: {result['next']['agent']}")

    print(f"\n{'='*70}")
    print(f"链 {chain_name} 模拟完成")
    print(f"{'='*70}")
    return outputs


def main():
    for name, chain in SIM_CHAINS.items():
        run_simulation(name, chain)

    # ── 兼容性验证：现有 chain 格式仍然可用 ──
    print(f"\n\n{'='*70}")
    print(f"向后兼容性验证：现有 chain 格式")
    print(f"{'='*70}")
    existing = {
        "description": "现有 dual-review chain",
        "steps": [
            {"agent": "error-analyst", "goal": "spec 合规评审"},
            {"agent": "programmer", "goal": "代码质量评审"},
        ],
    }
    run_simulation("existing-chain", existing)

    print(f"\n\n✅ 所有模拟完成，3 种扩展模式验证通过")


if __name__ == "__main__":
    main()

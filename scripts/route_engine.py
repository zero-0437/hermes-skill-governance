#!/usr/bin/env python3
"""
route_engine.py — 纯 Python 路由引擎
根据用户输入文本，通过关键词/正则/短语匹配路由到对应 Agent。
"""

import json
import os
import re
import yaml

# ── 模块级缓存 ─────────────────────────────────────────────────────
_route_map_cache: dict | None = None
_skill_cache: dict | None = None
_has_fuzzy_cache: bool | None = None


def _clear_cache():
    """安全清空所有模块级缓存（路由规则 + 技能 + 模糊检测）。"""
    global _route_map_cache, _skill_cache, _has_fuzzy_cache
    _route_map_cache = None
    _skill_cache = None
    _has_fuzzy_cache = None

# ── 模糊匹配常量 ───────────────────────────────────────────────────
FUZZY_OVERLAP_THRESHOLD = 0.6   # keyword 模糊重叠率阈值
CJK_CHAR_RE = re.compile(r'[\u4e00-\u9fff]')
CJK_BLOCK_RE = re.compile(r'[\u4e00-\u9fff]+')
EN_WORD_RE = re.compile(r'[a-z][a-z0-9_]*')

# ── 路径解析 ──────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROUTE_MAP_DIR = os.path.join(_SCRIPT_DIR, "..", "route-map")
_SKILL_CACHE_FILE = os.path.join(_SCRIPT_DIR, "..", ".skill-cache.json")


# ── 辅助函数 ───────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """文本归一化：转小写"""
    return text.lower()


def load_route_map() -> dict:
    """加载 route-map/ 目录下的所有规则，合并为单内存表并缓存"""
    global _route_map_cache
    if _route_map_cache is not None:
        return _route_map_cache

    index_path = os.path.join(_ROUTE_MAP_DIR, "index.yaml")
    if not os.path.exists(index_path):
        raise FileNotFoundError(f"route-map 目录不存在: {_ROUTE_MAP_DIR}")

    with open(index_path, "r", encoding="utf-8") as f:
        index = yaml.safe_load(f)

    defaults = index.get("defaults", {})
    overrides = index.get("overrides", [])
    agents_map = index.get("agents", {})

    route_map = {
        "defaults": defaults,
        "overrides": overrides,
        "agents": {},
    }

    for name, info in agents_map.items():
        file_path = os.path.join(_ROUTE_MAP_DIR, info["file"])
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Agent 规则文件不存在: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            agent_data = yaml.safe_load(f)
        route_map["agents"][name] = {
            "rules": agent_data.get("rules", []),
            "priority": info.get("priority", 99),
            "condition": info.get("condition", ""),
            "chain": info.get("chain", []),
        }

    _route_map_cache = route_map
    return route_map


def _load_skill_cache() -> dict | None:
    """加载 .skill-cache.json，获取各 Agent 的 L2 auto / L3 manual 技能"""
    global _skill_cache
    if _skill_cache is not None:
        return _skill_cache
    if not os.path.exists(_SKILL_CACHE_FILE):
        return None
    try:
        with open(_SKILL_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _skill_cache = data.get("agents", {})
        return _skill_cache
    except (json.JSONDecodeError, Exception):
        return None


def _lookup_skills(agent_name: str) -> tuple[list, list]:
    """查询指定 Agent 的 L2 auto 和 L3 manual 技能"""
    cache = _load_skill_cache()
    if not cache:
        return [], []
    agent_data = cache.get(agent_name, {})
    auto = agent_data.get("auto", [])
    manual = agent_data.get("manual", [])
    return auto, manual


# ══════════════════════════════════════════════════════════════════
# 关键词拆解 + 模糊匹配
# ══════════════════════════════════════════════════════════════════


def decompose_keywords(text: str) -> list[str]:
    """纯规则中文/英文关键词拆解，无 NLP 依赖。

    输出：拆解后的候选关键词列表（去重、保留顺序）。
    """
    text = text.lower().strip()
    if not text:
        return []

    seen = set()
    keywords = []

    def _add(kw: str):
        if kw and kw not in seen:
            seen.add(kw)
            keywords.append(kw)

    # ① 英文单词（按空白/标点分割）
    for w in EN_WORD_RE.findall(text):
        _add(w)

    # ② 提取连续 CJK 字符序列
    cjk_blocks = CJK_BLOCK_RE.findall(text)
    full_cjk = "".join(cjk_blocks)

    if full_cjk:
        # ③ 单字（character unigrams）
        for c in full_cjk:
            _add(c)

        # ④ 2-gram 滑动窗口
        for i in range(len(full_cjk) - 1):
            _add(full_cjk[i:i+2])

        # ⑤ 3-gram 滑动窗口
        for i in range(len(full_cjk) - 2):
            _add(full_cjk[i:i+3])

        # ⑥ 完整 CJK 序列
        _add(full_cjk)

    # ⑦ 全文作为兜底
    _add(text)

    return keywords


def _is_subsequence(chars: list[str], sequence: list[str]) -> bool:
    """检查 chars 是否按顺序出现在 sequence 中（子序列匹配）。"""
    i = 0
    for c in chars:
        while i < len(sequence) and sequence[i] != c:
            i += 1
        if i >= len(sequence):
            return False
        i += 1
    return True


def _char_overlap_ratio(pattern: str, input_text: str) -> float:
    """计算 pattern 汉字在 input 中的覆盖率。"""
    p_chars = set(CJK_CHAR_RE.findall(pattern))
    if not p_chars:
        return 0.0
    i_chars = set(CJK_CHAR_RE.findall(input_text))
    if not i_chars:
        return 0.0
    return len(p_chars & i_chars) / len(p_chars)


def match_fuzzy_phrase(normalized: str, pattern: str) -> bool:
    """Fuzzy phrase 匹配：中文子序列 + 英文单词精确匹配。"""
    pattern_lower = pattern.lower()

    # (a) 中文子序列匹配
    p_cjk = CJK_CHAR_RE.findall(pattern_lower)
    n_cjk = CJK_CHAR_RE.findall(normalized)
    if p_cjk:
        if not _is_subsequence(p_cjk, n_cjk):
            return False

    # (b) 英文单词匹配（pattern 中的英文词必须在 input 中出现）
    p_en = set(EN_WORD_RE.findall(pattern_lower))
    n_en = set(EN_WORD_RE.findall(normalized))
    for pw in p_en:
        if pw not in n_en:
            return False

    return True


def match_fuzzy_keyword(normalized: str, pattern: str) -> bool:
    """Fuzzy keyword 匹配：字符重叠率 >= 阈值。"""
    pattern_lower = pattern.lower()

    # 纯英文关键字：fallback 到精确匹配
    if not CJK_CHAR_RE.search(pattern_lower):
        return pattern_lower in normalized

    # 中英文混合：字符重叠率必须达标
    ratio = _char_overlap_ratio(pattern_lower, normalized)
    return ratio >= FUZZY_OVERLAP_THRESHOLD


def _detect_fuzzy_rules(route_map: dict) -> bool:
    """检测 route-map 中是否有任何规则启用了 fuzzy。结果缓存。"""
    global _has_fuzzy_cache
    if _has_fuzzy_cache is not None:
        return _has_fuzzy_cache

    for _name, data in route_map.get("agents", {}).items():
        for rule in data.get("rules", []):
            if rule.get("fuzzy", False):
                _has_fuzzy_cache = True
                return True
    for override in route_map.get("overrides", []):
        for rule in override.get("rules", []):
            if rule.get("fuzzy", False):
                _has_fuzzy_cache = True
                return True
    _has_fuzzy_cache = False
    return False


# ══════════════════════════════════════════════════════════════════
# 规则匹配（exact + fuzzy）
# ══════════════════════════════════════════════════════════════════


def match_rule(normalized: str, rule: dict) -> bool:
    """根据规则类型匹配文本（支持 fuzzy 扩展）。"""
    rule_type = rule.get("type", "regex")
    pattern = rule.get("pattern", "")
    fuzzy = rule.get("fuzzy", False)

    if rule_type == "regex":
        if fuzzy:
            pass  # regex + fuzzy 无意义，静默忽略
        return bool(re.search(pattern, normalized, re.IGNORECASE))
    elif rule_type == "phrase":
        if fuzzy:
            return match_fuzzy_phrase(normalized, pattern)
        return pattern.lower() in normalized
    elif rule_type == "keyword":
        if fuzzy:
            return match_fuzzy_keyword(normalized, pattern)
        return pattern.lower() in normalized
    else:
        raise ValueError(f"不支持的规则类型: {rule_type}")


def evaluate(text: str, route_map: dict) -> list[tuple[str, float, list[dict]]]:
    """对文本评估所有 Agent，返回 (agent_name, score, matched_rules) 降序列表

    matched_rules 是命中的原始规则 dict 列表，供调用方直接提取 pattern / skills，
    避免在调用方再次遍历规则做 match_rule 重复计算。

    负权重语义：
    - 规则 weight 可以为负数，此时命中该规则会降低该 Agent 的总分。
    - 如果总分低于 0，会被钳位到 0.0（不会变为负数）。
    - 负权重让该 Agent 不被选中，但不会让其他 Agent 得分增加。
    - 这实现了"否定路由"：用少量负权重规则即可屏蔽特定 Agent，
      而不影响其他 Agent 的评分结果。
    """
    normalized = _normalize(text)
    agents = route_map["agents"]
    results = []

    for name, data in agents.items():
        score = 0.0
        matched = []
        for rule in data.get("rules", []):
            if match_rule(normalized, rule):
                score += rule.get("weight", 0.0)
                matched.append(rule)
        if score < 0:
            score = 0.0
        results.append((name, score, matched))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def decide(
    scores: list[tuple[str, float]],
    route_map: dict,
    text: str | None = None,
) -> dict:
    """根据评分和策略决定路由目标"""
    defaults = route_map.get("defaults", {})
    min_confidence = defaults.get("min_confidence", 0.5)
    fallback_agent = defaults.get("fallback_agent", "pm-agent")

    # 空评分 → fallback
    if not scores:
        return {
            "agent": fallback_agent,
            "confidence": 0.0,
            "method": "llm_fallback",
            "details": {
                "scores": [],
                "matched_rules": [],
                "fallback_reason": "无匹配规则",
            },
            "auto_skills": [],
            "manual_skills": [],
        }

    top_name, top_score = scores[0]

    # 分数低于阈值 → fallback
    if top_score < min_confidence:
        return {
            "agent": fallback_agent,
            "confidence": top_score,
            "method": "llm_fallback",
            "details": {
                "scores": scores,
                "matched_rules": [],
                "fallback_reason": f"最高分 {top_score:.2f} < 阈值 {min_confidence}",
            },
            "auto_skills": [],
            "manual_skills": [],
        }

    # 检查平局
    tied = [s for s in scores if abs(s[1] - top_score) < 1e-9]
    if len(tied) > 1:
        # 平局：按 priority 裁决（数值越小优先级越高）
        agents = route_map.get("agents", {})
        best = min(tied, key=lambda x: agents.get(x[0], {}).get("priority", 99))
        return {
            "agent": best[0],
            "confidence": top_score,
            "method": "auto_tiebreak",
            "details": {
                "scores": scores,
                "matched_rules": [],
                "fallback_reason": f"平局裁决: {', '.join(a for a, _ in tied)}",
            },
            "auto_skills": [],
            "manual_skills": [],
        }

    # 正常自动路由
    return {
        "agent": top_name,
        "confidence": top_score,
        "method": "auto",
        "details": {
            "scores": scores,
            "matched_rules": [],
            "fallback_reason": "",
        },
        "auto_skills": [],
        "manual_skills": [],
    }


def route(user_input: str) -> dict:
    """
    主入口：路由用户输入到目标 Agent。

    流程：
    1. 加载 route-map
    2. 检查 overrides 是否命中（直接委派，跳过评分）
    3. 否则 evaluate → decide
    """
    route_map = load_route_map()
    normalized = _normalize(user_input)

    # ── 检查 overrides ──────────────────────────────────────────
    overrides = route_map.get("overrides", [])
    matched_rules = []
    matched_skills: set[str] = set()
    for override in overrides:
        agent_name = override["agent"]
        for rule in override.get("rules", []):
            if match_rule(normalized, rule):
                matched_rules.append(rule.get("pattern", ""))
                for skill in rule.get("skills", []):
                    matched_skills.add(skill)
                auto_skills, _manual_skills = _lookup_skills(agent_name)
                chain = route_map.get("agents", {}).get(agent_name, {}).get("chain", [])
                return {
                    "agent": agent_name,
                    "confidence": 1.0,
                    "method": "auto",
                    "details": {
                        "scores": [],
                        "matched_rules": matched_rules,
                        "fallback_reason": "",
                    },
                    "auto_skills": auto_skills,
                    "manual_skills": sorted(matched_skills),
                    "chain": chain or None,
                }

    # ── 评估 + 决策 ────────────────────────────────────────────
    scored_results = evaluate(user_input, route_map)               # (name, score, matched_rules)
    scores = [(name, score) for name, score, _ in scored_results]  # strip rules for decide()
    result = decide(scores, route_map, user_input)

    # 从 evaluate 结果直接提取 top agent 的匹配规则与技能（无需二次遍历规则列表）
    matched_skills: set[str] = set()
    if scored_results:
        top_rules = scored_results[0][2]  # 已命中的规则 dict 列表
        for rule in top_rules:
            matched_rules.append(rule.get("pattern", ""))
            for skill in rule.get("skills", []):
                matched_skills.add(skill)

    result["details"]["matched_rules"] = matched_rules

    # ── 技能分配：auto 来自 skill-cache，manual 来自规则 skills ──
    target = result.get("agent", "")
    if target:
        auto_skills, _manual_skills = _lookup_skills(target)
        result["auto_skills"] = auto_skills
        result["manual_skills"] = sorted(matched_skills) if matched_skills else []

        # ── 链条提取：从 index.yaml 的 Agent chain 字段 ──
        chain = route_map.get("agents", {}).get(target, {}).get("chain", [])
        if chain:
            result["chain"] = chain

    return result


# ── 日志记录 ───────────────────────────────────────────────────────

_LOG_FILE = os.path.join(_SCRIPT_DIR, "..", "logs", "route-engine.jsonl")
_LOG_MAX_BYTES = 10 * 1024 * 1024   # 10 MB
_LOG_BACKUP_COUNT = 5


def _rotate_log():
    """按文件大小轮转日志，保留 _LOG_BACKUP_COUNT 份备份。"""
    try:
        size = os.path.getsize(_LOG_FILE)
    except OSError:
        return  # 文件不存在，无需轮转
    if size < _LOG_MAX_BYTES:
        return
    # 移除最旧的备份（如 .5 → 删除），然后依次重命名
    last = f"{_LOG_FILE}.{_LOG_BACKUP_COUNT}"
    if os.path.exists(last):
        os.remove(last)
    for i in range(_LOG_BACKUP_COUNT - 1, 0, -1):
        src = f"{_LOG_FILE}.{i}"
        dst = f"{_LOG_FILE}.{i + 1}"
        if os.path.exists(src):
            os.rename(src, dst)
    os.rename(_LOG_FILE, f"{_LOG_FILE}.1")


def log_route(route_result: dict, user_input: str):
    """记录路由日志，JSON Lines 格式，追加写入（自动轮转）"""
    import datetime
    import json

    confidence = route_result.get("confidence", 0)
    method = route_result.get("method", "unknown")

    flagged = False
    flag_reason = None
    if method == "llm_fallback":
        flagged = True
        flag_reason = "low_confidence"
    elif method == "auto_tiebreak":
        flagged = True
        flag_reason = "tiebreak"
    elif method == "auto" and confidence < 0.6:
        flagged = True
        flag_reason = "borderline"

    entry = {
        "ts": datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=8))
        ).isoformat(),
        "input": user_input[:200],
        "agent": route_result.get("agent", ""),
        "confidence": confidence,
        "method": method,
        "matched": route_result.get("details", {}).get("matched_rules", []),
        "flagged": flagged,
        "flag_reason": flag_reason,
    }

    os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
    _rotate_log()
    with open(_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── 命令行入口 ─────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> None:
    """CLI 入口：接收用户输入文本，输出路由结果 JSON"""
    import sys
    import json

    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        print("用法: python route_engine.py <用户输入>")
        sys.exit(1)

    user_input = " ".join(argv)
    result = route(user_input)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

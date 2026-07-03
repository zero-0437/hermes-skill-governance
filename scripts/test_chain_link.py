#!/usr/bin/env python3
"""调用链路测试 — route_engine + chain_executor 全链路"""
import sys
sys.path.insert(0, '/opt/data/scripts')
from chain_executor import advance, start_chain, aggregate_parallel_results
sys.path.insert(0, '/opt/data')
import route_engine as re
re._clear_cache()

passed = 0
failed = 0

def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f'  ✅ {msg}')
    else:
        failed += 1
        print(f'  ❌ {msg}')

# ── 1. route_engine 路由 ──
print('=== 1. route_engine 路由 ===')
for inp, exp, method in [
    ('编码管线', 'programmer', 'chain_keyword'),
    ('双评审', 'dual-review', 'chain_keyword'),
    ('新项目管线', 'spec-agent', 'chain_keyword'),
    ('需求分析管线', 'spec-agent', 'chain_keyword'),
    ('开发管线', 'programmer', 'chain_keyword'),
    ('写一段代码', 'programmer', 'auto'),
]:
    r = re.route(inp)
    check(r['agent'] == exp and r['method'] == method, f'{inp:20s} → {r["agent"]:15s} ({r["method"]})')

print()

# ── 2. chain_executor 链推进 ──
print('=== 2. chain_executor chain 推进 ===')

# 2a. spec-agent-chain (4步)
print('2a. spec-agent-chain (brainstorming→plans→拆解→batch)')
chain_a = [
    {'agent':'spec-agent','goal':'brainstorming','keywords':['brainstorming']},
    {'agent':'pm-agent','goal':'writing-plans','keywords':['writing-plans']},
    {'agent':'pm-agent','goal':'拆解任务','keywords':['decompose']},
    {'agent':'programmer','goal':'批量实现','keywords':['implement'],'batch':True},
]
skills_a = {'spec-agent@0':['brainstorming'],'spec-agent@1':['writing-plans'],
            'spec-agent@2':['architecture-integrity-check'],'spec-agent@3':[]}

r = start_chain('T-SPEC', chain_a, skills_a, 'spec-agent')
check(r['status']=='CONTINUE' and r['next']['agent']=='spec-agent' and r['next']['keywords']==['brainstorming'],
      f'step[0] {r["status"]:20s} agent={r["next"]["agent"]} kw={r["next"]["keywords"]}')

r = advance('T-SPEC', chain_a, skills_a, {'agent':'spec-agent','status':'DONE'})
check(r['status']=='CONTINUE', f'step[1] {r["status"]:20s} agent={r["next"]["agent"]}')

r = advance('T-SPEC', chain_a, skills_a, {'agent':'pm-agent','status':'DONE'})
check(r['status']=='CONTINUE', f'step[2] {r["status"]:20s} agent={r["next"]["agent"]}')

r = advance('T-SPEC', chain_a, skills_a, {'agent':'pm-agent','status':'DONE'})
check(r['status']=='CONTINUE_BATCH', f'step[3] {r["status"]:20s} count={r["batch_count"]}')

r = advance('T-SPEC', chain_a, skills_a, {'agent':'programmer','status':'DONE','batch_complete':True,'batch_results':[{'ok':True}]})
check(r['status']=='DONE', f'done    {r["status"]:20s} steps={r["summary"]["total_steps"]}')

# 2b. programmer-chain (keywords+skills透传)
print('2b. programmer-chain (keywords+skills透传)')
chain_b = [
    {'agent':'programmer','goal':'TDD实现','keywords':['tdd','implement']},
    {'agent':'error-analyst','goal':'spec评审','keywords':['spec-review']},
]
skills_b = {'prog@0':['test-driven-development'],'prog@1':['requesting-code-review','receiving-code-review']}

r = start_chain('T-PROG', chain_b, skills_b, 'prog')
check(r['status']=='CONTINUE' and r['next']['keywords']==['tdd','implement'] and r['next']['skills']==['test-driven-development'],
      f'step[0] {r["status"]:20s} kw={r["next"]["keywords"]} skills={r["next"]["skills"]}')

r = advance('T-PROG', chain_b, skills_b, {'agent':'programmer','status':'DONE'})
check(r['status']=='CONTINUE' and r['next']['skills']==['requesting-code-review','receiving-code-review'],
      f'step[1] {r["status"]:20s} skills={r["next"]["skills"]}')

r = advance('T-PROG', chain_b, skills_b, {'agent':'error-analyst','status':'DONE'})
check(r['status']=='DONE', f'done    {r["status"]:20s}')

# 2c. parallel步骤
print('2c. parallel (CONTINUE_PARALLEL)')
chain_c = [
    {'type':'parallel','branches':[
        {'agent':'error-analyst','goal':'Standards审查','keywords':['standards']},
        {'agent':'programmer','goal':'Spec审查','keywords':['spec-check']},
    ],'join_strategy':'separate'},
    {'agent':'programmer','goal':'收尾','keywords':['finish']},
]
skills_c = {'par@1':['test-driven-development']}

r = start_chain('T-PAR', chain_c, skills_c, 'par')
check(r['status']=='CONTINUE_PARALLEL' and len(r['next'])==2,
      f'step[0] {r["status"]:20s} branches={len(r["next"])}')
check(r['next'][0]['keywords']==['standards'] and r['next'][1]['keywords']==['spec-check'],
      f'       branch keywords: {r["next"][0].get("keywords")} / {r["next"][1].get("keywords")}')

r = advance('T-PAR', chain_c, skills_c, {'agent':'x','status':'DONE','branches_complete':True,'branch_results':[{'ok':True}]})
check(r['status']=='CONTINUE', f'step[1] {r["status"]:20s} → {r["next"]["agent"]}')

r = advance('T-PAR', chain_c, skills_c, {'agent':'programmer','status':'DONE'})
check(r['status']=='DONE', f'done    {r["status"]:20s}')

# 2d. interactive
print('2d. interactive (NEEDS_CONTEXT)')
chain_d = [{'agent':'reality-checker','goal':'验证门控','keywords':['verification'],'type':'interactive'}]
r = start_chain('T-INT', chain_d, {}, 'reality')
check(r['status']=='NEEDS_CONTEXT' and r.get('interactive')==True and r.get('keywords')==['verification'],
      f'step[0] {r["status"]:20s} interactive={r.get("interactive")} kw={r.get("keywords")}')

r = advance('T-INT', chain_d, {}, {'agent':'reality-checker','status':'DONE'})
check(r['status']=='DONE', f'done    {r["status"]:20s}')

# 2e. 聚合
print('2e. 聚合函数')
r = aggregate_parallel_results([
    {'name':'error-analyst','summary':'规范良好','findings':['A']},
    {'name':'programmer','summary':'匹配spec','findings':['B']},
], 'separate')
check(r['status']=='DONE' and list(r['reports'].keys())==['error-analyst','programmer'],
      f'separate   {r["status"]} reports={list(r["reports"].keys())}')

r = aggregate_parallel_results([{'name':'pm-agent','summary':'ok'}], 'synthesize')
check('_warning' in r.get('comparison',{}),
      f'synthesize {r["status"]} has_warning={"_warning" in r.get("comparison",{})}')

print()
print(f'=== 结果: {passed}/{passed+failed} 通过 ({failed} 失败) ===')

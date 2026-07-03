#!/usr/bin/env python3
"""CFNB 定时运行脚本 —— 明早 10:00 由 cron 触发"""
import subprocess
import os

os.environ['SSHPASS'] = 'Hy199098'

# 后台启动 cfnb
cmd = (
    'cd /volume3/docker/cfnb && python3 -c "'
    'import subprocess; '
    "p = subprocess.Popen(['python3', 'main.py'], "
    "stdout=open('/tmp/cfnb_run.log','w'), "
    "stderr=subprocess.STDOUT, "
    "cwd='/volume3/docker/cfnb', "
    "start_new_session=True); "
    "print(f'PID={p.pid}')"
    '"'
)

result = subprocess.run(
    ['python3', '/opt/data/ssh_helper.py', '192.168.1.172', 'zero0437', cmd],
    capture_output=True, text=True, timeout=30
)
print(result.stdout)
if result.returncode != 0:
    print(result.stderr)

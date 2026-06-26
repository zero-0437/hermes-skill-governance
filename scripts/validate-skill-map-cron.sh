#!/bin/bash
# skill-map-validator cron wrapper — 24h 巡检
cd /opt/data
exec ./scripts/validate-skill-map.py 2>&1

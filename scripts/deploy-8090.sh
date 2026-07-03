#!/bin/sh
# 8090 部署脚本 — 内置权限检查、schema校验、环境兼容
# Rule #4: NAS deployment template
set -e

PROJECT_DIR="/volume1/8090"

# 0. 加载环境变量（用 . 代替 source，兼容 POSIX sh）
if [ -f "$PROJECT_DIR/.env" ]; then
    . "$PROJECT_DIR/.env" && set -a
fi

# 1. 权限检查
echo "[deploy-8090] Checking permissions..."
if [ ! -d "$PROJECT_DIR" ]; then
    echo "ERROR: $PROJECT_DIR does not exist" >&2
    exit 1
fi
if [ ! -w "$PROJECT_DIR" ]; then
    echo "ERROR: $PROJECT_DIR is not writable" >&2
    exit 1
fi

# 2. schema 校验（Rule #6: SQLite PRAGMA table_info）
echo "[deploy-8090] Running schema validation..."
DB_PATH="$PROJECT_DIR/data/messages.db"
if [ -f "$DB_PATH" ]; then
    echo "PRAGMA table_info(sessions);" | sqlite3 "$DB_PATH" | grep -q 'last_active' || {
        echo "[deploy-8090] Adding last_active column to sessions..."
        echo "ALTER TABLE sessions ADD COLUMN last_active TEXT;" | sqlite3 "$DB_PATH"
        echo "[deploy-8090] Schema migration complete."
    }
else
    echo "[deploy-8090] WARNING: $DB_PATH not found, skipping schema check."
fi

# 3. 文件同步
echo "[deploy-8090] Syncing files..."
# TODO: 在此处添加 rsync / scp / docker cp 等同步逻辑

# 4. 重启容器
echo "[deploy-8090] Restarting container..."
# TODO: 在此处添加 docker restart 8090 或 docker-compose 逻辑

echo "[deploy-8090] Deployment complete."

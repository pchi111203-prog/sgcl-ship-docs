#!/usr/bin/env bash
# Khởi chạy SGCL: build giao diện (nếu chưa có) rồi chạy server tại http://localhost:8000
set -e
cd "$(dirname "$0")"
if [ ! -d frontend/dist ]; then (cd frontend && npm install && npm run build); fi
cd backend
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"

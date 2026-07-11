# AI 资产配置投委会 · 一键启动
# make dev      同时启动后端(8000)与前端(5173)
# make backend  只启动后端 API
# make frontend 只启动前端
# make data     重新生成 Demo 数据（确定性，固定种子）
# make test     后端测试
# make e2e      Playwright 交互测试（需先 make dev）
# make build    构建前端产物（backend 同端口托管）

.PHONY: dev backend frontend data test e2e build install

install:
	cd backend && uv sync
	cd frontend && npm install

data:
	uv run --project backend python scripts/generate_demo_data.py

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

dev:
	@trap 'kill 0' INT TERM; \
	(cd backend && uv run uvicorn app.main:app --port 8000) & \
	(cd frontend && npm run dev) & \
	wait

test:
	cd backend && uv run pytest ../tests/backend -q

e2e:
	cd frontend && npx playwright test

build:
	cd frontend && npm run build

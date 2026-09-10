# ARIADNE — developer entry points
PY      ?= python3
API_DIR := apps/api
WEB_DIR := apps/web
MCP_DIR := apps/mcp-server

.PHONY: install seed dev api web mcp test test-api test-web test-mcp eval build clean

install:            ## install python + node dependencies
	pip install "fastapi>=0.110" "uvicorn[standard]>=0.27" "sqlalchemy>=2.0" "alembic>=1.13" \
	            "pydantic>=2.6" "pydantic-settings>=2.1" "httpx>=0.27" "numpy>=1.26" "pillow>=10.0" \
	            "opencv-python-headless>=4.9" "pypdf>=4.0" "reportlab>=4.0" "python-multipart>=0.0.9" pytest
	cd $(WEB_DIR) && npm install
	cd $(MCP_DIR) && npm install

seed:               ## generate dataset + seed database + benchmark
	$(PY) scripts/generate_drawings.py
	$(PY) scripts/generate_documents.py
	$(PY) scripts/seed.py

dev:                ## api + mcp + web concurrently (foreground: api)
	@echo "→ start MCP:  make mcp   (second terminal)"
	@echo "→ start web:  make web   (third terminal)"
	cd $(API_DIR) && $(PY) -m uvicorn app.main:app --reload --port 8000

api:
	cd $(API_DIR) && $(PY) -m uvicorn app.main:app --reload --port 8000

web:
	cd $(WEB_DIR) && npm run dev

mcp:
	cd $(MCP_DIR) && npm run dev

test: test-api test-web test-mcp

test-api:
	cd $(API_DIR) && $(PY) -m pytest -q

test-web:
	cd $(WEB_DIR) && npx vitest run

test-mcp:
	cd $(MCP_DIR) && npx vitest run

eval:               ## run the evaluation suite and print the report path
	cd $(API_DIR) && $(PY) -c "import sys;sys.path.insert(0,'.');sys.path.insert(0,'../../packages/evaluation');from app.services.evaluation_service import run_evaluation;import json;r=run_evaluation('make');print(json.dumps({k:v for k,v in r['sections'].items()},indent=1,default=str)[:2000])"

build:
	cd $(WEB_DIR) && npm run build
	cd $(MCP_DIR) && npm run build

clean:
	rm -f data/ariadne.db data/test_ariadne.db
	rm -rf apps/web/dist apps/mcp-server/dist

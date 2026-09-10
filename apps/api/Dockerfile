# ARIADNE API — python 3.11, OpenCV headless
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ARIADNE_FONT_DIR=/usr/share/fonts/truetype/dejavu

WORKDIR /srv/ariadne
RUN apt-get update && apt-get install -y --no-install-recommends \
      libglib2.0-0 libgl1 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/pyproject.toml apps/api/pyproject.toml
RUN pip install --upgrade pip && pip install "fastapi>=0.110" "uvicorn[standard]>=0.27" "sqlalchemy>=2.0" \
      "alembic>=1.13" "pydantic>=2.6" "pydantic-settings>=2.1" "httpx>=0.27" "numpy>=1.26" "pillow>=10.0" \
      "opencv-python-headless>=4.9" "pypdf>=4.0" "reportlab>=4.0" "python-multipart>=0.0.9" "psycopg[binary]>=3.1" \
      "pgvector>=0.2" "mcp>=1.2"

COPY apps/api apps/api
COPY packages/evaluation packages/evaluation
COPY scripts scripts
COPY data data

WORKDIR /srv/ariadne/apps/api
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

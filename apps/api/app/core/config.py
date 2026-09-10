"""Environment-driven configuration.

Every provider in ARIADNE is selected from these settings; nothing is hard-coded
to a vendor.  ``DEMO_MODE`` makes the whole stack deterministic and offline.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = REPO_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", os.path.join(os.getcwd(), ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- runtime -----------------------------------------------------------
    ariadne_env: str = "development"
    demo_mode: bool = Field(default=True)
    log_level: str = "INFO"
    service_name: str = "ariadne-api"

    # ---- api ---------------------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_cors_origins: str = ("http://localhost:5173,http://localhost:4173,"
                       "http://127.0.0.1:5173,http://127.0.0.1:4173")

    # ---- database ----------------------------------------------------------
    database_url: str = f"sqlite:///{DATA_DIR / 'ariadne.db'}"

    # ---- vector store ------------------------------------------------------
    vector_store: Literal["auto", "pgvector", "numpy"] = "auto"
    embedding_dim: int = 384

    # ---- graph -------------------------------------------------------------
    graph_store: Literal["auto", "sql", "neo4j"] = "auto"
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = "ariadne"
    graph_max_depth: int = 4
    graph_default_depth: int = 2

    # ---- llm ---------------------------------------------------------------
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2

    # ---- embeddings --------------------------------------------------------
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "BAAI/bge-m3"
    embedding_local_enabled: bool = True
    embedding_allow_download: bool = True

    # ---- vision ------------------------------------------------------------
    vision_base_url: str = ""
    vision_api_key: str = ""
    vision_model: str = "Qwen/Qwen2.5-VL-7B-Instruct"
    vision_enabled: bool = False

    # ---- mcp ---------------------------------------------------------------
    mcp_enabled: bool = True
    mcp_transport: str = "streamable-http"
    mcp_server_url: str = "http://localhost:8765/mcp"
    mcp_api_base_url: str = "http://localhost:8000"

    # ---- rag tuning --------------------------------------------------------
    rag_top_k: int = 8
    rag_rerank_top_n: int = 5
    rag_min_score: float = 0.05
    rag_revision_aware: bool = True

    # ---- security ----------------------------------------------------------
    auth_enabled: bool = True
    default_user_id: str = "u_engineer_1"
    secret_key: str = "change-me-in-production"

    # ---- paths -------------------------------------------------------------
    data_dir: Path = DATA_DIR
    drawings_dir: Path = DATA_DIR / "drawings"
    documents_dir: Path = DATA_DIR / "documents"
    reports_dir: Path = DATA_DIR / "reports"
    vector_dir: Path = DATA_DIR / "vector_store"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def llm_configured(self) -> bool:
        """True when a real LLM endpoint is reachable-by-config."""
        return bool(self.llm_api_key) and not self.demo_mode

    @property
    def embeddings_configured(self) -> bool:
        return bool(self.embedding_api_key or self.llm_api_key) and not self.demo_mode

    @property
    def effective_vector_store(self) -> str:
        if self.vector_store != "auto":
            return self.vector_store
        return "numpy" if self.is_sqlite else "pgvector"

    @property
    def effective_graph_store(self) -> str:
        if self.graph_store != "auto":
            return self.graph_store
        return "neo4j" if self.neo4j_uri else "sql"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    for p in (s.data_dir, s.drawings_dir, s.documents_dir, s.reports_dir, s.vector_dir):
        p.mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()

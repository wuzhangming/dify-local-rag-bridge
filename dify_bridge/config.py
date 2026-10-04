from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    data_dir: Path = PROJECT_DIR / "data"
    qdrant_url: str = "http://127.0.0.1:6333"
    embedding_url: str = "http://127.0.0.1:8003/v1/embeddings"
    embedding_model: str = "Qwen3-VL-Embedding-2B-8bit"
    existing_collection: str = "obsidian_vl2b_2048"
    uploads_collection: str = "dify_uploads_vl2b_2048"
    max_upload_bytes: int = 25 * 1024 * 1024
    embedding_batch_size: int = 16
    auth_token: str | None = None

    @classmethod
    def from_environment(cls) -> "Settings":
        data_dir = Path(os.environ.get("DIFY_BRIDGE_DATA_DIR", PROJECT_DIR / "data"))
        token = (os.environ.get("BRIDGE_API_KEY") or os.environ.get("DIFY_BRIDGE_TOKEN")
                 or _token_from_file(data_dir / "auth.token"))
        return cls(
            data_dir=data_dir,
            qdrant_url=os.environ.get("DIFY_BRIDGE_QDRANT_URL", "http://127.0.0.1:6333"),
            embedding_url=os.environ.get("DIFY_BRIDGE_EMBEDDING_URL", "http://127.0.0.1:8003/v1/embeddings"),
            auth_token=token,
        )


def _token_from_file(path: Path) -> str | None:
    """Read a local secret only when it is private to its owner."""
    if not path.is_file():
        return None
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise RuntimeError(f"refusing insecure token file permissions: {path}")
    token = path.read_text(encoding="utf-8").strip()
    return token or None

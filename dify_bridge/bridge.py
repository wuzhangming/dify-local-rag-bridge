from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import httpx
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from .config import Settings
from .text import chunks_for_text

ALLOWED_EXTENSIONS = {".md", ".txt", ".pdf", ".png", ".jpg", ".jpeg", ".heic"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".heic"}


class BridgeError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class Bridge:
    def __init__(self, settings: Settings, qdrant: Any | None = None, http: Any | None = None):
        self.settings = settings
        self.qdrant = qdrant or QdrantClient(url=settings.qdrant_url, timeout=20)
        self.http = http or httpx.Client(timeout=40)

    def health(self) -> dict[str, str]:
        return {"status": "ok"}

    def retrieve(self, query: str, knowledge_id: str, top_k: int, score_threshold: float = 0.0) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            raise BridgeError("query is required", 422)
        collections = {
            "local_existing": [self.settings.existing_collection],
            "local_uploads": [self.settings.uploads_collection],
            "local_all": [self.settings.existing_collection, self.settings.uploads_collection],
        }.get(knowledge_id)
        if collections is None:
            raise BridgeError("knowledge_id must be local_existing, local_uploads, or local_all", 422)
        vector = self.embed([query.strip()])[0]
        records: list[dict[str, Any]] = []
        completed_uploads = self._completed_document_ids() if self.settings.uploads_collection in collections else set()
        for collection in collections:
            try:
                exists = self.qdrant.collection_exists(collection)
            except Exception as exc:
                raise BridgeError("Qdrant is unavailable") from exc
            if not exists:
                if collection == self.settings.uploads_collection:
                    continue
                raise BridgeError(f"required knowledge collection is unavailable: {collection}")
            if collection == self.settings.uploads_collection and not completed_uploads:
                continue
            try:
                query_filter = None
                if collection == self.settings.uploads_collection:
                    query_filter = qm.Filter(must=[qm.FieldCondition(
                        key="document_id", match=qm.MatchAny(any=list(completed_uploads)),
                    )])
                response = self.qdrant.query_points(
                    collection_name=collection, query=vector, limit=top_k,
                    query_filter=query_filter, with_payload=True, with_vectors=False,
                )
                points = response.points
            except Exception as exc:
                raise BridgeError(f"search failed for {collection}") from exc
            records.extend(
                self._record(point, collection)
                for point in points
                if collection != self.settings.uploads_collection
                or str((point.payload or {}).get("document_id", "")) in completed_uploads
            )
        records.sort(key=lambda item: item["score"], reverse=True)
        return [record for record in records if record["score"] >= score_threshold][:top_k]

    def ingest(self, filename: str, raw: bytes) -> dict[str, Any]:
        filename = _safe_filename(filename)
        if not raw:
            raise BridgeError("upload is empty", 422)
        if len(raw) > self.settings.max_upload_bytes:
            raise BridgeError("upload exceeds 25 MB limit", 413)
        extension = Path(filename).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise BridgeError("only Markdown, TXT, text-extractable PDF, PNG, JPG, JPEG, and HEIC are accepted", 415)
        _validate_content(extension, raw)
        document_id = hashlib.sha256(filename.encode("utf-8") + b"\0" + raw).hexdigest()
        state = self._load_state(document_id)
        if state and state.get("status") == "completed" and self._completed_state_is_valid(state):
            return self._result(state, reused=True)
        self._save_original(document_id, filename, raw)
        text = self._extract(extension, raw, filename)
        chunks = chunks_for_text(text, markdown=extension == ".md")
        if not chunks:
            raise BridgeError("no usable text was found in this file", 422)
        point_ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"dify-upload:{document_id}:{index}")) for index in range(len(chunks))]
        state = {
            "document_id": document_id, "filename": filename, "status": "pending",
            "expected_point_ids": point_ids, "chunk_hashes": [hashlib.sha256(body.encode("utf-8")).hexdigest() for _, body in chunks],
            "chunks": len(chunks), "source": f"uploads/{document_id}/{filename}",
        }
        self._save_state(state)
        vectors = self.embed([body for _, body in chunks])
        self._ensure_upload_collection()
        points = []
        for index, ((section, body), vector, point_id) in enumerate(zip(chunks, vectors, point_ids)):
            points.append(qm.PointStruct(
                id=point_id, vector=vector,
                payload={
                    "root": "dify_uploads", "relative_path": state["source"], "file_name": filename,
                    "doc_type": extension.lstrip("."), "chunk_index": index, "section": section,
                    "text": body, "char_len": len(body), "document_id": document_id,
                },
            ))
        try:
            for batch in _batches(points, 64):
                self.qdrant.upsert(self.settings.uploads_collection, points=batch, wait=True)
            verified = self._verify_uploaded_points(state)
        except Exception as exc:
            raise BridgeError("upload indexing failed; retrying the same file is safe") from exc
        if not verified:
            raise BridgeError("upload indexing could not be verified; retry the same file")
        state["status"] = "completed"
        self._save_state(state)
        return self._result(state, reused=False)

    def embed(self, texts: list[str]) -> list[list[float]]:
        all_vectors: list[list[float]] = []
        for batch in _batches(texts, self.settings.embedding_batch_size):
            try:
                response = self.http.post(self.settings.embedding_url, json={
                    "model": self.settings.embedding_model, "input": batch,
                })
                response.raise_for_status()
                data = response.json().get("data")
                vectors = [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]
            except Exception as exc:
                raise BridgeError("embedding service is unavailable") from exc
            if len(vectors) != len(batch) or any(not isinstance(v, list) or len(v) != 2048 for v in vectors):
                raise BridgeError("embedding service returned an invalid vector")
            all_vectors.extend([[float(value) for value in vector] for vector in vectors])
        return all_vectors

    def _record(self, point: Any, collection: str) -> dict[str, Any]:
        payload = dict(point.payload or {})
        raw_score = float(point.score)
        # Dify accepts a 0..1 ranking score. Qdrant cosine spans -1..1, so negative
        # values are clipped. It remains a retrieval score, never a probability.
        score = min(1.0, max(0.0, raw_score))
        metadata = {
            "collection": collection, "root": str(payload.get("root", "")),
            "relative_path": str(payload.get("relative_path", "")),
            "section": str(payload.get("section", "")), "chunk_id": str(point.id),
            "chunk_index": payload.get("chunk_index"), "document_id": payload.get("document_id"),
            "score_type": "clipped_qdrant_cosine_similarity", "raw_score": raw_score,
        }
        return {
            "content": str(payload.get("text", "")), "score": score,
            "title": str(payload.get("file_name") or payload.get("relative_path") or "local document"),
            "metadata": metadata,
        }

    def _extract(self, extension: str, raw: bytes, filename: str) -> str:
        if extension in {".md", ".txt"}:
            try:
                return raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise BridgeError("text files must be UTF-8 encoded", 422) from exc
        if extension == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError as exc:
                raise BridgeError("PDF support is not installed; install pypdf in the bridge virtual environment", 503) from exc
            try:
                import io
                text = "\n\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(raw)).pages)
            except Exception as exc:
                raise BridgeError("PDF text extraction failed", 422) from exc
            if not text.strip():
                raise BridgeError("this PDF contains no extractable text; scanned PDFs need OCR before upload", 422)
            return text
        return self._ocr(raw, extension, filename)

    def _ocr(self, raw: bytes, extension: str, filename: str) -> str:
        source = Path(__file__).with_name("ocr.swift")
        bin_dir = self.settings.data_dir / "bin"
        binary = bin_dir / "vision-ocr"
        bin_dir.mkdir(parents=True, exist_ok=True)
        try:
            if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
                subprocess.run(["/usr/bin/swiftc", str(source), "-o", str(binary)], check=True, capture_output=True, timeout=60)
            with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as handle:
                handle.write(raw)
                image_path = handle.name
            try:
                result = subprocess.run([str(binary), image_path], check=True, capture_output=True, text=True, timeout=45)
            finally:
                os.unlink(image_path)
        except (OSError, subprocess.SubprocessError) as exc:
            raise BridgeError("local macOS Vision OCR failed") from exc
        if not result.stdout.strip():
            raise BridgeError("OCR found no text in this image", 422)
        return result.stdout

    def _ensure_upload_collection(self) -> None:
        try:
            if not self.qdrant.collection_exists(self.settings.uploads_collection):
                self.qdrant.create_collection(
                    collection_name=self.settings.uploads_collection,
                    vectors_config=qm.VectorParams(size=2048, distance=qm.Distance.COSINE),
                )
        except Exception as exc:
            raise BridgeError("could not create upload knowledge collection") from exc

    def _verify_uploaded_points(self, state: dict[str, Any]) -> bool:
        """Verify IDs, document fields, text hashes, and 2048-D vectors before publish."""
        ids = state.get("expected_point_ids", [])
        hashes = state.get("chunk_hashes", [])
        if len(ids) != state.get("chunks") or len(hashes) != len(ids):
            return False
        try:
            records = self.qdrant.retrieve(
                self.settings.uploads_collection, ids=ids, with_payload=True, with_vectors=True,
            )
        except Exception:
            return False
        by_id = {str(record.id): record for record in records}
        if set(by_id) != set(ids):
            return False
        for index, point_id in enumerate(ids):
            record = by_id[point_id]
            payload = dict(record.payload or {})
            vector = record.vector
            if isinstance(vector, dict):
                return False
            if (
                payload.get("document_id") != state["document_id"]
                or payload.get("chunk_index") != index
                or not isinstance(payload.get("text"), str)
                or hashlib.sha256(payload["text"].encode("utf-8")).hexdigest() != hashes[index]
                or not isinstance(vector, list) or len(vector) != 2048
            ):
                return False
        return True

    def _completed_state_is_valid(self, state: dict[str, Any]) -> bool:
        try:
            return self._verify_uploaded_points(state)
        except Exception:
            return False

    def _completed_document_ids(self) -> set[str]:
        directory = self.settings.data_dir / "state"
        if not directory.exists():
            return set()
        completed: set[str] = set()
        for path in directory.glob("*.json"):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                if (
                    state.get("status") == "completed"
                    and isinstance(state.get("document_id"), str)
                    and self._completed_state_is_valid(state)
                ):
                    completed.add(state["document_id"])
            except (OSError, ValueError, TypeError):
                continue
        return completed

    def _state_path(self, document_id: str) -> Path:
        return self.settings.data_dir / "state" / f"{document_id}.json"

    def _load_state(self, document_id: str) -> dict[str, Any] | None:
        path = self._state_path(document_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_state(self, state: dict[str, Any]) -> None:
        path = self._state_path(state["document_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(path, state)

    def _save_original(self, document_id: str, filename: str, raw: bytes) -> None:
        path = self.settings.data_dir / "originals" / document_id / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(raw)

    @staticmethod
    def _result(state: dict[str, Any], reused: bool) -> dict[str, Any]:
        return {"document_id": state["document_id"], "chunks": state["chunks"], "status": state["status"], "source": state["source"], "reused": reused}


def _safe_filename(value: str) -> str:
    filename = Path(value or "").name
    if not filename or filename in {".", ".."} or len(filename) > 255:
        raise BridgeError("a valid filename is required", 422)
    return filename


def _validate_content(extension: str, raw: bytes) -> None:
    magic = {
        ".pdf": b"%PDF-", ".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff",
    }
    if extension in magic and not raw.startswith(magic[extension]):
        raise BridgeError("file content does not match its filename extension", 415)
    if extension == ".heic" and b"ftyp" not in raw[:32]:
        raise BridgeError("file content does not match HEIC", 415)
    if extension in {".md", ".txt"}:
        try:
            raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise BridgeError("text files must be UTF-8 encoded", 422) from exc


def _batches(values: list[Any], size: int):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)

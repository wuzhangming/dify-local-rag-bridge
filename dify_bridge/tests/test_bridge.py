from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from dify_bridge.bridge import Bridge, BridgeError
from dify_bridge.config import Settings
from dify_bridge.server import create_app


class FakeResponse:
    def __init__(self, values):
        self.values = values

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": [{"index": index, "embedding": value} for index, value in enumerate(self.values)]}


class FakeHttp:
    def __init__(self, fail=False):
        self.fail = fail

    def post(self, *_args, **kwargs):
        if self.fail:
            raise OSError("offline")
        return FakeResponse([[0.01] * 2048 for _ in kwargs["json"]["input"]])


class FakeQdrant:
    def __init__(self, existing=True):
        self.collections = {"obsidian_vl2b_2048"} if existing else set()
        self.points = {}
        self.fail_upsert = False

    def collection_exists(self, name):
        return name in self.collections

    def create_collection(self, collection_name, **_kwargs):
        self.collections.add(collection_name)

    def upsert(self, collection_name, points, **_kwargs):
        if self.fail_upsert:
            raise OSError("broken qdrant")
        self.points.setdefault(collection_name, {}).update({str(p.id): p for p in points})

    def retrieve(self, collection_name, ids, **_kwargs):
        return [SimpleNamespace(id=identifier, payload=self.points[collection_name][identifier].payload,
                                vector=self.points[collection_name][identifier].vector)
                for identifier in ids if identifier in self.points.get(collection_name, {})]

    def query_points(self, collection_name, **_kwargs):
        points = []
        for point in self.points.get(collection_name, {}).values():
            points.append(SimpleNamespace(id=point.id, payload=point.payload, score=0.76))
        return SimpleNamespace(points=points)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.temp.name), auth_token="test-token")
        self.qdrant = FakeQdrant()
        self.bridge = Bridge(self.settings, self.qdrant, FakeHttp())

    def tearDown(self):
        self.temp.cleanup()

    def test_ingest_is_idempotent_and_preserves_source_metadata(self):
        source = b"# Title\n\n" + ("This is useful local knowledge. " * 8).encode()
        first = self.bridge.ingest("guide.md", source)
        second = self.bridge.ingest("guide.md", source)
        self.assertEqual(first["status"], "completed")
        self.assertTrue(second["reused"])
        result = self.bridge.retrieve("find knowledge", "local_uploads", 5)
        self.assertEqual(result[0]["metadata"]["root"], "dify_uploads")
        self.assertEqual(result[0]["metadata"]["relative_path"], first["source"])
        self.assertEqual(result[0]["metadata"]["score_type"], "clipped_qdrant_cosine_similarity")

    def test_failed_upload_remains_pending_and_can_resume(self):
        self.qdrant.fail_upsert = True
        source = ("retry content " * 20).encode()
        with self.assertRaisesRegex(BridgeError, "retrying the same file"):
            self.bridge.ingest("retry.txt", source)
        self.qdrant.fail_upsert = False
        result = self.bridge.ingest("retry.txt", source)
        self.assertEqual(result["status"], "completed")

    def test_pending_partial_upload_is_not_retrievable(self):
        source = ("incomplete content " * 100).encode()
        original_upsert = self.qdrant.upsert

        def partial_upsert(collection_name, points, **kwargs):
            original_upsert(collection_name, points[:1], **kwargs)
            raise OSError("interrupted")

        self.qdrant.upsert = partial_upsert
        with self.assertRaises(BridgeError):
            self.bridge.ingest("interrupted.txt", source)
        results = self.bridge.retrieve("incomplete", "local_uploads", 5)
        self.assertEqual(results, [])

    def test_completed_upload_is_repaired_when_qdrant_loses_a_point(self):
        source = ("repair content " * 100).encode()
        first = self.bridge.ingest("repair.txt", source)
        point_id = next(iter(self.qdrant.points[self.settings.uploads_collection]))
        self.qdrant.points[self.settings.uploads_collection].pop(point_id)
        repaired = self.bridge.ingest("repair.txt", source)
        self.assertFalse(repaired["reused"])
        self.assertEqual(repaired["status"], "completed")

    def test_score_threshold_filters_clipped_qdrant_scores(self):
        self.bridge.ingest("scored.txt", ("score content " * 20).encode())
        self.assertEqual(self.bridge.retrieve("score", "local_uploads", 5, 0.8), [])
        result = self.bridge.retrieve("score", "local_uploads", 5, 0.7)
        self.assertEqual(result[0]["score"], 0.76)
        self.assertEqual(result[0]["metadata"]["raw_score"], 0.76)

    def test_rejects_size_format_and_empty_input(self):
        with self.assertRaisesRegex(BridgeError, "empty"):
            self.bridge.ingest("empty.txt", b"")
        with self.assertRaisesRegex(BridgeError, "only Markdown"):
            self.bridge.ingest("nope.docx", b"text")
        too_large = b"x" * (self.settings.max_upload_bytes + 1)
        with self.assertRaisesRegex(BridgeError, "25 MB"):
            self.bridge.ingest("large.txt", too_large)

    def test_retrieval_errors_when_required_old_collection_is_missing(self):
        bridge = Bridge(self.settings, FakeQdrant(existing=False), FakeHttp())
        with self.assertRaisesRegex(BridgeError, "required knowledge collection"):
            bridge.retrieve("hello", "local_existing", 5)

    def test_embedding_failure_is_not_treated_as_empty_result(self):
        bridge = Bridge(self.settings, self.qdrant, FakeHttp(fail=True))
        with self.assertRaisesRegex(BridgeError, "embedding service"):
            bridge.retrieve("hello", "local_existing", 5)

    def test_auth_and_bad_top_k(self):
        client = TestClient(create_app(self.settings, self.bridge))
        self.assertEqual(client.get("/health").status_code, 401)
        self.assertEqual(client.get("/health", headers={"Authorization": "Bearer test-token"}).status_code, 200)
        response = client.post("/retrieval", headers={"Authorization": "Bearer test-token"}, json={
            "knowledge_id": "local_all", "query": "x", "retrieval_setting": {"top_k": 99},
        })
        self.assertEqual(response.status_code, 422)
        response = client.post("/retrieval", headers={
            "Authorization": "Bearer test-token", "Content-Type": "application/json",
        }, content='{"knowledge_id":"local_all","query":"x","retrieval_setting":{"score_threshold":NaN}}')
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

import mlx.core as mx
from mlx_embeddings import load

MODEL_PATH = os.environ.get("EMBEDDING_MODEL_PATH")
MODEL_ID = "Qwen3-VL-Embedding-2B-8bit"
HOST = "127.0.0.1"
PORT = 8003

if not MODEL_PATH:
    raise RuntimeError(
        "EMBEDDING_MODEL_PATH is required and must point to the local "
        "Qwen3-VL-Embedding-2B-8bit model directory"
    )

print(f"Loading {MODEL_ID} from {MODEL_PATH} ...")
model, processor = load(MODEL_PATH)
print("Model loaded.")


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            self.send_json(200, {
                "object": "list",
                "data": [{
                    "id": MODEL_ID,
                    "object": "model",
                    "created": 0,
                    "owned_by": "local"
                }]
            })
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/embeddings":
            self.send_json(404, {"error": "not found"})
            return

        try:
            size = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(size))
            requested_model = request.get("model")
            if requested_model and requested_model != MODEL_ID:
                self.send_json(400, {"error": f"model must be {MODEL_ID}"})
                return

            raw_input = request.get("input")
            texts = [raw_input] if isinstance(raw_input, str) else raw_input
            if not isinstance(texts, list) or not texts:
                self.send_json(400, {"error": "input must be a string or non-empty string list"})
                return
            if not all(isinstance(text, str) for text in texts):
                self.send_json(400, {"error": "all input items must be strings"})
                return

            items = [{"text": text} for text in texts]
            vectors = model.embed(items, processor)
            mx.eval(vectors)
            vectors = vectors.tolist()

            if any(len(vector) != 2048 for vector in vectors):
                self.send_json(500, {"error": "model returned a vector that is not 2048-dimensional"})
                return

            self.send_json(200, {
                "object": "list",
                "model": MODEL_ID,
                "data": [
                    {
                        "object": "embedding",
                        "index": index,
                        "embedding": [float(value) for value in vector]
                    }
                    for index, vector in enumerate(vectors)
                ]
            })
        except Exception as exc:
            self.send_json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def log_message(self, format, *args):
        print(format % args)


print(f"Listening on http://{HOST}:{PORT}")
HTTPServer((HOST, PORT), Handler).serve_forever()

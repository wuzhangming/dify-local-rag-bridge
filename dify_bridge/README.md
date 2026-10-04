# Dify 本地知识库适配服务

这个服务把本地 Qdrant 知识库以 Dify 外部知识库 API 的检索格式暴露出来，并把 Dify 上传的文件存入独立的 `dify_uploads_vl2b_2048` collection。公开工作流使用 `local_uploads`，只检索由本服务长期入库的资料。

## 安装位置和数据位置

服务代码位于本项目的 `dify_bridge/`。默认上传原件、入库状态和编译后的 OCR 工具位于 `dify_bridge/data/`；可以通过 `DIFY_BRIDGE_DATA_DIR` 移到外置硬盘。例如：

```zsh
export DIFY_BRIDGE_DATA_DIR='/Volumes/YourExternalDisk/dify-bridge-data'
```

要使用文件型密钥，创建 `${DIFY_BRIDGE_DATA_DIR}/auth.token`，写入一行随机 token，然后执行 `chmod 600`。也可以在启动时通过 `BRIDGE_API_KEY`（兼容 `DIFY_BRIDGE_TOKEN`）提供 token。没有 token 时所有接口都会拒绝访问。

## 运行

手动安装依赖时：

```zsh
.venv/bin/python -m pip install -r dify_bridge/requirements.txt
```

启动前，确保 `serve_vl_embedding.py` 已在 `127.0.0.1:8003` 运行，Qdrant 在 `127.0.0.1:6333` 运行。

```zsh
# 默认读取 data/auth.token；不要把真实令牌写进命令历史。
.venv/bin/python -m uvicorn dify_bridge.server:app --host 127.0.0.1 --port 8004
```

Dify 在 Docker Desktop 内访问宿主机时，外部知识库 API 的基础 URL 配置为 `http://host.docker.internal:8004`（不附加 `/retrieval`）。Authorization Header 配置为 `Bearer <同一个 token>`。

## API

所有接口需要 `Authorization: Bearer <token>`，且不会返回密钥。

`GET /health` 只返回 `{ "status": "ok" }`。

`POST /retrieval` 的请求格式：

```json
{"knowledge_id":"local_uploads","query":"问题", "retrieval_setting":{"top_k":5}}
```

`knowledge_id` 只能是：

- `local_existing`：只读已有 `obsidian_vl2b_2048`。
- `local_uploads`：只检索 Dify 上传内容。
- `local_all`：合并两个库后按 Qdrant cosine similarity 排序。

`retrieval_setting` 可选 `score_threshold`，必须是有限的 0 到 1 数字。响应 `records` 的每条内容含 `content`、Dify 的 0 到 1 `score`、`title` 和 `metadata`。Qdrant cosine 原始范围是 -1 到 1；服务把负值截到 0、正值保持不变，并将未变换的数值保存为 `metadata.raw_score`。`metadata.score_type` 明确该分数是排序相似度，不是答案正确率或概率，并带有 `root`、`relative_path`、`section`、`chunk_id` 等来源字段。

`POST /ingest?filename=example.md` 接收原始 binary body。也可使用 `X-Filename` header，或 multipart 的 `file` 字段。支持 UTF-8 Markdown/TXT、含可提取文字的 PDF，及 PNG/JPG/JPEG/HEIC 图片；图片只在 macOS 上通过本机 Vision OCR 提取文字。单文件上限 25 MB；扫描 PDF 会返回提示，要求先 OCR。

相同“文件名 + 内容”会安全复用同一 document ID；同名不同内容会保留为不同版本，不会删除旧内容。服务持久化期望的 Qdrant point IDs 和文本哈希，在任一批次失败时将状态保留为 pending；重新提交同一文件会继续 upsert，并核对所有 point ID、正文哈希、chunk 序号和 2048 维向量后才标记 completed。`local_uploads` 只检索此类已验收 manifest 中的文档，半入库内容不会被检索。

## 限制

- 只支持文本抽取 PDF；不对扫描 PDF 做 OCR。
- 图片 OCR 使用 macOS `/usr/bin/swiftc` 编译的 Vision 程序，首次图片上传较慢。
- 服务不提供删除 API；避免误删知识库内容。
- 不应将 8004 暴露到公网；即使已启用 Bearer token，也建议只在本机或受控局域网使用。

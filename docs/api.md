# Bridge API

所有接口都要求 `Authorization: Bearer <token>`，不会返回令牌。

下面curl中的`YOUR_TOKEN`仅用于展示协议，不是可直接执行的凭据。不要把真实令牌写进命令历史；Dify中通过秘密变量和认证表单配置。需要本机测试时，可用Python从自己的私密文件读入内存，再构造请求，避免打印令牌。

## 健康检查

```zsh
curl -H 'Authorization: Bearer YOUR_TOKEN' http://127.0.0.1:8004/health
```

成功结果是：

```json
{"status":"ok"}
```

## 检索

Dify 外部知识库连接使用基础 URL `http://host.docker.internal:8004`，并调用检索接口。直接在宿主机测试时：

```zsh
curl -X POST http://127.0.0.1:8004/retrieval \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"knowledge_id":"local_uploads","query":"紫藤项目负责人","retrieval_setting":{"top_k":5,"score_threshold":0}}'
```

| 字段 | 说明 |
| --- | --- |
| `knowledge_id` | `local_uploads`、`local_existing`、`local_all` 之一。公开模板使用 `local_uploads`。 |
| `query` | 非空问题。 |
| `retrieval_setting.top_k` | 1–20 的整数，默认 5。 |
| `retrieval_setting.score_threshold` | 0–1 的有限数字，默认 0。 |

每条 `records` 包含 `content`、`title`、`score` 和 `metadata`。`score` 是经过负值截断的 Qdrant cosine 排序分数，不是正确率；原始值在 `metadata.raw_score`。

`local_existing` 需要名为 `obsidian_vl2b_2048` 的兼容 collection，缺失时会报错。`local_all` 合并它与上传 collection。公开工作流不依赖这两种模式。

## 入库

```zsh
curl -X POST 'http://127.0.0.1:8004/ingest?filename=notes.txt' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @examples/Dify界面上传验收.txt
```

也可使用 `X-Filename` 或 multipart 的 `file` 字段。可接受 UTF-8 MD/TXT、可提取文字的 PDF，以及 PNG/JPG/JPEG/HEIC 图片，单文件上限 25 MB。

成功响应含 `document_id`、`filename`、`status: completed`、`chunks`、`source` 和 `reused`。相同“文件名 + 内容”安全复用；同名不同内容会成为独立版本。失败文件保持 pending，重试相同内容是安全的；只有 completed 文档可被 `local_uploads` 检索。

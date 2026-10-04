# 从零配置：macOS Apple Silicon + Dify + 本地知识库

本仓库将 Dify 对话编排、本地 Qdrant、MLX 向量模型和文件入库 bridge 连接起来。Dify 负责工作流、对话和引用展示；bridge 负责把附件转文字、分块、入库和检索；Qdrant 保存向量；DeepSeek 根据召回证据生成回答。

参考环境完成了单元测试和一次端到端演示。全新电脑还没有完成完整验收，搭建完成后务必按 [validation.md](validation.md) 做真实测试。

## 1. 准备位置和软件

需要 Apple Silicon Mac、Docker Desktop、Python（参考验证使用3.11）、DeepSeek API 账号，以及一个兼容 `mlx-embeddings` 加载和本服务编码接口的本地 `Qwen3-VL-Embedding-2B-8bit` 模型目录。模型权重不随仓库提供；不能随意用另一份不同维度模型代替。MLX 仅支持 Apple Silicon macOS。

建议把仓库、模型、Qdrant 数据和 Docker Desktop 数据位置都放在外置盘。Docker Desktop 的 File Sharing 要允许该盘；Docker data location 也应在外置盘。不同 Docker Desktop 版本设置位置不同，以实际界面为准。

```zsh
cd /Volumes/YourExternalDisk
git clone <your-github-repository-url> dify-local-rag-bridge
cd dify-local-rag-bridge
```

不要把模型、Qdrant 数据、bridge 的 `data/` 或任何 API key 放进 Git。

## 2. 建立 Python 环境

```zsh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-embedding.txt
.venv/bin/python -m pip install -r dify_bridge/requirements.txt
```

`requirements-embedding.txt` 固定了参考环境中验证过的 MLX 版本，并不会下载模型。bridge 依赖包含 FastAPI、Qdrant client、PDF 文字抽取和 multipart 上传支持。图片 OCR 使用 macOS Vision，不需要另装 Python OCR 包。

## 3. 启动向量服务

准备好本地模型后，只在当前终端设置模型路径：

```zsh
export EMBEDDING_MODEL_PATH='/Volumes/YourExternalDisk/models/Qwen3-VL-Embedding-2B-8bit'
.venv/bin/python serve_vl_embedding.py
```

另开终端确认：

```zsh
curl http://127.0.0.1:8003/v1/models
```

它应返回 `Qwen3-VL-Embedding-2B-8bit`。服务只监听本机 `127.0.0.1:8003`。

## 4. 启动 Qdrant

以下是最小 Docker 示例，镜像版本为原环境观察到的1.19.1。将卷目录改为你的外置盘真实位置。如果已有Qdrant占用6333端口，先使用并检查已有实例，不要重复执行新建命令。

```zsh
mkdir -p /Volumes/YourExternalDisk/dify-local-rag/qdrant
docker run --name dify-local-rag-qdrant \
  --restart unless-stopped \
  -p 127.0.0.1:6333:6333 \
  -v /Volumes/YourExternalDisk/dify-local-rag/qdrant:/qdrant/storage \
  qdrant/qdrant:v1.19.1
```

首次成功上传时，bridge 会创建 `dify_uploads_vl2b_2048` collection（2048 维、cosine）。不要将其他维度模型写入它。

## 5. 创建 bridge 令牌并启动 bridge

`dify_bridge/data/` 会保存令牌、上传原件、完成状态和编译后的 OCR 工具；它已被 `.gitignore` 排除。生成令牌并限制权限：

```zsh
mkdir -p dify_bridge/data
python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > dify_bridge/data/auth.token
chmod 600 dify_bridge/data/auth.token
```

不要公开、复制到聊天或提交这个文件。配置Dify时可在自己的本地编辑器安全查看，并仅填入自己的Dify认证表单和秘密变量；不要在演示截图中显示。随后启动：

```zsh
.venv/bin/python -m uvicorn dify_bridge.server:app --host 127.0.0.1 --port 8004
```

bridge 保持在宿主机 loopback 上；Docker Desktop 中的 Dify 将通过 `host.docker.internal:8004` 访问它。不要为此把 bridge 公开到 `0.0.0.0`。

## 6. 部署 Dify 并配置网络

按 [Dify Docker Compose 官方文档](https://docs.dify.ai/en/getting-started/install-self-hosted/docker-compose) 部署 Dify，首次打开 Web 页面时创建管理员。Dify 的 SSRF proxy 需允许宿主机：在其 `.env` 中配置（以你的 Dify 版本的配置项为准）：

```dotenv
SSRF_PROXY_ALLOW_PRIVATE_DOMAINS=host.docker.internal
```

修改后用 Dify 自己的 Compose 命令重启相关服务。这个设置只让容器访问受控宿主机地址；bridge 仍由 loopback 保护。

## 7. 配置 DeepSeek

在 Dify 的模型供应商页安装或启用官方 DeepSeek provider，并在安全表单填写 API key。模板默认选择 `deepseek-flash`。如果插件版本显示不同模型名，在导入后的两个 LLM 节点中选择可用模型。

模型会收到用户问题、有限对话历史和召回的文字片段；上传原件和本地 Qdrant 数据不会直接由本模板发送给模型。API key 不能写进 YAML、Markdown、Git 或命令行。

## 8. 创建 Dify 外部知识集

1. 在 Dify 的“知识库”创建“外部知识库 API”。
2. 基础 URL 填 `http://host.docker.internal:8004`，**不要**附加 `/retrieval`。
3. 认证选择 Bearer Token，安全填写第 5 步的同一令牌。
4. 基于该 API 创建外部知识集，外部 Knowledge ID 填 `local_uploads`。
5. 复制 Dify 显示的 Dataset ID（UUID）。它不是 Qdrant collection 名称。

外部知识集界面可能显示文档数为 0，因为文档实际由 Qdrant 和 bridge 管理；必须以真实问答验证。

## 9. 导入工作流

打开 `dify_workflows/local_knowledge_chatflow.yml`，把唯一的 `REPLACE_WITH_YOUR_DIFY_DATASET_ID` 替换为第 8 步 Dataset ID。导入 Dify 的 Chatflow / Advanced Chat 应用后：

1. 在环境变量中填写 `BRIDGE_API_KEY`，值与令牌文件完全相同。
2. 检查两个 LLM 节点的 DeepSeek provider 与模型名。
3. 发布应用。
4. 按 [validation.md](validation.md) 在预览与已发布入口分别验收。

工作流里的 `/ingest` 节点专门处理本轮上传；外部知识库连接专门处理检索。令牌在 YAML 中留空是正确的。

## 10. 重新启动顺序

电脑重启后依次启动：Qdrant、向量服务、bridge、Dify。只要外置盘上的 Qdrant 卷和 `dify_bridge/data/` 都保存完好，已完成的上传文件仍然可以检索。

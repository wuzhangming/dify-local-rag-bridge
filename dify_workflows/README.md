# Dify 工作流模板

`local_knowledge_chatflow.yml` 是面向 Dify 1.17.1 / DSL 0.7.0 的 Advanced Chatflow 模板。它把用户上传的文件交给本地 bridge 长期入库，再通过 Dify 外部知识集检索并由 DeepSeek 回答。

这份公开模板只查询 `local_uploads`：即本工作流经 bridge 写入的资料。它不假设你已有任何个人旧向量库。

## 导入前配置

1. 启动 Qdrant、Embedding 服务、bridge 和 Dify。bridge 在宿主机保持 `127.0.0.1:8004` 监听；Docker 中的 Dify 通过 `host.docker.internal:8004` 访问它。
2. 在 Dify 的“知识库”中创建“外部知识库 API”。基础 URL 填 `http://host.docker.internal:8004`，认证填 `Bearer <bridge token>`。不要在这里附加 `/retrieval`。
3. 基于该 API 创建外部知识集，外部 Knowledge ID 填 `local_uploads`。
4. 复制该知识集的 **Dataset ID**。它既不是 Qdrant collection 名，也不是 `local_uploads`。
5. 打开本 YAML，把 `REPLACE_WITH_YOUR_DIFY_DATASET_ID` 改为第 4 步的 Dataset ID，再导入 Dify。
6. 在导入后的工作流环境变量中填写 `BRIDGE_API_KEY`。该值必须与外部知识库 API 的 Bearer token 相同，不能提交到 Git。
7. 在 Dify 模型供应商页配置 DeepSeek。模板使用 `langgenius/deepseek/deepseek` 的 `deepseek-flash`；若你的已安装插件模型名称不同，在两个 LLM 节点中选择可用模型。

## 流程行为

```text
用户问题和可选附件
  ├─ 有附件：逐个文件上传 → bridge /ingest → 成功状态汇总
  └─ 无附件：继续检索
                    ↓
              多轮问题改写
                    ↓
     Dify 外部知识集 → bridge /retrieval → local_uploads
                    ↓
             根据证据生成回答和引用
```

支持 UTF-8 Markdown/TXT、可提取文字的 PDF，以及 PNG/JPG/JPEG/HEIC 图片。图片由 macOS Vision OCR 转成文字；扫描型 PDF 不在本模板范围。单文件上限是 25 MB，单次最多 5 个附件。

同一“文件名 + 内容”可安全重试；同名不同内容会保留为不同版本。bridge 只有在写入和校验完成后才让文档参与检索。

## 导入后验收

1. 上传 `examples/Dify界面上传验收.txt`，询问“紫藤项目的负责人和验收代号是什么？请注明来源。”
2. 新开一个对话，不上传文件，再问“紫藤项目负责人是谁？”
3. 检查回答包含“周岚”和“ZT-8632”，并显示文件引用。
4. 上传 `examples/图片文字识别验收.png`，询问其中的项目编号，确认 OCR 能检索到 `YX-4826`。

如果工作流报错，不要把附件已出现在界面上当成已长期入库。具体排查见 `docs/validation.md`。

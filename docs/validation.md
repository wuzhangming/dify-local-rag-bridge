# 验收与排查

## 本次整理的实际检查结果

2026-10-04，公开副本使用已有参考Python环境运行9项单元测试，全部通过；Python编译检查、Swift OCR类型检查、14节点13边的YAML结构及环境占位检查通过。公开模板秘密变量为空，个人dataset ID已移除；未复制真实数据、令牌、模型或运行数据库。

原本机链路已完成MD、TXT、文字PDF、图片OCR的实际入库，Dify界面TXT上传、新对话检索、多轮指代、旧库正式问答、来源展示和无预算证据的测试。公开包改为模型路径环境变量、dataset占位和上传库演示，**尚未在空环境从零完成整套部署**。自动测试不能替代这一步。

参考环境观察到的版本：Python3.11、Dify1.17.1、Qdrant1.19.1、fastapi0.129.2、uvicorn0.39.0、httpx0.28.1、qdrant-client1.19.1、python-multipart0.0.24、pypdf6.19.0、mlx0.31.2、mlx-embeddings0.1.0、transformers5.17.0。模型依赖固定参考版本，bridge依赖目前未完整锁定，其他版本需要重新验收。

## 本地自动检查

在仓库根目录先运行：

```zsh
.venv/bin/python -m unittest dify_bridge.tests.test_bridge
.venv/bin/python -m py_compile serve_vl_embedding.py dify_bridge/*.py
swiftc -typecheck dify_bridge/ocr.swift
```

它们只验证 Python 逻辑、语法和 OCR 源码，不能代替 Docker 网络、模型、Qdrant、OCR 与 DeepSeek 的真实验收。

## 上传并问答

在已发布 Dify 应用中上传 `examples/Dify界面上传验收.txt`，发送：

```text
请根据我上传的文件，回答紫藤项目的负责人和验收代号，并注明来源。
```

预期包含“周岚”“ZT-8632”并引用该文件，且工作流运行成功。

## 验证长期入库

新开对话，不上传文件，发送：

```text
紫藤项目负责人是谁？资料归档日期是什么时候？请注明来源。
```

预期包含“周岚”“每月十五日”并引用同一文件。失败时检查 external Knowledge ID 是否为 `local_uploads`、入库节点是否成功、bridge data 目录和 Qdrant 卷是否持续存在。

## 验证图片与 PDF

上传 `examples/图片文字识别验收.png`，问“银杏项目的归档负责人和项目编号是什么？”预期为陈宁、YX-4826。首次图片上传会编译 Swift OCR 工具。

上传 `examples/PDF_text_acceptance.pdf`，问“Cedar 项目的编号和负责人是什么？”预期为 CD-5928、Morgan。扫描 PDF 没有文字层会失败，需先 OCR。

## 验证不会编造

询问“紫藤项目的预算金额是多少？资料里没有的话请明确说明。”预期为说明资料不足，不能给出虚构数字或引用。

## 常见问题

| 现象 | 优先检查 |
| --- | --- |
| 外部知识库连接失败 | SSRF allowlist 是否有 `host.docker.internal`；基础 URL 不应带 `/retrieval`；令牌是否一致。 |
| 上传 401 | Dify 的 `BRIDGE_API_KEY` 与 `auth.token` 不一致。 |
| 上传 502 | Qdrant、embedding 或 bridge 未启动；查看 bridge 日志。 |
| 新会话查不到上传资料 | 附件显示不等于入库成功；检查 Dify 工作流运行记录。 |
| 图片 OCR 失败 | 仅支持 PNG/JPG/JPEG/HEIC，且 macOS 必须有 `/usr/bin/swiftc`。 |
| 模型加载失败 | `EMBEDDING_MODEL_PATH` 未设置或不是兼容模型目录。 |

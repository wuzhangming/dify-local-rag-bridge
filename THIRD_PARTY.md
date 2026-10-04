# 第三方组件与公开范围

本项目连接现有框架和模型，未将它们作为自研成果。

| 组件 | 官方来源 | 使用方式 |
|---|---|---|
| Dify | https://github.com/langgenius/dify | 用户自行部署；仓库仅提供适配编排 |
| Qdrant | https://github.com/qdrant/qdrant | 用户自行部署向量库 |
| Qwen3-VL-Embedding | https://github.com/QwenLM/Qwen3-VL-Embedding | 用户自行获取兼容模型；不发布权重 |
| MLX / MLX Embeddings | https://github.com/ml-explore/mlx / https://github.com/Blaizzy/mlx-embeddings | 本地模型运行依赖 |
| FastAPI | https://github.com/fastapi/fastapi | Python API依赖 |
| pypdf | https://github.com/py-pdf/pypdf | PDF文字抽取依赖 |
| DeepSeek | https://api-docs.deepseek.com | 用户自己的远程模型服务和凭据 |
| macOS Vision | Apple系统框架 | Swift OCR工具调用本机框架 |

第三方组件和模型适用各自的许可与服务条款。具体版本、下载源和许可应在使用时核对；本仓库没有通过一个新许可证覆盖第三方内容。

本次没有代维护者选择项目开源许可证。代码首先作为公开作品展示；未来确认授权范围后可增加合适的LICENSE。公开源码可见性与开放复用授权不是同一回事。

开发使用了AI辅助分析、实现和验证。个人原始资料、上传数据、私密令牌、Dify数据库、模型权重、旧库索引和内部截图均不作为公开内容。

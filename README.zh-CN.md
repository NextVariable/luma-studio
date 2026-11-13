# Luma Studio · 流幕

[![CI](https://github.com/NextVariable/luma-studio/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/NextVariable/luma-studio/actions/workflows/ci.yml)

流幕是面向分集漫剧的本机制作工作台。把剧本、角色造型、镜头和对白放在同一部作品里，按镜头返工，最后导出整集 MP4。

[English](README.md) · [架构与数据](docs/architecture.md) · [服务配置](docs/providers.md) · [贡献指南](CONTRIBUTING.md) · [更新记录](CHANGELOG.md)

**当前为开发预览版。** 导入素材后可以在本机完成制作、复核和导出，无需模型账号。云端生成可使用自己的服务商凭据，完整的云端生成成片仍待端到端验收。

## 快速开始

需要 **macOS 或 Linux**、**Python 3.11+**，以及含 `ffprobe` 和 `libx264` 编码器的 **FFmpeg**。

```sh
git clone https://github.com/NextVariable/luma-studio.git
cd luma-studio
python3 -m luma check
python3 -m luma
```

打开[本机工作台](http://127.0.0.1:7820/)。

1. 在「作品」新建作品，在「镜头」添加分镜。
2. 在每镜的「素材」导入并选用图片或视频。在「对白」编辑台词并选用音轨。
3. 确认镜头，进入「成片」。从本集制作清单直接跳回处理缺项，完成后导出 MP4。
4. 修改某一镜后，确认哪些画面和音轨可以沿用，再导出新版。之前的成片可从导出记录查看。

运行 `python3 -m unittest discover -s tests -p test_delivery_checklist.py -v`，可以用本地测试素材复现单镜返工和重导出。此测试实际调用 FFmpeg，无需模型凭据。

## 制作流程

| 环节 | 当前能力 |
| --- | --- |
| 分镜 | 按集管理剧本。可以手动分镜，也可以接入带连续性复审和人工审批的 Dify 导演流程。 |
| 制作准备 | 为镜头固定角色造型和参考图。按片段设置生成参数，生成或导入后选用候选素材。 |
| 单镜返工 | 对照修改前后，查看哪些画面或对白音轨可沿用、需要重审或已取消选用，再确认修改。 |
| 交付 | 本集制作清单显示缺项与导出阻塞，可一键跳转。MP4 支持选用画面、独立音轨和可切换字幕。 |

## 可选的模型服务

| 能力 | 服务 |
| --- | --- |
| 导演分镜与审批 | Dify |
| 图片和视频生成 | fal，当前提供 FLUX.1 Kontext Pro 和 Kling 2.5 Turbo Pro |
| 配音和单镜修改建议 | OpenAI 直连。单镜修改也可以沿用已配置的 Dify 应用。 |

按[服务配置](docs/providers.md)填写自己的 Key。新建库的生成额度默认为零。生成确认会列出预计费用或计费方式和本机授权次数，实际账单由各服务商结算。

## 数据与开发

流幕默认只在本机监听。备份和恢复见[架构与数据](docs/architecture.md)。

| 路径 | 内容 |
| --- | --- |
| [`luma/`](luma/) | Python 包：HTTP 服务、SQLite、任务队列、服务适配、FFmpeg 导出 |
| [`web/`](web/) | 原生 JavaScript 浏览器工作台、样式和随附素材 |
| [`workflows/`](workflows/) | Dify 工作流定义及其生成脚本 |
| [`tests/`](tests/) | Python 与 JavaScript 回归测试 |
| [`docs/`](docs/) | 架构与服务配置 |

```sh
python3 -m unittest discover -s tests -v
node --test tests/*.test.js
```

前端测试使用 Node.js 22+。参见 [MIT 许可](LICENSE)、[第三方声明](THIRD_PARTY_NOTICES.md)和[安全问题报告](SECURITY.md)和[行为准则](CODE_OF_CONDUCT.md)。

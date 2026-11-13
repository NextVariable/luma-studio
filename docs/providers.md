# Provider setup · 服务配置

The local import, review, and MP4 export workflow can run without model services. Provider requests send the inputs required by that task, such as the scoped script, selected reference media, or dialogue.

| Provider | Configure | Usage |
| --- | --- | --- |
| Dify | In Dify, import [director-production.yml](../workflows/production/director-production.yml), configure its model nodes, and publish the app. Save its app Key in **设置 → AI 分镜**, or set `DIFY_PRODUCTION_KEY`. | Script breakdown, shot proposals, continuity review and human approval. The connection check reads app metadata. |
| fal | In **镜头 → 制作**, open the image and video service settings and save your fal Key, or set `FAL_KEY`. | FLUX.1 Kontext Pro images and Kling 2.5 Turbo Pro 5- or 10-second image-to-video segments. Choose and save the segment and its references before submitting. |
| OpenAI | Install the optional WebSocket dependency in the studio's Python environment, then save the Key in **设置 → OpenAI 直连**, or set `OPENAI_API_KEY`. | GPT Realtime 2.1 Mini speech and GPT-5.4 mini single-shot proposals. |

```sh
python3 -m pip install -r requirements-realtime.txt
```

Use [.env.example](../.env.example) as a template for manual configuration. Credentials stay in the local environment or the library's `.env`. Use **设置 → 生成额度** to authorize a batch. The local authorization count and the provider bill are independent. Estimate and actual usage may differ.

[Production workflows](../workflows/production/) includes the optional Dify single-shot revision template. The historical Dify audio workflow supports existing configurations and recovery of older tasks. New speech jobs use OpenAI. The [smoke workflows](../workflows/smoke/) are connection and contract fixtures.

中文操作顺序为先在本机保存 Key，再确认制作参数，查看报价或计费方式，最后按需要开放本批生成额度。旧音色 `fable`、`onyx` 和 `nova` 需要新建受支持的角色音色版本，再显式更新镜头绑定。

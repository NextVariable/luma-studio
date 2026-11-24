# Luma Studio V0.5.1 任务清单

> 依赖顺序执行；每完成一组执行对应测试。除用户明确要求外，不发起真实付费调用。

## T1 参考图批准门禁

- [x] `luma/visual.py`：新增 `STATUS_LABELS`、`view_states()`。
- [x] `luma/studio.py::asset_image_packet`：默认仅已批准/旧版批准；`allow_unapproved` 显式确认；无批准视图时阻塞；每张引用写入状态与 SHA；返回 `approval` 元数据。
- [x] `luma/studio.py::storyboard_packet`：角色/场景只取已批准参考；有图无批准时给出可操作错误。
- [x] `luma/studio.py::preview_job_quote`：透传状态、排除清单、确认提示、风格标签。
- [x] `luma/preparation.py::catalog`：条目增加 `approved` / `approval_status`。
- [x] `luma/sample_scene.py`：为示例素材写入批准记录。
- [x] 测试：`tests/test_reference_approval.py`，更新 `tests/test_visual_assets.py`。

验证：`python -m pytest -q tests/test_visual_assets.py tests/test_reference_approval.py`

## T2 资产版本语义与交互

- [x] `web/js/cast.js`：上传视图/主图前确认“创建新版本、批准不继承、绑定不变”。
- [x] 版本列表显示批准数、视图数、绑定镜数、当前选用。
- [x] 未批准视图提示与逐视图批准状态。
- [x] 采用/恢复版本文案明确不影响已有镜头绑定。
- [x] 后端测试：新版本不继承批准；`asset_select` 不改变绑定；旧版本批准仍可查。

验证：Node 语法检查 + Python 版本语义测试。

## T3 风格感知美术指导

- [x] 新增 `luma/art.py`：四种风格、通用约束、风格专属约束、`resolve`/`constraints`。
- [x] `production.validate` 校验可选 `art_style`，不写默认值。
- [x] `asset_image_packet`、`storyboard_packet` 接入风格约束，移除写实硬编码。
- [x] `preparation.freeze` 视频指令追加风格约束。
- [x] `web/js/script.js` 增加美术风格选择。
- [x] 测试：`tests/test_art_direction.py`，含冲突指令检查。

验证：`python -m pytest -q tests/test_art_direction.py`

## T4 单镜返工与制作证据

- [x] `quality.candidates` 增加 `evidence_class` / `provider` / `verified`。
- [x] `evidence.classify` 将 `assembly`、`blocking` 归为本地。
- [x] `web/js/shots.js`、`web/js/delivery.js` 显示证据类别、模型、请求号、费用、评分、采用状态与免责声明。
- [x] 测试：`tests/test_v05_1_regressions.py` 覆盖单镜隔离与证据类别。

验证：`python -m pytest -q tests/test_v05_1_regressions.py tests/test_production_evidence.py`

## T5 工作流与全量回归

- [x] `shots.js` 基础模式步骤状态与“去批准参考”入口。
- [x] `python -m pytest -q` 全量。
- [x] JS 全量测试（仓库现有命令）。
- [x] `ruff check luma tests`。
- [x] 本地启动服务 + 浏览器检查示例工作流（不提交付费请求）。
- [x] 旧项目加载、多视图批准/撤换/版本切换、任务中断恢复、单镜返工、证据费用、模拟端到端导出 MP4。

## T6 文档与交付

- [x] 更新 `docs/feature-matrix-v05.md`、`docs/acceptance-report-v05.md` 的 V0.5.1 状态。
- [x] 按模块提交（参考门禁 / 风格与版本 / 证据与工作流 / 文档）。
- [x] 检查敏感文件与工作区状态。
- [x] `env -u GH_TOKEN git push`。
- [x] `env -u GH_TOKEN gh pr edit 5` 更新 PR 正文，不新建 PR，不合并 main。
- [x] 输出最终验收报告（Commit、PR Head、修改文件、问题证据、测试、遗留缺陷、真实 API 状态、审计与合并建议）。

## 停止条件

- 需要真实付费调用但未获单独授权。
- 需要强制推送、改写 `main` 或破坏本地数据。
- 发现与规格冲突且无法通过安全默认值解决。

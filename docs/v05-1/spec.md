# Luma Studio V0.5.1 实施规格（Spec）

## 目标

在 `dev/trae-luma-v05` / PR #5 上完成 V0.5.1：参考图批准门禁、资产版本语义、风格感知美术指导、单镜返工与证据可读性、全量回归。不重写架构，不合并 `main`，不发起未授权付费调用。

## 当前审计结论

- 分支 `dev/trae-luma-v05`，HEAD `9a0de59`，与 `origin/dev/trae-luma-v05` 一致，工作区干净。
- `luma/studio.py::asset_image_packet` 会把同版本所有视图加入模型请求，只对已批准视图做 SHA 校验；未批准视图会静默进入生成。这是 P0 缺陷。
- `luma/studio.py::storyboard_packet` 在无批准参考时回退到版本主图，并标记为 `legacy`，同样会静默使用未批准参考。
- `luma/preparation.py::catalog` 列出所有资产视图，没有批准状态信息；高级模式可选择未批准视图。
- 美术质量约束硬编码“真实皮肤 / 电影级写实”，对二维动画风格不成立。
- `luma/quality.py::candidates` 缺少证据类别，缺失 job/receipt 的候选无法在比较界面区分。
- 已有 416 项 Python 测试、JS 测试、ruff 基线；真实生成未验收。

## 设计与实现

### 1. P0 参考图批准门禁

**`luma/visual.py`**

新增：

```python
STATUS_LABELS = {'approved': '已批准', 'legacy': '旧版批准', 'unapproved': '未批准'}
def view_states(version, references, role, asset_id, version_id) -> list[dict]
```

`view_states` 按 `allowed_views(role)` 顺序返回当前版本实际存在的视图：

- `view` / `file` / `label`
- `status`: `approved`（有 SHA 且文件匹配）、`legacy`（有批准记录但无 SHA）、`unapproved`
- `approval`: 对应批准记录或 `None`

批准记录的文件必须与版本视图文件一致，否则视为 `unapproved`。

**`luma/studio.py::asset_image_packet`**

- 用 `view_states` 代替全量遍历。
- 默认仅使用 `approved` / `legacy` 视图；最多 3 张。
- 若版本存在视图但没有任何批准视图，且未显式传入 `allow_unapproved=True`，抛出：
  `这个版本只有未批准的视图；请先在角色与素材中批准要用于生成的视图，或明确选择“使用未批准视图”`。
- `allow_unapproved=True` 时才纳入未批准视图，并在提示词中加入明确说明：
  `注意：本次生成包含尚未批准的视图，仅用于本次请求，不会自动成为正式参考。`
- 每张引用写入 `status`、`sha256`、`asset_id`、`version_id`、`view`、`source`（批准来源）。
- 形成请求前重新计算文件 SHA；已批准记录带 SHA 且不匹配时立即报错。
- 返回包增加：

```python
packet['approval'] = {
  'used': [{'view','status','label'}],
  'excluded': [{'view','status','label','reason'}],
  'allow_unapproved': bool,
  'requires_confirmation': bool,
}
packet['art_style'] / packet['art_label']
```

- 风格参考仍只允许一张，必须已批准，并校验 SHA。

**`luma/studio.py::storyboard_packet`**

- 角色：仅使用 `approved_refs`。若版本有图片但无批准记录，抛出：
  `请先在角色与素材中批准{name}要用于分镜的参考视图`。
- 场景：仅使用已批准参考；若场景版本有图片但无批准，抛出对应错误。
- 无任何图片时保留原有“请添加参考图”提示。
- 机位构图、本镜已选图不参与批准门禁。

**`luma/studio.py::preview_job_quote`**

- 透传 `references` 的 `status`。
- 增加 `excluded_references`、`requires_approval`、`approval_notice`、`art_label`。
- 报价仍由 packet digest 保护；提交时 `job_request` 重新生成 packet，参数变化会拒绝旧报价。

**`luma/preparation.py::catalog`**

- 每个资产视图条目增加 `approved`（bool）与 `approval_status`。
- 高级模式仍允许显式选择，但界面必须显示“未批准”标记与警告。

**`luma/sample_scene.py`**

- 为示例项目中实际存在的角色/场景主图写入批准记录（`view='primary'`、`source='示例素材'`、SHA），保证示例项目可直接走通分镜流程；不涉及用户旧数据。

### 2. P0 资产版本与多视图语义

- 后端语义保持：`asset_view` / `character_look` 创建新版本；版本不可变；镜头 `asset_bindings` 不自动变化。
- 新增回归测试确认：
  - 新版本不继承旧版本批准记录。
  - `asset_select` 不改变任何已有镜头绑定。
  - 新版本可以恢复到旧版本，旧版本批准记录仍可查。
  - 同一版本同一视图重复批准必须显式 `replace=True`。
- `web/js/cast.js`：
  - 上传角色/场景视图、上传主设定图前，用 `L.confirmBox` 明确告知“会创建新的素材版本；旧版本批准不继承；已有镜头绑定不变”。
  - 版本列表展示：`已批准 x/y 视图`、`绑定 n 镜`、当前选用标记。
  - 当前版本存在未批准视图时显示提示：“这些视图尚未批准，正式生成不会使用。”
  - 视图槽显示批准状态；点击“批准此视图”沿用现有 API。
  - “选用此版本”文案改为“选用为当前版本（不影响已有镜头绑定）”。

### 3. P0 风格感知美术指导

**新增 `luma/art.py`**

```python
STYLES = {
  'anime':      {'label': '精致二维动画 / 赛璐璐', 'keywords': (...), 'specific': '...'},
  'comic':      {'label': '国漫 / 插画',           'keywords': (...), 'specific': '...'},
  'cinematic':  {'label': '电影写实',               'keywords': (...), 'specific': '...'},
  'custom':     {'label': '自定义风格',             'keywords': (),    'specific': ''},
}
GENERAL = '...身份一致、脸部完整、肢体结构、服装连续、画面干净、无多余角色、无水印...'
def resolve(brief) -> dict   # 显式 art_style 优先；其次关键词推断；非空但未命中 -> custom；空 -> cinematic
def constraints(brief, subject) -> str
```

- 通用约束不再写“真实皮肤”“摄影级写实”“动漫式简化”。
- 风格专属：
  - anime：干净线稿、赛璐璐分层上色、动画比例五官、平涂材质；禁止照片级皮肤纹理和三维写实质感。
  - comic：国漫插画线条与色彩层次；禁止照片写实皮肤与三维渲染感。
  - cinematic：电影级实拍光影、可信皮肤与布料材质；避免卡通化线条。
  - custom：使用 `creative_brief.style` 原文，仅叠加通用约束。
- `production.validate` 校验可选 `art_style` 合法性；不写入默认值，避免改变旧项目 digest。
- 接入点：
  - `asset_image_packet` 角色/场景提示词。
  - `storyboard_packet` 分镜提示词。
  - `preparation.freeze` 视频指令末尾追加风格约束（确定性，保持不变式）。
- `web/js/script.js` 创作设定增加“美术风格”下拉：自动 / 二维动画 / 国漫插画 / 电影写实 / 自定义，并保存到 `creative_brief.art_style`。

### 4. P1 单镜返工与制作证据

- `luma/quality.py::candidates`：
  - 增加 `evidence_class`：`local` / `provider_recorded` / `provider_unrecorded`。
  - 增加 `verified=False` 与 `provider`（来自 job payload）、`request_id`。
  - 缺失 job 或 receipt 的候选标为 `provider_unrecorded`。
- `luma/evidence.py::classify`：把 `assembly`、`blocking` 归入 `local`；保留免责声明。
- `web/js/shots.js::compareCandidates`：
  - 显示证据类别、模型、请求号、报价/实扣、采用状态、人工评分。
  - 明确显示“离线/模拟记录不能作为真实 API 验收”。
- `web/js/delivery.js`：证据表增加模型、请求号、费用、评分、采用状态，并显示 `verified` 不可声称提示。
- 确认单镜返工只影响目标镜头：新增测试覆盖镜头 A 重新生成后镜头 B 的 takes/selected/bindings 不变。

### 5. P1 工作流可读性

`web/js/shots.js::basicProduction`：

- 每一步显示完成/阻塞状态。
- 参考缺失或未批准时，提供“去批准参考”按钮，直接打开第一个阻塞资产的对话框。
- 分镜、复核、返工按钮保持单镜作用范围；文案说明“只影响这一镜”。

### 6. 测试与验收

新增/更新：

- `tests/test_visual_assets.py`：更新旧断言，覆盖多视图、无批准、旧版数据、文件变化、非法视图、重复批准、跨版本。
- `tests/test_reference_approval.py`：批准门禁、`allow_unapproved`、排除清单、摘要预览。
- `tests/test_art_direction.py`：四种风格、提示词冲突检查、视频/分镜注入。
- `tests/test_v05_1_regressions.py`：版本不继承批准、绑定不变、单镜返工隔离、证据类别。
- 全量：`python -m pytest -q`、JS 测试（仓库现有命令）、`ruff check`。
- 浏览器：本地启动服务，加载示例项目，验证创建角色视图 → 批准 → 报价预览 → 版本列表/绑定提示（不提交真实付费请求）。
- 端到端：使用示例项目和模拟供应商测试链路，导出 MP4 的现有测试保持通过。

## 非目标

- 不调用真实付费 Seedream / Wan / MiniMax / Dify。
- 不合并 `main`，不强制推送。
- 不重写前端框架，不引入新依赖。
- 不破坏不可变版本设计，不删除历史候选与批准记录。

## 交付

- 按模块提交 3–4 个 commit。
- `env -u GH_TOKEN git push` 推送 `dev/trae-luma-v05`。
- `env -u GH_TOKEN gh pr edit 5` 更新 PR #5，不新建 PR。
- 最终报告包含 commit SHA、PR Head、修改文件、测试结果、未解决缺陷、真实 API 验收状态、是否建议合并。

## 需要用户确认

请确认以上范围与优先级。确认后我将按 `docs/v05-1/tasks.md` 连续实施，仅在遇到无法自主决策的高风险问题时停下。

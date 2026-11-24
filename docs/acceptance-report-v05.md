# Luma Studio V0.5 产品验收报告

日期：2026-11-22
分支：`dev/trae-luma-v05`  
对照基线：`origin/main` = `6e20c1ad0e730b7dfab078fe14cb70b848d85dfc`  
本报告只记录已经实际执行或可复现的证据；未执行的真实付费调用和人工画质评审单独标注。

## 1. 版本同步结论

- 开发目录：`luma-studio-v05`（`luma-studio-open-source` 的 worktree）。
- 本地 `main` 与 `origin/main` 均为 `6e20c1a`，未修改远端 main。
- 未发现其他目录有更新的 V0.5 实现；`luma-studio-v04` 为旧快照，`luma-studio` 保存真实运行数据。
- 所有 SQLite 数据、真实素材、历史候选、`.env` 与 API Key 均未删除或覆盖。
- V0.5 提交序列：
  - `8038dc8` 资产候选审核与证据台账
  - `5ddb250` 状态与徽章整理
  - `b4b23d1` README
  - `ad61482` V0.5 功能完成矩阵
  - `1133b10` 多视图参考批准与风格引导的资产生成
  - `5522b84` 验收文档更新

## 2. 本轮完成的能力

### P0 高质量视觉资产链

- 剧本/资产 → 角色定妆候选 → 人工确认 → 资产版本 → 场景图 → 批准引用 → 正式分镜的链路已连通。
- 参考图按视图批准：角色支持 `primary/front/three_quarter/side/back`，场景支持 `primary/wide/detail/reverse`。
- 同一资产版本可同时批准多张视图；重复批准同一视图需要显式替换；旧数据中没有 `view` 的引用会按文件自动推导视图并继续可用。
- 角色与场景资产生成会注入最多 3 张同资产既有视图，以及 1 张作品级已批准画风参考。
- 生成提示词写入成稿质量约束：解剖与五官准确、材质真实，禁止低多边形、塑料感、简笔五官、多余肢体、文字和水印。
- 分镜生成优先使用已批准视图；场景参考与画风参考分别标注用途；批准文件的 SHA256 在生成前复核，文件变化会拒绝生成。
- 资产版本仍为不可变绑定：新增视图或换版本不会悄悄改变已经绑定旧版本的镜头。

### P0 统一镜头工作台

- 基础模式保留“检查人物和场景 → 定机位 → 分镜 → 候选 → 对白/交付”的连续路径。
- 基础模式新增参考就绪状态：显示已批准/待批准数量与是否设置作品画风。
- 基础模式新增“单镜返工”入口，复用既有局部改写对话框，不要求用户理解 JSON、Dify 节点或内部任务状态。
- 高级模式保留既有分段制作、Dify 计划与预览应用能力。

### P1 可靠性

- 多视图引用一致性：版本、视图、文件、来源、哈希绑定校验。
- 旧项目兼容：无 `view` 的历史参考继续生效。
- 生成参考顺序与供应商契约：角色/场景设定图最多 3 张，画风图只能 1 张且必须末尾。
- 付费安全：本轮未配置真实付费调用，未自动重提任何不确定任务；测试中拦截网络连接。

## 3. 证据分级

| 证据类型 | 本轮结果 |
| --- | --- |
| 离线自动化测试 | 416 个 Python 测试全部通过；23 个 JS 测试全部通过；ruff 通过 |
| 模拟供应商响应 | 资产候选、批准、版本绑定、证据台账、任务恢复等路径通过模拟 |
| 真实模型 API | 本轮未执行 Seedream / Wan / MiniMax / Dify 付费调用（未获明确授权），不作为已验收 |
| 人工画质与体验评审 | 浏览器复验通过界面结构与入口可见性；真实画质、低多边形改善、场景连续性未做人工评审，标记待验收 |

新增测试：`tests/test_visual_assets.py`（5 项）
- 同一版本多视图分别批准且镜头绑定不变
- 资产生成携带既有视图与作品画风，参考顺序受契约保护
- 分镜优先采用已批准视图与场景参考
- 无 `view` 的旧引用兼容
- 批准文件变化在生成前被拒绝

浏览器复验（临时数据目录，未触碰真实数据）：
- 阿远资产对话框显示四个视图槽位与“已批准参考 / 批准此视图”。
- 镜头 02 的制作面板基础模式显示“参考就绪：0 张已批准 · 1 张待批准 · 未设作品画风”，并显示“单镜返工”。

## 4. 尚未解决或待验收

### P0

- 真实 Seedream 多视图定妆与多参考场景图未运行，画质与低多边形改善无法确认。
- 真实分镜生成中多参考的实际一致性未验证。
- 两个端到端项目（A《末班车之后》；B 全新剧本从空白建角色、场景、分镜、成片）只完成离线与界面级验收，未完成真实付费成片验收。

### P1

- 每个角色在分镜中仍只使用一张最佳批准视图（供应商契约与当前参数映射限制）；多视图主要用于资产生成与参考库。
- 真实 Wan / MiniMax / Dify 续查、费用对账与 MP4 交付未在本轮重新跑通。
- 新用户完整任务与移动端体验未做正式可用性测试。

## 5. 交付状态

- 分支：`dev/trae-luma-v05`；V0.5.1 起点 `9a0de59`。
- 变更文件（相对 `6e20c1a`）：以 `git diff --stat` 为准。
- PR #5 已创建（base `main`），V0.5.1 完成后更新同一 PR；未合并 `main`。
- 历史建议标题：`Luma Studio V0.5: multi-view approved references and style-guided asset generation`
- 历史建议正文（V0.5 初版，现行正文以 PR #5 为准）：

```text
## Summary
- Approve character/scene references per view, with legacy reference compatibility.
- Inject up to three existing views plus one approved work-style reference into Seedream asset generation.
- Add formal-art quality constraints to generation prompts and verify approved-file SHA before use.
- Add basic-mode reference/style readiness and a single-shot rework entry.

## Verification
- 416 Python tests, 23 JS tests, ruff.
- Browser check: per-view approval controls and basic-mode readiness/rework entry.

## Not verified
- No real paid Seedream/Wan/MiniMax/Dify calls this round.
- No human art review of low-poly/facial quality or scene continuity.
```

## 6. 独立审查建议

请 ChatGPT 重点审查：
1. `luma/visual.py` 的多视图唯一性与 legacy 推导是否符合预期。
2. `luma/studio.py` 中 `approve_imported_reference`、`asset_view`、`storyboard_packet`、`asset_image_packet` 的一致性。
3. `luma/domestic_media.py` 的参考顺序契约是否与真实 Seedream API 行为一致。
4. `web/js/cast.js` 的逐视图批准与场景视图上传是否存在状态遗漏。
5. 任何将模拟或界面验证误写成真实生产验证的表述。

## 7. V0.5.1 增量验收

日期：2026-11-22
起点：`9a0de59`（PR #5 原 Head）

### 已修复

- **P0 参考图越权**：`asset_image_packet` 不再把同版本未批准视图放进模型请求；默认只使用已批准/旧版批准视图。存在视图但无批准时会阻塞；使用未批准视图必须显式确认，并返回 `approval.excluded`、`requires_approval` 与报价预览。
- **P0 分镜参考**：`storyboard_packet` 不再回退到未批准主图；有图无批准时给出“去批准参考”的可操作错误。
- **P0 版本语义**：新版本不继承旧版本批准；选用/恢复版本不改变镜头绑定；界面显示批准数、视图数、绑定镜数；新增视图前确认“创建新版本、批准不继承、绑定不变”。
- **P0 风格感知**：新增 `luma/art.py`，区分二维动画/赛璐璐、国漫插画、电影写实、自定义；动画不再被强制要求真实皮肤或摄影级写实；风格信息进入资产、分镜与图生视频提示。
- **P1 证据**：候选与交付页显示证据类别、模型、请求号、估价/实扣、人工评分与采用状态；明确“供应商记录”不等于真实 API 验收，缺失 job 标为无供应商记录。
- **P1 返工**：回归确认单镜返工只修改目标镜头；基础模式提示作用范围并提供受阻时的批准入口。

### 测试证据

- Python：`431 passed`（新增 15 项：批准门禁 5、风格 6、版本/返工/证据 4）。
- JavaScript：`23 passed`。
- Ruff：`All checks passed!`。
- 浏览器：项目加载、5 项美术风格选择、资产版本 `1/1 已批准` 与绑定数、基础制作步骤可见；无控制台错误。
- 未执行真实付费 Seedream / Wan / MiniMax / Dify；未做人工成片画质评审。

### 仍需验收

- 真实多视图定妆、动画风格成片、角色一致性与场景连续性。
- 真实供应商账单与实际费用核对。
- 新用户完整任务、移动端与长项目体验。

## 8. V0.5.3 增量验收

日期：2026-11-22
起点：`a80d646`（Codex 审计修复后的 HEAD）

### 已修复的最后一个 P1

- `preparation.report` 的批准门禁不再以 `visual_bible.references` 是否存在为前提；Legacy 作品同样不能把未批准资产图静默送入制作准备、首帧、视频报价或正式提交。
- `preparation.catalog` 始终返回每个资产视图的 `approved` / `approval_status`；未批准视图仍可预览、编辑和迁移，只是不能静默生成。
- 可选显式确认：`allow_unapproved` 从报价、冻结包、任务快照一直传到后台重建，报价 digest 与提交参数必须一致；使用未批准图时返回 `approval.unapproved` 与提示文本，且不会写入批准记录。
- 后台执行重建 `preparation.freeze` 保留本次确认选项；未确认任务不会因重建被“洗白”。
- 报价增加本机确认记录与 30 分钟有效期；过期报价或变化后的参考文件在提交时被拒绝，且不扣减授权、不创建任务。
- 版本切换、选用不修改已绑定镜头；新版本不继承旧版本批准。
- 本机导入素材的预览与普通编辑不受门禁影响。

### 测试证据

- Python：`456 passed`（新增 `tests/test_v05_3_legacy_gate.py` 7 项；更新准备/媒体测试夹具以显式批准参考）。
- JavaScript：`23 passed`。
- Ruff：`All checks passed!`。
- 浏览器：项目加载、高级制作面板、未批准提示与确认开关、基础流程；无控制台错误（见 PR #5 说明）。
- 未执行真实付费 Seedream / Wan 调用。

### POC-01

真实验收预案见 `docs/poc-01-real-generation.md`：A 定妆 ¥0.12、B 分镜 ¥0.12、C 5 秒视频 ¥0.75，合计 ¥0.99；隔离环境已生成报价，等待单次授权。

### 仍未验收

- POC-01 三个真实请求与成片画质。
- 真实账单与实扣费用对账。
- 新用户完整任务、移动端与长项目体验。

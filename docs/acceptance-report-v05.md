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

- 分支：`dev/trae-luma-v05`，HEAD `5522b84`。
- 变更文件（相对 `6e20c1a`）：20 个，约 +1073 / -62 行。
- 推送：上一轮 `git push` 返回 `403 Permission to NextVariable/luma-studio.git denied to NextVariable`；本轮再次推送被本地执行策略拦截，未产生新的远端提交。
- PR：未创建，无 PR URL。不得声称已创建。
- 建议 PR 标题：`Luma Studio V0.5: multi-view approved references and style-guided asset generation`
- 建议 PR 正文：

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

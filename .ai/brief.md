# 任务简报（第 2/2 轮）：时间条件的画布接线（匹配模块参数 + 自动铺 + 执行管线）

> 第 1 轮已完成并通过审查：`date_parser`、models 字段、store（`set_document_date`/`get_document_date` 回退/`get_amount_matches(time_tolerance_days)` 组合区间语义）、OCR 落库。本轮把时间条件接入画布 UI 与执行链路。

## 规格

### 1. 匹配模块参数（model + 配置面板）

- `FlowNode.params` 增加 `time_tolerance_days: int = 7`（默认 7 天）与 `time_unlimited: bool = False`（不限制时间；勾选时忽略天数）
- 配置面板（`config_dialog.py`）「匹配」模块区域新增：
  - `时间容差 ≤ N 天`（QSpinBox，0~365，默认 7；0 = 必须同日）
  - `不限制时间`（QCheckBox；勾选时禁用天数框）
  - 说明小字：「按票面日期（识别失败回退文件时间）比较两侧最近距离」
- 节点卡片摘要（`items.py`）增加时间条件显示：`≤7天` / `同日` / `不限时间`

### 2. 自动铺带时间条件

- `match_flow_dialog._build_candidate_chains`：`store.get_amount_matches(time_tolerance_days=7)`（默认值；不改引擎调用以外的行为）
- 画布无候选时的提示文案补充「（可能因时间条件被排除，可在匹配模块调大容差或选择不限制）」

### 3. 执行管线逐链时间校验

- `_on_confirm` 逐支线校验除金额差外增加**时间校验**：
  - 取链发票侧与支付侧绑定文件的日期区间（复用 `store.get_document_date`，组合成员展开取 min/max）
  - 链有效条件：金额差 ≤ tolerance **且**（time_unlimited 或 区间最近距离 ≤ time_tolerance_days）
  - 跳过原因区分：`金额差超出容差` / `时间差超出容差（X 天 > N 天）`，汇总进 result_summary.skip_reasons
- 一键「确定」文案不新增要求，沿用现结构

### 4. 预览面板日期展示（帮助人工核对）

- `preview_panel` 文件列表项附加日期显示：`文件名 · 2026-07-09（票面/文件）`（来源标注见 store 回退返回的 source）

## 验证要求（Codex）

1. 离屏真实对话框（临时 store，构造时间相近/超差数据）：
   - 自动铺：默认 7 天 → 仅时间接近的候选铺出；调 `time_unlimited=True` 后候选变多（重铺或直接断言引擎调用参数）
   - confirm：时间超差的链跳过且 skip_reasons 含「时间差」；金额差的链原因不变
   - 配置面板：SpinBox/复选框联动（勾不限制→天数禁用）、保存后 node.params 正确、卡片摘要文案正确
   - 预览面板列表项含日期与来源标注
2. 回归：金额条件/组合/端口拖线/框选/confirm 计数；`D:/Using_small_tools/Git/bin/bash.exe scripts/check.sh` 全绿
3. 离屏脚本退出用 exec 循环或 sys.exit；临时脚本用后清理；不新增依赖、不改用户数据、不 commit

## 备注

- store.py 已 904 行（超 800 约束）→ 记 backlog 待专项拆分，本轮不动
- 本轮完成后与第 1 轮一并提交推送（Claude 审查后）

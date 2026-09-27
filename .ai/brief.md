# 任务简报：匹配时间参数持久化 + 金额页显示识别日期

## 问题 1（P1）：匹配模块的时间设置在重开画布后丢失

**现象**：用户在自动比对画布的「匹配」模块里改了时间容差 N 天，关闭后重新点「自动比对」，又变回 7 天——设置无法生效。

**Root cause**：画布设计为每次打开空白重铺，自动铺硬编码 `store.get_amount_matches(time_tolerance_days=7)`，新匹配模块 params 也用默认值；用户设置只存在于内存画布。

**修复规格（偏好持久化）**：
- 用现有 `AppConfig`（`app/core/app_config.py` 的 `get/set/save`）持久化匹配默认参数：
  - `match_time_tolerance_days`（默认 7）
  - `match_time_unlimited`（默认 false）
  - `match_amount_tolerance`（默认 0.01，**一并持久化**——金额容差同样存在重开丢失问题，语义一致）
- 自动铺：读偏好 → `get_amount_matches(tolerance=偏好金额, time_tolerance_days=None if unlimited else 偏好天数)`
- 新建匹配模块（拖入画布）：`params` 初始化为偏好值（不再写死 7）
- 配置面板保存匹配模块时：写回 node.params **并** `AppConfig.set(...)` + `save()` 同步偏好
- 「匹配」模块卡片摘要、无候选提示文案逻辑不变
- 说明：`config/app_config.json` 是用户偏好文件，本次通过 `AppConfig.set` 正常写入（属该文件用途）；`data/store.json` 仍不可动

## 问题 2（P2）：金额页（OCR 识别）显示识别出的时间

**需求**：OCR 识别界面不止显示识别金额，还要显示识别出的时间（票面日期/支付时间）。

**规格**：
- `amount_page` 表格新增「日期」列，位置在「文件名」之后（列序：文件 / 日期 / 识别金额 / 编辑金额 / 确认）；同步调整 `_configure_columns`、行填充、单元格编辑/确认逻辑中的列索引
- 显示内容：OCR 识别日期（`YYYY-MM-DD`）；未识别到时显示 `—`（灰字）
- OCR 完成后随金额一起刷新该行日期（`_on_ocr_finished` 路径已有日期落库，读取 store 的 `get_document_date` 结果）
- 现有「识别金额 / 编辑金额 / 确认」行为与布局不回归（表格最小高度/行高/滚动等保持不变或微调适配）

## 相关文件
- `app/core/app_config.py`（DEFAULTS 增加三个键）
- `app/ui/widgets/match_flow_dialog.py`（自动铺读偏好；新模块初始化偏好）
- `app/ui/widgets/match_flow/model.py`（默认 params 可保留现状，由 dialog 注入偏好）
- `app/ui/widgets/match_flow/config_dialog.py`（保存时同步写偏好）
- `app/ui/pages/amount_page.py`（日期列）
- 需要时 `app/app_entry.py`/页面构造处确认 AppConfig 获取路径

## 验证要求（Codex）
1. 持久化：临时 AppConfig → 配置面板改 N=15 保存 → 断言 config 键值；新建 MatchFlowDialog → 自动铺传参/新匹配模块 params = 15；unlimited 勾选同理；金额容差一并断言
2. 金额页：构造含票面日期与无日期的文件 → 表格日期列显示 `2026-07-09` 与 `—`；OCR 落库后刷新断言；列索引调整后编辑金额/确认仍正常（回归）
3. `D:/Using_small_tools/Git/bin/bash.exe scripts/check.sh` 全绿；离屏脚本用 exec/sys.exit 退出；临时脚本用后清理
4. 不新增依赖；`data/store.json` 不改（测试用临时 store/config）；不 commit，交 Claude 审查后提交

# 任务简报：金额页日期列 显示重叠 + 选择器放大

## 问题（人类 2026-09-28 真机反馈）

1. **日期字体重叠**：计算金额模式中，发票文件一列的日期文字出现重叠（视觉挤压）
2. **日期选择器太小不好用**：内嵌 QDateEdit 与弹窗都偏小，点选困难

## 修复方向

### 1. 定位重叠根因（先实证再改）
- 离屏 grab `DateEditCell`（含"未设置"与正常日期两种态）→ 像素/几何分析：文本绘制区与日历下拉按钮/清除按钮是否重叠；`DATE_COL_WIDTH` 当前值是否不足；Qt 样式下 `specialValueText` 与 drop-down 的布局挤压
- 汇报根因后修复（预计：列宽不足 + QDateEdit 文本区未给 drop-down 留 padding）

### 2. 放大与易用性（含具体参数，可按实测微调）
- `DateEditCell`：QDateEdit 高度 36→**40**、字号显式 **13px**、文本左 padding 加大、drop-down 宽度 ≥ **26px**（样式 `QDateEdit::drop-down`）；清除按钮高度同步、宽度略增
- `amount_page`：`DATE_COL_WIDTH` 增加到 **190~210**（保证 日期文本 + 下拉按钮 + 清除按钮 三者不挤压）
- **日历弹窗放大**：为 QDateEdit 的 calendarPopup 设置 QCalendarWidget 样式（导航栏高度、星期/日期单元格 `min-width:30px; min-height:28px`、字号 13px、选中/今天高亮沿用 Elegant Light 蓝），使弹窗明显大于默认
- 若实测发现 QDateEdit 弹出日历放大受限明显、体验仍差 → 备选方案「点击单元格弹出独立大日历对话框（QCalendarWidget 放大 + 今天/清除/确定）」，在汇报中给建议与取舍，不擅自切换

### 3. 验证要求
- 离屏 grab：修复前后各一张日期单元格截图（正常日期 + 未设置），以及日历弹窗放大后截图（`_tmp_diag/` 留存供审）
- 几何断言：QDateEdit 文本显示区与 drop-down/清除按钮矩形不相交；列宽 ≥ 文本宽 + 按钮宽
- 回归：日期手动编辑/清除/OCR 覆盖保护逻辑不变；金额编辑/确认列交互正常；`check.sh` 全绿
- 离屏脚本 exec/sys.exit 退出；临时脚本用后清理；不新增依赖；不改用户数据；不 commit（Claude 审查后按规则提交）

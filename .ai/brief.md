# 任务简报：金额页日期列可手动编辑

## 需求（人类 2026-09-28）

「计算金额模式」中，文件的日期需要**可手动修改**——有些日期识别错误或没有日期，需要人工修正。

## 规格

### 1. 新控件 `app/ui/widgets/date_edit_cell.py`：DateEditCell

- 复用「编辑金额」列（`amount_edit_cell.py`）的交互范式：内嵌控件 + `committed` 信号（值：`YYYY-MM-DD` 或 `""` 表示清除）
- 用 **QDateEdit**（日历弹出，`setCalendarPopup(True)`）；**空值表示**：用 `setSpecialValueText("未设置")` + `minimumDate(=1900-01-01)` 双重语义——显示"未设置"即无日期；另给「清除」按钮（清空 → 提交空值）
- 载入时：有日期 → 设置该日期；无 → 显示"未设置"
- 视觉与金额编辑单元格一致（无边框/透明背景、聚焦时高亮）
- 日期口径：仅日期（无时间）

### 2. 源语义扩展：`source="manual"`

- 手动设置 → `store.set_document_date(kind, fid, date_iso, "manual")`
- **清除** → `set_document_date(kind, fid, "", "")`（空值回退文件修改时间，引擎语义不变）

### 3. 联动显示（manual 与 ocr 同等对待）

- `amount_page` 日期列：改为承载 DateEditCell（`setCellWidget(行, 1)`）；显示规则改为「有 document_date（ocr 或 manual）→ 显示日期；否则 —」
- `file_list_panel`（比对页）`_set_date_cell`：判定改为「`document_date` 非空」即显示票面/手动日期（不再只认 `source=="ocr"`）；tooltip 区分来源：`票面日期（OCR 识别）` / `手动设置` / 回退时 `文件修改时间（未识别到票面日期）`
- `preview_panel` 标注：`（票面）`/`（手动）`/`（文件）`（当前仅票面/文件两态）

### 4. OCR 不覆盖手动日期（重要）

- `amount_page._persist_ocr_document_date`：仅当当前条目 `document_date_source != "manual"` 时才写入 OCR 日期（手动修正优先，重跑识别不丢失）
- merge 重扫保留逻辑无需改（已有 document_date 即保留）

## 相关文件

- 新增 `app/ui/widgets/date_edit_cell.py`
- `app/ui/pages/amount_page.py`（日期列控件化/显示规则/OCR 不覆盖）
- `app/ui/widgets/file_list_panel.py`、`app/ui/widgets/match_flow/preview_panel.py`（来源显示扩展）

## 验证要求（Codex）

1. 控件：设置日期 → store 落库 `source="manual"`；清除 → 落空且界面显示"未设置"；重新载入表格显示正确
2. 不覆盖：先手动设置日期，再模拟 OCR 完成写入 ocr 日期 → store 中仍为手动值与 `manual` 来源；未手动过的文件 OCR 正常写入
3. 联动：比对页与预览面板对 manual 来源显示日期与对应 tooltip/标注
4. 回归：金额编辑/确认列交互、表格列索引（日期列现在是控件）、比对页日期列、`D:/Using_small_tools/Git/bin/bash.exe scripts/check.sh` 全绿
5. 离屏脚本 exec/sys.exit 退出；临时脚本用后清理；不新增依赖；不改用户数据（测试用临时 store/config）；不 commit（Claude 审查后按规则提交）

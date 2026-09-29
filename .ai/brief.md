# 任务简报：外部重命名自愈 / 失效关联清理 / 关联信息导出 Excel

人类 2026-09-29 真机反馈三项。三项互有耦合（1 的自愈会消掉 2 的一部分脏数据），请一并实现。

---

## 1. 在资源管理器里重命名文件后：组合成员掉队 + 关联/OCR 丢失，且需要单文件重命名

### 现象（人类描述）
在文件夹中把发票/图片改名后重新扫描：
- 该文件**从组合里掉了出来变成顶层独立文件**，但组合仍显示旧的成员数量（统计没跟上）
- 计算金额模式里必须**重新跑 OCR**（金额/票面日期丢了）

### 根因（Claude 已定位，请复核）
`models.generate_file_id = sha1(abs_path|modified_iso)` —— **路径参与了 id**。改名 → 路径变 → id 变：
1. `merge_*`（`store.py:103-180`）把未扫到的旧记录标 `missing=True`（**记录仍在**，组合/关联仍指向它）
2. 新路径扫进来是一条**全新记录**：无关联、无金额、无票面日期
3. 面板渲染组合成员时只从「非 missing」文件里取（`file_list_panel._populate_tree`）→ 组合里的旧 id 取不到 → 该成员不显示；但 `len(combo['file_ids'])` 没变 → **组合仍显示旧成员数**
4. `_prune_shell_combos` 只在「全部成员 missing」时才清理 → 单个成员掉队时组合留着残骸

### 修复：重扫时做「改名自愈」（识别同一文件的新旧记录并接管）
在 `merge_invoices` / `merge_payments` 中，**标记 missing 之后、`_prune_shell_combos` 之前**执行：
- 对每条**新记录**（store 中不存在的 id），在 **missing 记录**里找候选：`size_bytes`、`modified_iso`、`ext` **三者全等**的同类记录
- **唯一候选** → 视为同一文件被改名：
  - 继承：`amount`（OCR 金额）、`document_date` / `document_date_source`（票面/手动日期）、
    `linked_payment_ids`（或 `linked_invoice_ids`）
  - 用**新的 file_id** 建记录（**不要复用旧 id**！id 由路径生成，复用会导致下次重扫又对不上、记录反复翻转）
  - 交叉引用重映射：`linked_*_ids`、`associations`、`combos[*].file_ids`（复用 `store._remap_file_ids(old_to_new)`）
  - 删除那条旧的 missing 记录（避免它被后续文件重复认领）
  - **记录日志**：把 (旧名 → 新名) 记入本次 merge 的返回值或 store 内存字段，供 UI 提示「已自动识别 N 个改名文件」
- **多个候选**（同 size+同 mtime+同扩展名）→ **不猜**，跳过该条（宁可漏修不可错配）
- 匹配与规划逻辑放**新的纯逻辑模块** `app/core/file_identity.py`（Qt-free，可单测），store 只调用

### 同时新增：右键单文件「重命名」（应用内改名，不走文件系统外部改名）
- 文件行右键菜单新增 **「重命名」**（顶层独立文件与组合成员文件都可用）
- 输入新基名（默认=当前文件名去扩展名）→ `store.rename_group([fid], [], 名)` / `rename_group([], [fid], 名)`
  （现有实现已会重映射 `combos[*].file_ids`、`linked_*_ids`、`associations`，**组合成员身份、关联、金额、日期全部保留**）
- 成功后 `reload_from_store(keep_view=True)`（**不要 advance**，单文件改名后停在原位）
- 冲突（目标名已存在）→ 现有失败分支提示即可

**验收**：外部改名后重扫 → 文件仍在原组合中（组合成员数一致）、关联仍在、金额与票面日期仍在（无需重跑 OCR）；应用内右键改名 → 同上。

---

## 2. 关联对象被改名/删除后：状态徽标仍计为「已关联」且无法取消

### 现象（人类描述）
- 关联错了 → 把发票改名/删除 → 图片状态栏仍显示「已关联」，但**无法取消关联**（另一侧已选不到那条记录）
- 再与别的发票关联后，数量**累加**：关联一个 2 文件组合后状态显示「已关联 3」（2 有效 + 1 失效）

### 根因（Claude 已定位）
- `file_list_panel._link_state`（约 :540）用 `len(partner_ids)` 直接数 `linked_*_ids` 的**原始条数**，
  不校验对象是否还存在/是否 missing → 失效记录照样计数
- `_partner_entries`（约 :568）**跳过 missing/不存在的对象** → 展开子行、「取消所有关联」都碰不到这些失效 id
  → 用户没有任何入口能清掉它们
- `_on_unlink`（按钮）要求两侧都有选中项，失效对象在另一侧根本选不到 → 死锁

### 修复
- **计数只算有效关联**：对象记录存在且 `missing == False`
- **失效条数要可见**：徽标文本/颜色给出提示（例如有效 2 条时显示「已关联 2」，另有失效时追加「⚠1」或换警示色；
  78px 宽度不够就沿用现有 `setFixedSize` 调整或 tooltip 补充，**具体表现由实现决定，但必须让人一眼知道存在失效关联**）
- **新增清理入口**：文件行右键菜单新增 **「清理失效关联」**（仅在该文件确有失效关联时出现）
  → store 新增 `prune_dangling_links(file_id)`（或按 kind 全局清理，二选一，说明理由）：
  删除指向「记录不存在 / missing」对象的 `linked_*_ids` 与 `associations` 条目
- 「取消所有关联」也应**连带清掉**该文件的失效 id（用户点它时语义就是"清空我这边全部关联"）
- （本项与 1 的自愈有协同：外部改名会被 1 自动修复，本项主要处理**删除**与历史脏数据）

**验收**：构造「关联 → 删除一侧记录」与「关联 → 外部改名」两种脏数据 →
徽标不再把失效计入；右键「清理失效关联」后失效条目消失、计数正确；再关联新对象时数量正确（不再 2+1=3）。

---

## 3. 导出关联信息为 Excel

- 比对关联模式**按钮行**新增 `[导出 Excel]`（放在「重命名关联」右侧；样式 type="default"）
- 点击 → `QFileDialog.getSaveFileName`（默认文件名 `关联信息_YYYYMMDD.xlsx`，过滤 `*.xlsx`）→ 生成文件 → 成功提示（含条数与路径）
- **内容**：一行一条「发票 ↔ 支付记录」关联，列建议：
  `发票文件名 | 发票金额 | 发票日期 | 支付记录文件名 | 支付金额 | 支付日期 | 所属组合 | 关联方式`
  - 金额取 `amount.final_amount`（无则留空）；日期取 `store.get_document_date(file)`（票面/手动/回退文件时间，来源可加备注列或后缀）
  - 组合列：文件属于组合时写组合名，否则留空
  - 关联方式：`自动` / `手动`（`store.is_auto_linked`）
  - 只导出**有效**关联（对象存在且非 missing）；未关联的文件不出现（不做额外汇总页）
- **实现约束（重要）**：**不新增第三方依赖**。当前 venv 里 `openpyxl` / `xlsxwriter` 都**没有**，
  `pandas` 虽在但只是传递依赖（不在 requirements.txt）且写 xlsx 同样需要上述引擎 → **用标准库自己写最小 xlsx**
  （`zipfile` + XML：`[Content_Types].xml` / `_rels/.rels` / `xl/workbook.xml` / `xl/_rels/workbook.xml.rels` /
  `xl/worksheets/sheet1.xml`，字符串用 `inlineStr` 即可，数字写成 number）：
  - 新模块 `app/core/excel_export.py`（Qt-free）：
    `build_association_rows(store) -> list[list[str|float]]`（表头 + 数据）
    `write_xlsx(path, rows, sheet_name="关联信息") -> None`
  - **XML 转义必须有**（文件名可能含 `& < > " '`）；空值写空字符串；浮点保留 2 位（写成 number 或格式化字符串，二选一说明）
  - 模块末尾放 `if __name__ == "__main__":` 自检（生成临时文件 → 用 zipfile 重新读回校验关键 XML 片段/行数）
- UI 侧只做：取文件名、调用 core、提示成功/失败（**业务逻辑不得写在 UI 里**）

**验收**：导出后用 Python 标准库读回（`zipfile` + `xml.etree`）校验：文件可被 ZIP 打开、必要成员齐全、
行数 = 有效关联对数 + 1（表头）、首行表头正确、抽查某行的文件名/金额与 store 一致、含中文与特殊字符的文件名不破坏 XML。

---

## 验证要求（Codex 必须给出可复现证据）
1. 离屏断言脚本（`_tmp_diag/`，用后清理，退出用 exec/事件循环或 `sys.exit()`）：
   - **改名自愈**：建 6 发票 + 1 组合（含该发票）+ 关联 → **在磁盘上真实 `os.rename`** → 重新扫描
     → 断言：文件仍在组合中（`combo['file_ids']` 指向新 id）、组合成员数与显示一致、关联仍成立、
     金额与 `document_date` 已继承、旧 missing 记录已删除、列表不出现孤立顶层项
   - **歧义不猜**：构造两条同 size+同 mtime+同扩展名的 missing 记录 → 断言跳过（不匹配）
   - **失效关联**：删除一侧文件后重扫 → 徽标不计失效（或明确标注）、右键「清理失效关联」后条目消失、
     再关联新对象计数正确（不相加）
   - **导出 Excel**：真实导出到临时目录 → 用 zipfile+ElementTree 读回断言（见上）
2. **应用内右键重命名**：组合成员改名后仍在组合中、index 不变、关联/金额保留
3. `bash scripts/check.sh`（Windows：`D:/Using_small_tools/Git/bin/bash.exe scripts/check.sh`）全绿
4. 约束：**不新增依赖**；不改 `data/store.json` / `config/app_config.json` 用户数据；`app/core/` 保持 Qt-free；
   不 commit；**不要动与本次无关的文件**（历史上曾误改 `main.py`）
5. 文件规模：`store.py` 954 行、`file_list_panel.py` 1020 行（均已超 800 约束）——
   新逻辑放新模块（`file_identity.py` / `excel_export.py`），`store.py` 只加薄调用；把这两处超限记入 backlog 而不是继续堆大

## 非目标
- 不做「按内容哈希」的通用文件身份（本轮只用 size+mtime+ext 启发式）
- 不做未关联文件的汇总页/多 sheet；不改画布
- 不自动删除失效关联（**不静默丢数据**，只提供显式清理入口 + 正确计数）

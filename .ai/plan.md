# 方案设计

> 由 Codex 在分析需求后写入。Claude Code 审查时参考。
> 本方案对应 `.ai/brief.md`（7 项功能增强，分 A/B 两阶段）。

## 需求分析

在「比对关联模式」中新增「组合（Combo）」概念：同一列表内的多个文件可组合，
组合作为整体参与金额求和、批量关联与自动比对。同时补齐父行「取消所有关联」、
将自动比对二级界面重写为「关联组」容器模型（多对多、可拖动、同步滚动）。

## 总体设计（对应 D1–D3）

### D1. Store 组合数据模型（app/core/store.py）
- `_load()` / `_empty_data()` 增加 `combos` 段（`setdefault("combos", [])`，向后兼容）。
- 新增方法（均加锁 + `_save()` + `_notify()`）：
  - `create_combo(kind, name, file_ids) -> combo_id`：`cb_<16hex>`，成员有序去重、仅保留非 missing 文件。
  - `delete_combo(combo_id) -> bool`
  - `get_combos(kind) -> list[dict]` / `get_combo(combo_id) -> Optional[dict]`
  - `add_combo_files(combo_id, file_ids)` / `remove_combo_file(combo_id, file_id)`
  - `get_combo_total(combo_id) -> float`：成员 `final_amount` 求和，round 2，跳过 missing/无金额成员。
- 组合与文件相互独立：文件不反向记录所属组合，树的层级由 `combos` 段推导。

### D2. FileListPanel 三层树（app/ui/widgets/file_list_panel.py）
- 顶层项两类：**独立文件**（不在任何组合中）与**组合父行**（名称=组合名、
  金额=`¥ 总和`、默认展开，子项=成员文件；成员文件可再展开显示关联对象子行）。
- 组合父行按「首个成员文件在原文件顺序中的位置」插入，序号列统一编号；
  成员文件子行不再独立编号（保留其原 file_id 供定位/关联）。
- 新增角色 `ROLE_COMBO_ID`：组合父行存 combo_id；成员文件行存所属 combo_id。
- 选择模式改 `ExtendedSelection`（支持 Ctrl 多选）。
- 树填充：`_populate_tree(files)` 读取 `store.get_combos(kind)` 推导层级；
  组合成员既不入独立顶层项。`_item_by_fid` 同时登记成员子行（定位/选中可用）。
- 层级着色：`_HierarchyTree.drawRow` 改为按行角色绘制——
  关联子行（有 `ROLE_PARTNER_ID`）保留浅蓝底+主色强调条；成员文件行用极浅灰底
  区分层级；组合父行与独立文件保持白底。
- 右键菜单：
  - 关联子行：复制文件名 / 定位文件（现状保留）。
  - 独立文件父行：已关联 → 「定位所有」+「取消所有关联」（确认后逐个
    `remove_association`，Store notify 自动刷新两面板）；未关联 → 无菜单。
  - 成员文件行：同上（视为普通文件行）。
  - 组合父行：「取消组合」（确认后 `delete_combo`，成员恢复独立顶层项）；
    任一成员已关联时另提供「定位所有」「取消所有关联」。
  - 多选（≥2 个顶层独立文件）：「组合」→ `QInputDialog` 输入名称 →
    `store.create_combo(kind, name, ids)` → 发 `combosChanged` 信号。
- 新信号 `combosChanged = Signal()`：组合增删后由 ComparePage 触发两侧重建树。
- 金额实时计算：组合父行金额列在 `_populate_tree` / `refresh_status` 中调用
  `store.get_combo_total`；`refresh_status` 同步刷新成员金额与组合总和。

### D3. 自动比对匹配扩展（app/core/store.py）
- `get_amount_matches()` 改为「单元↔单元」匹配：单元 = 单文件（非组合成员）或
  组合（成员 `final_amount` 求和）。匹配组合↔单文件、单文件↔组合、组合↔组合；
  任一成员已关联即跳过；missing 文件跳过；无金额单元跳过。
- 返回结构（破坏性变更）：
  `{"invoice_ids": [...], "payment_ids": [...], "invoice_name", "payment_name", "amount", "is_combo_invoice", "is_combo_payment"}`。
- `batch_link(pairs, auto_linked=True)` 契约改为接收
  `{"invoice_ids": [...], "payment_ids": [...]}`（两两组合内部成员）；
  同时兼容旧 `invoice_id`/`payment_id` 键，避免遗漏调用点。

## 阶段 A：文件列表侧组合（功能 1–4）

1. `store.py`：combos 段 + CRUD/求和 + `get_amount_matches`/`batch_link` 改造。
2. `file_list_panel.py`：三层树、多选、右键菜单（取消所有关联/组合/取消组合）、
   组合金额实时计算、`combosChanged` 信号、`get_selected_combo()`。
3. `compare_page.py`：
   - `_update_link_buttons` / `_on_link` 支持 组合↔文件、组合↔组合 批量关联
     （`batch_link` 两两组合，`auto_linked=False`）。
   - 连接 `combosChanged` → 两侧 `reload_from_store()` 重建树。
   - `_on_store_changed` 保留 `refresh_status()`（展开状态不丢、金额/总和实时更新）。

## 阶段 B：自动比对二级界面（功能 5–7）

1. `auto_match_dialog.py` 重写为「关联组」模型：
   - 左右两个 `QTreeWidget`，一行=一个「关联组N」（顶层项，默认展开、不可拖动，
     可接受 drop）；子项=组内文件（可拖动换组）。
   - 即使单文件也包组；空组在确定前保留（组标题显示「（空）」）。
   - 右键组内文件：「取消关联」（移出本组）/「添加关联」（从对话框当前候选池中
     选同类型文件加入本组）。
   - 两侧纵向滚动条同步（valueChanged 互连，带防递归标志）。
   - 构造入参 `(matches, store=None)`：由 store 解析成员文件名/金额显示。
   - `accepted_pairs()`：按组索引对齐，左组发票 × 右组支付 两两组合，返回
     `{"invoice_ids": [...], "payment_ids": [...]}`；任一侧为空组 → 跳过该行。
2. `compare_page.py`：`AutoMatchDialog(self._match_pairs, store=self.store)`
   构造；`Accepted` 后直接 `batch_link(pairs, auto_linked=True)`。

## 验收与验证

- 每阶段结束运行 `D:/Using_small_tools/Git/bin/bash.exe scripts/check.sh`
  （系统 PATH 中的 bash 为 WSL，Hyper-V 不可用会报错，故用 Git Bash 显式调用）。
- 不修改 `data/store.json`、`config/app_config.json`，不新增第三方依赖。
- 风格对齐 Elegant Light（白色背景、#409eff 主色、圆角、Microsoft YaHei）。

## 风险与注意事项

- `batch_link` 是破坏性契约变更，全仓调用点仅 `compare_page.py`（两处），已排查。
- 组合为空（成员全 missing）时 `_populate_tree` 跳过渲染，避免空壳父行。
- 多选「组合」仅对顶层独立文件生效；选中含组合父行时不提供「组合」。
- 右键菜单用 `QMessageBox.question` 确认（MkMessage 无 confirm 方法）。

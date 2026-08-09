# 任务简报

## 当前任务

在「比对关联模式」中实现 7 项功能增强：父行取消所有关联、文件多选组合、组合批量关联、组合金额自动计算、组合自动对比、自动比对二级界面组合优化、关联项组合显示。

## 总体设计决策（已定，Codex 遵循）

### D1. 组合（Combo）数据模型 —— 持久化到 Store
新增 `combos` 数据段到 `data/store.json`，Store 是唯一真相源：

```json
"combos": [
  {
    "combo_id": "cb_<16hex>",
    "kind": "invoice",          // "invoice" | "payment"
    "name": "打车费",
    "file_ids": ["f1", "f2"],   // 成员文件 file_id（有序、去重）
    "created_at": "2026-..."
  }
]
```

Store 新增方法（`app/core/store.py`，均加锁 + `_save()` + `_notify()`）：
- `create_combo(kind, name, file_ids) -> combo_id`
- `delete_combo(combo_id) -> bool`
- `get_combos(kind) -> list[dict]`
- `get_combo(combo_id) -> Optional[dict]`
- `add_combo_files(combo_id, file_ids)`  / `remove_combo_file(combo_id, file_id)`
- `get_combo_total(combo_id) -> float`（成员 `final_amount` 求和，round 2 位；跳过 missing/无金额成员）

`_load()`/`_empty_data()` 增加 `combos` 段（向后兼容，`setdefault("combos", [])`）。

### D2. 树结构升级为三层（FileListPanel）
`QTreeWidget` 顶层项由「纯文件」扩展为两类：
- **独立文件**（不在任何组合中）：顶层项，行为与现状一致
- **组合父行**：顶层项，名称列显示组合名，金额列显示 `¥ 总金额`（实时），默认展开；子项为成员文件（正常文件行，可再展开显示其关联对象子行）

成员文件不再作为独立顶层项出现（避免重复）。序号列：独立文件与组合父行按当前顺序统一编号。

新增角色：`ROLE_COMBO_ID`（组合父行存 combo_id，成员文件存所属 combo_id）。

### D3. 自动比对匹配扩展（store.get_amount_matches）
匹配结果从「单发票↔单支付」扩展为「文件组 ↔ 文件组」：

```json
{
  "invoice_ids": ["i1"],         // 一个或多个
  "payment_ids": ["p1"],         // 一个或多个
  "invoice_name": "打车费",       // 组合名或文件名（显示用）
  "payment_name": "...",
  "amount": 123.45,
  "is_combo_invoice": false,     // 是否为组合
  "is_combo_payment": false
}
```

匹配逻辑：
- 单文件金额 ↔ 单文件金额（现状）
- 组合总额 ↔ 单文件金额
- 单文件金额 ↔ 组合总额
- 组合总额 ↔ 组合总额
- 已关联（任一成员已关联）的候选跳过；缺失文件跳过

> 注意：该数据结构变化是**破坏性变更**，`AutoMatchDialog`、`_on_auto_match`、`batch_link` 的调用契约都要随之调整（`batch_link` 改为接收 `invoice_ids`/`payment_ids` 列表）。

## 分阶段实施（每个阶段结束跑 `bash scripts/check.sh`）

### 阶段 A：文件列表侧组合（功能 1、2、3、4）

**A1. 父行右键「取消所有关联」**
- 已关联文件父行右键菜单新增「取消所有关联」
- 点击后弹确认框（MkMessage 确认），确认则遍历该文件所有 `linked_*_ids` 逐个 `remove_association`，刷新两面板
- 菜单项：已关联父行 → 「定位所有」+「取消所有关联」；未关联父行 → 无菜单（现状）

**A2. 多选与组合**
- `FileListPanel.tree` 选择模式改 `ExtendedSelection`（支持 Ctrl+点击多选）
- 多选时右键菜单显示「组合」→ `QInputDialog` 输入组合名 → `store.create_combo(kind, name, selected_ids)`
- 重建树：组合父行默认展开，成员文件作为子项
- 组合父行右键菜单「取消组合」→ 确认后 `store.delete_combo` → 成员恢复独立顶层项
- 限制：组合仅限**同一列表**内文件（天然满足，多选发生在单个面板）

**A3. 组合批量关联**
- 选中组合父行 + 另一列表单文件 → 「关联选中项」按钮可用 → 将组合内**所有**成员与该目标文件逐个建立关联（`add_association` 或 `batch_link`）
- 若组合父行 + 另一列表也是组合 → 两组合所有成员两两关联

**A4. 组合金额实时计算**
- 组合父行金额列显示 `¥ 总和`（round 2）
- 成员金额变化 / 添加移除成员后自动重算（`refresh_status`/`_populate_tree` 时调用 `store.get_combo_total`）

### 阶段 B：自动比对二级界面（功能 5、6、7）

**B1. 组合匹配接入自动比对**
- `get_amount_matches` 返回含组合的结果（D3）
- `_on_auto_match` / `_open_auto_match_dialog` 适配新的 `invoice_ids`/`payment_ids` 结构

**B2. AutoMatchDialog 重写为「关联组」模型**
UI 结构（左右并排两个 `QListWidget`/`QTreeWidget`，一行 = 一个关联组）：
- 每行是一个「关联组」容器：左侧组放发票（可多个），右侧组放支付记录（可多个）
- 组标题用序号命名「关联组1」「关联组2」…，默认展开
- **即使只有一个关联文件**也用组容器包裹
- 组内文件通过自定义数据角色保存 id
- 拖拽：文件可拖到同侧其他组（换组）；空组在确定前保留
- 右键组内文件：「取消关联」（将该文件移出组，组可留空）/「添加关联」（从对话框当前候选池中选**同类型**文件加入组）
- 两侧列表**同步滚动**（滚动一个带动另一个）

**B3. 确定/取消语义**
- 「确定」：按行（组）对齐配对。左组所有发票 × 右组所有支付 两两组合 → `batch_link`。**空组视为无关联，不建立任何关联**
- 「取消」：关闭窗口，无任何关联变更

## 验收标准

- [ ] A1：已关联父行右键「取消所有关联」→ 确认后全部解除，界面实时刷新
- [ ] A2：Ctrl+点击多选 → 右键「组合」→ 命名 → 创建组合父行（默认展开、含成员）；「取消组合」解散恢复
- [ ] A3：组合父行 + 另一列表单文件 → 关联按钮 → 组合所有成员与该文件全部关联
- [ ] A4：组合父行金额列显示成员总和，round 2，成员变化自动更新
- [ ] B1：自动比对能匹配 组合↔单文件 / 组合↔组合
- [ ] B2：二级界面以「关联组N」容器展示（含单文件也包组），可拖动换组、右键增删组内文件、两侧同步滚动
- [ ] B3：确定按组建立关联、空组不关联；取消无变更
- [ ] 全部通过 `bash scripts/check.sh`
- [ ] Elegant Light 主题一致；不破坏现有手动关联/定位/重命名/一键关联功能

## 相关文件

- `app/core/store.py`（combos 数据段 + CRUD + 匹配扩展）
- `app/core/models.py`（如新增 Combo 类型则加；否则用 dict）
- `app/ui/widgets/file_list_panel.py`（三层树、多选、右键菜单）
- `app/ui/pages/compare_page.py`（关联按钮组合逻辑、自动比对适配）
- `app/ui/widgets/auto_match_dialog.py`（重写为关联组模型）

## 备注

- 先读 `AGENTS.md`、`CLAUDE.md`、本 brief，再写 `.ai/plan.md`
- 不要改 `data/store.json` 和 `config/app_config.json`；不新增第三方依赖
- 每个阶段完成跑 `bash scripts/check.sh`，失败修复重跑（最多 3 轮/阶段）
- 结构破坏性变更（D3）请确保 UI 层同步适配，不要遗漏 `batch_link` 调用点

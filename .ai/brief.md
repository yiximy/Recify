# 任务简报：比对关联模式 — 重命名后列表位置保持 + 列表可视行数（布局透气）

人类 2026-09-28 真机反馈（两条）：

1. **重命名关联后列表刷新丢位置**：每次「重命名关联」成功后列表重建，滚动条回顶部，
   要重新往下滑找刚才的位置 / 找刚改名的文件，无法顺手下移重命名下一个。
2. **列表太压抑、看得太少**：本机运行界面上文件列表只显示 **4 行**，布局憋屈、信息量小。

## 已完成的根因定位（Claude 读码确认，Codex 需复核并以其为准修正）

### 根因 1：重命名把条目挤到列表末尾（`app/core/store.py:rename_linked_files`）
- `store.py:305-316` 重新生成 file_id 后做 `del self._data["invoices"][old]; self._data["invoices"][new] = inv`
  → **dict 插入顺序改变，重命名条目被挪到末尾**。
- `get_invoices()/get_payments()` 按 `dict.values()` 顺序返回（`store.py:181-199`），
  `FileScanner.scan_*` 仅在扫描时按文件名排序（`file_scanner.py:72,98`），merge 对已存在条目**原地更新**不改变顺序。
  → 所以重命名后该文件在列表里"跳到最下面"，即使不 clear 也找不到原位。

### 根因 2：重命名后走了整目录重扫 + 树 clear（`app/ui/pages/compare_page.py:342-343`）
- `_on_rename` 调 `panel.restore_folder()` → `_scan_and_load` → `merge_*` + `_populate_tree` → `tree.clear()`
  → 滚动位置、选中项、展开状态全丢（`file_list_panel.py:352`）。
- 重命名只改路径/文件名/ID，**磁盘上没有任何文件增删**，无需整目录重扫；
  `reload_from_store()`（不落盘重扫、无 merge 副作用）已足够。

### 根因 3：布局垂直空间分配（`compare_page.py:77,89`）
- 上下两块用固定 stretch **2 : 3**（列表 40% / 预览 60%），且每个面板上方有 3 条横栏
  （文件夹栏 / 查找栏 / 定位状态栏，定位栏平时为空也占位）。
- 行高：状态徽标 `setFixedSize(78,24)` + `::item padding 6px` → 每行 ≈ **37px**。
- 粗算：列表区 ≈ 710×40% = 284px − 三条横栏 ≈ 97px → 树高 ≈ 187px → **正好 4~5 行**（与人类观察吻合）。

## 修复要求

### A. Store：重命名保持列表位置（`app/core/store.py`）
- 重新生成 file_id 时**保序重键**（不改变键在 dict 中的位置），发票与支付记录都要。
  建议实现：整表重建时把旧键位置替换为新键
  `{new_id if k == old_id else k: v for k, v in d.items()}`（发票/支付各一次）。
- 不改重命名语义（扩展名保留、冲突检查、交叉引用更新、`_save`/`_notify` 行为一律不变）。
- 要求：rename 后 `get_invoices()` 中该文件的 **index 与 rename 前一致**。

### B. 面板：重建树时保留视图状态（`app/ui/widgets/file_list_panel.py`）
- 新增视图状态 = `(当前顶层行 index, 垂直滚动条值, 已展开行的 index 集合)`；
  **按行 index 记录**（不按 file_id —— 重命名后 ID 会变，按 ID 恢复必然失效）。
- `_populate_tree(files, view_state=None)`：填充 + 应用查找/定位过滤后恢复该状态
  （恢复目标行 & 展开项；滚动条值最后 setValue 恢复；两者取合理近似即可）。
- `reload_from_store(keep_view: bool = True, advance: bool = False)`：
  - `keep_view=True` 时先捕获状态、重建后恢复；`advance=True` 时目标行 = 捕获行 index + 1
    （**越界钳制到最后一行**），恢复滚动位置后 `setCurrentItem`（会自然触发 fileSelected → 预览切到下一个）。
  - `advance` 仅在**无查找过滤**时生效（有查询时保持原行，避免语义混乱）。
  - 默认值必须让既有调用（`_on_combos_changed`）也享受 keep_view，行为更连贯。
- 文件夹切换 / 刷新按钮（`_scan_and_load`）**保持现有语义**（新目录回到顶部，不恢复状态）。

### C. 重命名流程（`app/ui/pages/compare_page.py:_on_rename`）
- 成功后不再 `restore_folder()`，改为：
  `invoice_panel.reload_from_store(keep_view=True, advance=True)`、payment 侧同理
  （两侧都往后挪一行 = 顺手下移重命名下一个）。
- 保持现有成功/失败提示文案不变。

### D. 布局透气（`app/ui/pages/compare_page.py`）
- 把「上下两块」改为**垂直 QSplitter**（上=文件列表 splitter，下=预览 splitter）：
  - 默认尺寸偏列表（约 `setSizes([3, 2])` 语义，列表约 58~60%），**用户可拖动分隔条**自行取舍；
  - 列表一侧禁止折叠（`setCollapsible(0, False)`）；预览允许拖到很小（给个 ~120px 最小高度即可）；
  - 保留原有横向 splitter 与 500:500，以及各控件的最小尺寸，不引入水平滚动。
- 每个面板的定位状态栏：无定位时**整行隐藏**（把该行包进一个容器 QWidget 切换 `setVisible`），
  有定位时照旧显示（现有 `lbl_locate_status` / `btn_clear_locate` 属性名保持不变，就近更新逻辑）。
- 紧凑行：`::item padding 6px → 4px`、表头 `padding 8px → 6px`（徽标 24px 不变 → 行高 ≈ 33px）。

## 验证要求（Codex 必须给出可复现证据）

1. **离屏断言脚本**（临时脚本，`_tmp_diag/` 留证据，脚本用后清理）：
   - 构造临时 store：≥12 张发票 + ≥12 张支付（金额各不相同），临时目录 + 真实文件（可空文件）+ 真实 rename 到临时目录；
   - 断言：① rename 后 `get_invoices()` 中该文件 index 不变；② `tree.verticalScrollBar().value()` 重命名前后保持
     （允许 ±1 行像素级误差，需说明取值）；③ 重命名后 `currentRow` = 原行 index + 1（钳制）；
     ④ **可见行数**：1440×920 主窗口尺寸下，列表树内**完整可见行数 ≥ 7**（报告实际值，附 before/after 截图）；
     ⑤ 无定位时定位栏 `isVisible() == False`，`set_located_files([...])` 后 `True`；
     ⑥ 回归：文件夹切换仍回到顶部、查找过滤仍能定位、组合重建仍正常。
   - 退出用 `exec()`/事件循环或 `sys.exit()`（避免裸退出 segfault 干扰）。
2. 截图存 `_tmp_diag/`（重命名前/后列表状态 + 可见行数对比）供审查，脚本用后删除。
3. `bash scripts/check.sh` 全绿。
4. 约束：不新增依赖；不修改 `data/store.json`、`config/app_config.json` 用户数据；`app/core/` 保持 Qt-free；
   `file_list_panel.py` 已 994 行 —— **若改动会超 1000 行，请把「视图状态保持」抽到新文件**
   （如 `app/ui/widgets/list_view_state.py`），不要把文件继续堆大。
5. 不 commit（Claude 审查后按规则提交）。

## 非目标
- 不改重命名语义/冲突处理/扩展名规则；不改扫描排序；不做列表虚拟化；不动画布相关代码。

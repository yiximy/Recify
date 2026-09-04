# 自动比对 → Node-RED 式流程画布：实施方案（v1，待 Claude Code 审阅）

> 对应 `.ai/brief.md`（重构「自动比对」UI）。Codex 已读 AGENTS/CLAUDE/brief，并研读
> store.py / file_scanner.py / models.py / compare_page.py / file_list_panel.py /
> folder_picker.py / auto_match_dialog.py / amount_page.py / main_window.py / scripts/check.sh。
> **本阶段只做方案，未改源代码。** 请 Claude Code 审阅后另行派发实现任务。

## 0. 已确认语义 → 实现映射

| 拍板语义 | 实现映射 |
|---|---|
| 双线入匹配 | 发票/支付模块「输出端」均可连入匹配模块「输入端」（输入端可收多条线）；匹配模块输出端为结果出口、悬空 |
| 替换审阅对话框 | 「自动比对」按钮 → 打开新流程画布（模态二级界面）；删除 `AutoMatchDialog` |
| 文件夹粒度 | 发票/支付模块各绑一个文件夹；同类多模块取**文件夹并集**参与匹配 |
| 删除「是否审阅」开关与一键模式 | 移除 `ToggleSwitch("是否审阅")` / `_review_mode` / `_start_auto_link_mode` / `_match_pairs` 审阅分支；按钮恒为「自动比对」 |

## 1. 文件结构与类划分

### 新增（Qt UI 层；`app/core/` 保持无 Qt）

```
app/ui/widgets/match_flow/__init__.py      # 包说明
app/ui/widgets/match_flow/model.py         # Qt-free：FlowNode / FlowWire / FlowModel + 校验/规划纯逻辑（~200 行）
app/ui/widgets/match_flow/items.py         # FlowNodeItem / FlowPortItem / FlowWireItem：QGraphicsItem 自绘（~320 行）
app/ui/widgets/match_flow/canvas.py        # FlowScene + FlowCanvas：背景网格、平移缩放、拖放接收、连线态、命中删除（~380 行）
app/ui/widgets/match_flow/config_dialog.py # NodeConfigDialog：双击配置面板（~220 行）
app/ui/widgets/match_flow_dialog.py        # MatchFlowDialog(QDialog)：侧边栏+画布+底部按钮+执行编排（~300 行）
```

### 修改
- `app/core/store.py`：`get_amount_matches`/`_build_match_units` 加可选参数；`merge_invoices`/`merge_payments` 加 `mark_missing` 可选参数（均向后兼容，见 §6）。
- `app/ui/pages/compare_page.py`：入口换新对话框、删旧模式（见 §8）。

### 删除
- `app/ui/widgets/auto_match_dialog.py`（连同 compare_page 的 import）。

### 不动
- `data/store.json`、`config/app_config.json`、UI 主题/色系、其余页面、`toggle_switch.py`（理由见 §8）。

### 拆分理由
- 单文件画布逻辑会超 800 行，违反文件聚焦规范；brief 允许 `match_flow/` 分包。
- `model.py` 无 Qt → 校验矩阵与执行规划可脱离窗口做纯逻辑验证。
- 各文件职责单一：items 只管「画什么/命中」；canvas 管「场景交互状态机」；dialog 只做组装与「确定」编排。

### 类职责要点（公开接口草案）
- `FlowModel`：`add_node(kind,x,y)->FlowNode` / `remove_node(id)`（级联删线）/ `can_connect(src_id,dst_id)->(bool,reason)` / `add_wire` / `remove_wire` / `validate()->list[str]` / `build_plan()->FlowPlan`。
- `FlowNodeItem`：持有 `FlowNode`；`itemChange` 上报位移；`mouseDoubleClickEvent` 开配置；右键菜单（配置…/删除模块）；`update_content()` 重绘名称/文件夹/参数摘要。
- `FlowPortItem`（节点子 item）：`is_output` 标志；按下输出端口 → 通知 scene 进入连线态。
- `FlowWireItem`：贝塞尔路径；`shape()` 加宽命中；hover/选中高亮；右键删除。
- `FlowScene`：维护 linking 状态机（临时线/合法目标高亮/非法反馈）、节点↔线同步、删除路由、空白平移、拖放接收、空态遮罩。
- `FlowCanvas(QGraphicsView)`：Ctrl+滚轮缩放、`AnchorUnderMouse`、背景网格（drawBackground）。
- `MatchFlowDialog`：左侧模板栏 + `FlowCanvas` + 底部状态条与「取消/确定」；`_on_confirm` 执行 §7 管线；`result_summary` 供 ComparePage 读取。

## 2. 数据结构（model.py，Qt-free）

```python
NodeKind = Literal["invoice", "payment", "match"]

@dataclass
class FlowNode:
    node_id: str
    kind: NodeKind
    name: str                          # 展示名；默认「电子发票 N / 支付记录 N / 匹配 N」
    folder: str = ""                   # 仅源模块；空 = 未配置
    params: dict = field(default_factory=lambda: {"tolerance": 0.01, "include_combos": True})  # 仅匹配模块
    x: float = 0.0                     # 画布场景坐标（节点左上）
    y: float = 0.0

@dataclass
class FlowWire:
    wire_id: str
    src_id: str                        # 源模块节点 id（invoice/payment）
    dst_id: str                        # 匹配模块节点 id

@dataclass
class FlowRun:                         # build_plan() 产出：一个匹配模块 = 一次独立匹配运行
    match_id: str
    invoice_folders: list[str]
    payment_folders: list[str]
    tolerance: float
    include_combos: bool

@dataclass
class FlowPlan:
    scan_invoice_folders: set[str]     # 画布上所有「已绑文件夹」发票模块（含未连线，防误标 missing）
    scan_payment_folders: set[str]
    runs: list[FlowRun]                # 只含至少一根入线的匹配模块
```

不变式：
- `node_id`/`wire_id` 唯一（`uuid4().hex[:10]`）。
- 连线只允许「源模块 → 匹配模块」；同 `(src_id,dst_id)` 至多一条（单端口模型天然唯一）。
- folder 按用户原样保存用于展示；比较时统一 `normcase(abspath(...))`。
- 配置不持久化：每次打开空白画布（见 §11-1）。
## 3. 画布架构与视觉

- `FlowScene`：管理节点/连线/临时线/连线态；`drawBackground` 绘点阵网格（底色 `#fafafa`，网格点 `#e4e7ed`，间隔 24px，微网格可选 6px 更浅）——Node-RED 质感但保持轻盈。
- `FlowCanvas(QGraphicsView)`：`setDragMode(NoDrag)`（避免 ScrollHandDrag 吞掉画布 drop 与节点拖放）；空白区左键拖拽平移（scene 命中不到任何 item 时进入 pan）；`Ctrl+滚轮` 缩放 0.4~2.5，`AnchorUnderMouse`；普通滚轮滚动。
- z 序：连线 0 < 节点 10 < 临时线 1000；选中节点描边 `#409eff` 2px；选中/悬停连线加粗变色。
- 模块配色（**复用 auto_match_dialog 现有语义色板**，不新增色系，符合“不改主题色”）：
  - 发票：强调 `#409eff` / 浅底 `#ecf5ff`
  - 支付：强调 `#67c23a` / 浅底 `#f0f9eb`
  - 匹配：强调 `#e6a23c` / 浅底 `#fdf6ec`
- 节点外形：圆角 8px 白底卡片，约 200×78；顶部色带（类型色 + 类型名 + 模块名），下方信息行：
  - 源模块：文件夹路径（`QFontMetrics.elidedText` 中省略）；未配置显示「未选择文件夹」（橙字警示）。
  - 匹配模块：参数摘要「误差 ±0.01 · 含组合」+ 接入摘要「发票 1 路 · 支付 1 路」。
- 端口：左圆=输入、右圆=输出，半径 6px，类型色填充 + 白描边；hover 放大并给 tooltip（「从此端口拖出到匹配模块」等）。
- 空态引导：节点数为 0 时画布中央浮层（QLabel 叠在 view 上或 scene 文本项）：「从左侧拖入「电子发票 / 支付记录」，再拖入「匹配」模块并连线，双击模块配置，点「确定」执行比对」。

## 4. 交互细节

### 4.1 侧边栏拖入画布
- 左侧 `QListWidget` 三个模板项（类型色圆点 + 名称 + 一句说明）。子类化 `startDrag`：`QDrag` + `QMimeData`，mime `application/x-recity-node`，`data("kind")` 存类型；`setDragEnabled(True)`。
- `FlowCanvas.setAcceptDrops(True)`；`dragEnter/dragMove` 匹配 mime → `acceptProposedAction` 并给画布轻微高亮框；`dropEvent` → `mapToScene(event->position)` → `model.add_node(kind, x-100, y-40)` 使落点居中 → 建 `FlowNodeItem` → 隐藏空态遮罩 → 状态条「已添加模块：双击配置」。
- **同类可多实例**：每次拖入都新建，不做去重。

### 4.2 连线（仅源输出 → 匹配输入）
- 按下输出端口 → scene 进入 `linking` 态：记录 `src_node`，创建临时线，随 `mouseMove` 更新终点（scene 坐标，贝塞尔）。
- `mouseMove` 期间：合法目标（匹配模块输入端口或模块体）高亮为绿色“吸入”；悬停非法目标/空白时临时线画为警示红，松开即取消。
- `mouseRelease`：
  - 命中匹配模块（输入端口 ± 容差或模块体）→ `FlowModel.can_connect`：True → 加线并绿字提示；False → 状态条红字给原因（见 §5 矩阵）。
  - 否则取消，不产生线。
- `Esc` / 右键取消进行中连线；画布失焦也清理 linking 态。

### 4.3 双击配置
- `FlowNodeItem.mouseDoubleClickEvent` → `NodeConfigDialog(node, store=..., parent=view)`（`exec()` 模态，parent 确保层级正确）。
- 源模块：名称（`MkInput`）+ `FolderPicker`（复用 `app/ui/widgets/folder_picker.py`；首次添加发票/支付模块时预填 store 默认文件夹）+ 文件数提示（用 `file_scanner.INVOICE_EXTS/PAYMENT_EXTS` 做轻量目录计数，不解析 PDF 页数，避免卡顿）。确定后回写 `name/folder`，重绘并刷新相关匹配模块接入摘要。
- 匹配模块：名称 + 参数（§6.4）+ 只读接入摘要 + 固定说明「已有关联自动跳过（引擎固定行为）」。确定回写 `params`。
- 名称为空 → 自动回退默认名。

### 4.4 节点拖动
- `FlowNodeItem` 设 `ItemIsMovable | ItemSendsGeometryChanges`；`itemChange(PositionChange)` → 回调 canvas `sync_wires(node_id)`（对 incident 线先 `prepareGeometryChange` 再 `setPath`），并回写 `model.x/y`。
- 防递归：itemChange 内只更新线、不 `setPos`。
- 场景范围：加/删节点时用「节点 bbox 并集 ∪ 当前视口」更新 `sceneRect`（不逐帧 update，防抖动）。

### 4.5 删除
- 节点：右键菜单「配置… / 删除模块」（删除级联删线）；选中后按 `Delete` 同效。
- 连线：右键 → 「删除连线」；单击选中后 `Delete`。
- 删除一律先改 model 再删 scene item，保证一致。

## 5. 连线校验矩阵

规则一句话：**仅「源模块(invoice/payment) 输出端口 → 匹配模块 输入端口」合法**。

| 拖放 | 结果 | 提示（状态条） |
|---|---|---|
| invoice.out → match.in | ✅ | 已连接 |
| payment.out → match.in | ✅ | 已连接 |
| 任意 → invoice/payment 输入 | ❌ | 发票/支付模块只输出数据，不能作为连线目标 |
| match.out → 任意 | ❌ | 匹配模块输出为结果出口，悬空即可 |
| 源.out → 源.in（含同类型） | ❌ | 同“不能作为连线目标” |
| match.out → match.in | ❌ | 匹配模块间无需连线 |
| 重复 (src,dst) | ❌ | 该模块已连接，请先删除原连线 |

反馈：非法释放 → 红字 2.5s；合法 → 绿字。同一节点对因单端口模型天然不会出现第二条。

## 6. store 引擎对接

### 6.1 `get_amount_matches` 文件夹过滤：推荐「引擎内可选参数」方案
**为什么不在外部按路径过滤全量结果**：候选是「文件组」而非单文件（单文件或组合），且发票×支付是笛卡尔积；外部过滤对组合语义不可控。过滤应发生在单元构建处（此处有 `abs_path` 与 `missing` 信息）。推荐加可选参数（默认 None=不过滤，旧行为完全不变）：

```python
def get_amount_matches(
    self,
    invoice_folders: Optional[Iterable[str]] = None,
    payment_folders: Optional[Iterable[str]] = None,
    tolerance: float = 0.01,
    include_combos: bool = True,
) -> list[dict]:
```

`_build_match_units(data_key, folder_set=None, include_combos=True)`：
- 单文件单元：`norm_dir(os.path.dirname(f.abs_path)) ∈ folder_set` 才纳入。
- 组合单元：全部**非 missing** 成员的 dirname ∈ folder_set 才纳入（跨界组合整组跳过）。
- `include_combos=False`：不产组合单元；组合成员**不退化为单文件单元**（维持引擎「组合成员不单独匹配」既有语义，防重复/意外关联）。
- `tolerance` 替换硬编码 `0.01`：`abs(diff) <= tolerance`。
- 无参调用（旧路径）行为不变；中文 docstring 同步更新。

### 6.2 多文件夹并集扫描：推荐 `merge_*` 加 `mark_missing` 可选参数
**问题**：现有 `merge_*` 会把「不在本次扫描内」的同 kind 存量文件标 `missing`。画布逐文件夹 merge → 前一个文件夹被标 missing（多文件夹无法并存）；一次性把并集合并 → 误伤**不属于画布的其他活动文件夹**（如比对页当前文件夹），用户切回比对页会发现数据“消失”。
**推荐**（改动最小、向后兼容、把两种语义分开）：

```python
def merge_invoices(self, scanned, mark_missing: bool = True): ...
def merge_payments(self, scanned, mark_missing: bool = True): ...
```

- `True`：现行为（文件夹切换 = 替换活动源，比对/金额页不变）。
- `False`：只 upsert（保留既有金额/关联），不把未扫描文件标 missing（画布多文件夹 = 增量累加）。
- 画布执行传 `False`；金额/关联保留逻辑沿用现有合并代码，零新增风险。
- **备选（不推荐）**：不改 merge，接受“画布执行后 store 池 = 画布文件夹并集、其余同 kind 文件被标 missing”。副作用会污染比对页当前活动文件夹状态。此项请 Claude 拍板。

### 6.3 组合单元边界语义
- 组合是持久化用户分组（store `combos`），画布不动组合本身。
- 文件夹过滤下：组合单元仅当其**全部非 missing 成员都在所选文件夹集内**才参与；否则整组跳过——避免用含外部文件夹成员的总额去链接内部文件；与「任一成员已关联即跳过」的既有保守风格一致。
- 组合总额计算、missing 成员跳过、round(2) 逻辑一律不动。
- `include_combos` 默认 True = 现有引擎语义；不引入新组合计算能力。

### 6.4 匹配模块最小真实参数集（不造假参数）
只暴露引擎真实支持的 **2 个参数 + 1 条固定说明**：
1. `金额误差阈值 ±`（`tolerance`，QDoubleSpinBox，范围 0~10 元、步进 0.01、默认 0.01）→ 直通 `get_amount_matches(tolerance=...)`。
2. `组合单元参与匹配`（`include_combos`，QCheckBox，默认勾选）→ 直通 `include_combos`。
3. 固定说明：「已有关联的文件组自动跳过（引擎固定行为，无需配置）」。

**明确不做**：“跳过已关联”开关——引擎当前无放开分支，做了即假参数。若未来要「已关联也进候选人工复核」，属于新引擎能力，另开任务（记录到 `.ai/backlog.md` 亦可）。
## 7. 「确定」执行管线

### 7.1 配置校验（不关窗，红字/弹窗列缺项）
```
issues = model.validate()  # 覆盖：
#  画布为空 → 「请先从左侧拖入模块开始配置」
#  无匹配模块 → 「缺少匹配模块：请拖入一个「匹配」模块并接入发票与支付」
#  某匹配模块缺发票入线 → 「匹配模块「匹配 N」缺少发票输入，请连入发票模块」
#  某匹配模块缺支付入线 → 同理
#  已连线的源模块未绑文件夹 → 「发票模块「电子发票 N」尚未选择文件夹」
if issues: 状态条红字 + MkMessage.warning(join(issues)); return
```

### 7.2 执行（MatchFlowDialog 内，WaitCursor）
```python
def _on_confirm(self):
    issues = self.model.validate()
    if issues: ...; return                       # 7.1
    if self.store is None: MkMessage.warning(self, "数据未初始化"); return
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        plan = self.model.build_plan()
        # (1) 扫描 + 增量合并：每 kind 一次「并集」merge，mark_missing=False 累加不误伤
        inv_files = [f for fd in plan.scan_invoice_folders
                     for f in FileScanner.scan_invoices(fd)]
        pay_files = [f for fd in plan.scan_payment_folders
                     for f in FileScanner.scan_payments(fd)]
        if inv_files: self.store.merge_invoices(inv_files, mark_missing=False)
        if pay_files: self.store.merge_payments(pay_files, mark_missing=False)
        # (2) 按每个匹配模块参数/接入文件夹求候选，全局去重（多匹配模块并集场景安全）
        all_pairs, seen = [], set()
        for run in plan.runs:
            for p in self.store.get_amount_matches(
                    invoice_folders=run.invoice_folders,
                    payment_folders=run.payment_folders,
                    tolerance=run.tolerance,
                    include_combos=run.include_combos):
                key = (tuple(sorted(p["invoice_ids"])), tuple(sorted(p["payment_ids"])))
                if key not in seen:
                    seen.add(key); all_pairs.append(p)
        # (3) 批量关联（沿用 auto_linked=True 标记语义）
        count = self.store.batch_link(all_pairs, auto_linked=True)
    finally:
        QApplication.restoreOverrideCursor()
    self.result_summary = {"count": count, "total": len(all_pairs), "found": bool(all_pairs)}
    self.accept()
```

### 7.3 ComparePage 提示（沿用旧文案风格）
```python
def _on_auto_match(self):
    if not self.store: MkMessage.warning(self, "数据未初始化"); return
    dlg = MatchFlowDialog(store=self.store, parent=self)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return                                    # 取消/关窗无副作用
    r = dlg.result_summary
    if not r["found"]:
        MkMessage.success(self, "未找到金额匹配的未关联配对。\n请先在「计算金额模式」中为发票和支付记录完成 OCR 识别。")
        self.lbl_match_progress.setText("")
    elif r["count"] > 0:
        MkMessage.success(self, f"自动比对完成，成功关联 {r['count']} / {r['total']} 对。\n自动关联的文件已在列表中标记。")
        self.lbl_match_progress.setText(f"自动比对已保存：{r['count']} / {r['total']} 对")
    else:
        MkMessage.warning(self, "没有新增关联，可能这些配对已被关联。")
    self._update_link_buttons()
```
- 说明：扫描为同步（与 FileListPanel 既有行为一致；大量 PDF 的 `get_page_count` 可能较慢 → WaitCursor + 状态条「正在扫描…」）。本管线无 OCR，OCR 仍按 AGENTS 在 workers 后台线程，不在此引入。

## 8. 删除清单与耦合检查

### compare_page.py 删除项
- import：`auto_match_dialog`(L15)、`toggle_switch`(L18)。
- 状态：`_match_pairs`、`_review_mode`（L44-45）。
- 控件：`toggle_review` 构建与 `toggled` 连接（L61-64）。
- 方法：`_on_review_toggled`(L212-220)、`_open_auto_match_dialog`(L243-269)、`_start_auto_link_mode`(L306-329)。
- `_on_auto_match` 改写为 7.3。
- 保留：工具栏 `btn_auto_match`（文本恒「自动比对」）+ `lbl_match_progress`；`_update_link_buttons`；手动关联/取消/重命名/定位/组合/预览全部逻辑与 import（`QDialog` 仍需用于 `DialogCode.Accepted`）。

### 耦合检查（全仓 grep 结果）
- `AutoMatchDialog`：仅 compare_page 引用 → 删文件 + 删 import 即安全。
- `_review_mode` / `_start_auto_link_mode` / `_match_pairs` / `toggle_review`：仅 compare_page 内部 → 整段删除安全。
- `ToggleSwitch` 组件：仅 compare_page 使用，但 `scripts/check.sh` 步骤 3 仍直接 `from app.ui.widgets.toggle_switch import ToggleSwitch` → **保留 toggle_switch.py**（作为通用控件；避免为删死代码而改 check.sh）。若 Claude 希望连文件+check.sh 一起清理，作为可选项。
- `check.sh`：步骤 1 遍历 `app` 全部 `.py` 做语法检查；步骤 3 import `ComparePage` → 新 `match_flow` 包经 compare_page 导入链自动被覆盖；若删 `auto_match_dialog.py` 前漏改 compare_page import，check.sh 步骤 3 直接失败（天然护栏）。**check.sh 本身无需改动**。
- amount_page / home_page / main_window / app_entry：无相关引用，不受影响。
- `auto_match_dialog.py` 内调色板常量将被 items.py 以新常量承接（语义色值不变），删除该文件不丢视觉资产。

## 9. 分步实施顺序（每步跑验证）

1. **store.py 扩展**：merge `mark_missing` + `get_amount_matches`/`_build_match_units` 可选参数。验证：用 `tempfile` 建临时 store，`python -c` 断言（文件夹过滤 / 组合跨界跳过 / tolerance / include_combos=False / mark_missing=False 累加不标 missing / 无参旧行为不变）；再 `bash scripts/check.sh`（Windows 用 brief 给的 bash 路径）。
2. **match_flow/model.py**：纯逻辑 + `python -c` 断言（can_connect 矩阵 / validate / build_plan）。
3. **items.py + canvas.py**：`QT_QPA_PLATFORM=offscreen` 自检脚本：建场景→加节点/线→移动节点→删节点/线→无异常。
4. **config_dialog.py + 双击接线**。
5. **match_flow_dialog.py 组装**：侧边栏拖放、空态遮罩、状态提示；offscreen 冒烟（构造/打开/关闭）。
6. **compare_page 接入 + 删除旧文件/旧分支**；`bash scripts/check.sh` 全绿。
7. **清理**：删除临时自检脚本/截图；按需最小更新 README「自动比对支持审阅/一键两种模式」的描述（建议同 PR 防文档腐烂，是否做由 Claude 定）。
8. 视觉/交互的人工窗口验证留给 Claude Code（像素级），实现者保证 check.sh 与 offscreen 冒烟通过。

## 10. QGraphicsScene 风险点清单

1. **坐标映射**：drop/dragMove 用 `event->position()` 再 `mapToScene`，勿把 view 坐标当 scene 坐标。
2. **itemChange 递归**：`PositionChange` 回调里只更新连线/回写 model，不 `setPos`。
3. **连线重绘**：`setPath` 前必须 `prepareGeometryChange()`，否则残影。
4. **连线命中**：默认 path 太细 → override `shape()` 用 `QPainterPathStroker`(~10px) 加宽；设 `AcceptHoverEvents` + `setAcceptedMouseButtons(Left|Right)`。
5. **z 序/事件穿透**：线 z=0、节点 z=10；节点区域要拦截事件，避免底层线误高亮/误选。
6. **拖动 vs 连线冲突**：输出端口作子 item 自行处理按下进入连线态；节点 `ItemIsMovable` 需与鼠标位移阈值配合，防双击/单击误拖。
7. **平移模式**：用 NoDrag + 空白区按下平移；不要用 `ScrollHandDrag`（会吞画布 drop 与节点拖放）。
8. **临时线生命周期**：删除/关窗/失焦/Esc 都要清 linking 态与临时线，防悬空引用。
9. **缩放命中**：scene 命中不受 view 变换影响；Ctrl+滚轮 `AnchorUnderMouse`，钳制 0.4~2.5。
10. **文本绘制**：QGraphicsItem 内 `QPainter.drawText` + `QFontMetrics.elidedText`，避免布局繁琐；按字体像素高算 bbox。
11. **双击与拖拽**：`mouseDoubleClickEvent` 开配置前检查位移阈值，防双击变拖动。
12. **性能**：`updateSceneRect` 只发生在加/删节点；连线路径更新 O(线数)，≤50 条无感。
13. **网格背景**：QGraphicsView QSS 背景与 scene `drawBackground` 叠色需协调（参考 preview_view 既有风格），border-radius 6px。
14. **迭代安全**：删节点/批量删线先收集受影响列表再 `removeItem`，勿遍历中改容器。
15. **Modal 嵌套**：NodeConfigDialog/校验弹窗 parent 必须正确（模态 MatchFlowDialog 之上）；执行结果消息统一回 compare_page 弹，避免 exec 嵌套。

## 11. 待实现时默认决策（请 Claude Code 审阅确认/纠正）

1. **画布配置不持久化**：每次打开空白画布 + 引导提示（不新增 config 段，范围最小）。
2. **首个发票/支付模块预填 store 默认文件夹**（`invoice_folder`/`payment_folder`，存在时）；后续同类模块为空——保住“单文件夹用户拖入即可确定”的旧体验。
3. **模块配色**：发票蓝 `#409eff/#ecf5ff`、支付绿 `#67c23a/#f0f9eb`、匹配橙 `#e6a23c/#fdf6ec`（均取自现用语义色板）。
4. **匹配参数仅 tolerance + include_combos**（§6.4）；不做假参数。
5. **merge 采用 `mark_missing=False` 增量累加**（§6.2 推荐项，需确认此 store 语义扩展）。
6. **0 候选视为「未找到」**：执行成功即 accept（found=False），compare_page 弹旧“请先 OCR”文案——比留在画布少一步；如需“留在画布改配置”可改为不关窗。
7. **执行在对话框内同步完成**，结果经 `result_summary` 交 compare_page 提示（延续旧架构：对话框返回结果、消息由页面弹）。
8. **非法/未配置时点确定不关窗**，warning 列缺项。
9. **README 自动比对两模式描述过时** → 建议同 PR 最小更新（待 Claude 决定）。
10. **匹配模块输出端恒悬空**；不设“执行入口”等额外节点，保持三模块最小集。

## 12. 验收对照（brief 验收项 → 方案落点）

- 新画布界面 / 旧对话框与开关、一键模式移除 → §1、§8。
- 三模块拖入、同类多实例、双击配置 → §4.1/§4.3、§1。
- 连线/非法拒绝/删除 → §4.2/§4.5、§5。
- 贝塞尔流畅、悬停反馈 → §3、§4.2。
- 确定校验与执行、结果提示一致 → §7。
- 多源（并集）+ 组合单元语义 → §6.1-6.3、§7.2。
- 手动功能无回归 → §8 保留清单。
- `bash scripts/check.sh` 全绿 → §9。
---

## 13. Claude Code 审阅结论（2026-09-03，实施前定稿）

审阅通过。已独立核验两个关键前提：① store.py L108-110/L126-128 确认 `merge_*` 会把未扫描同 kind 文件标 missing → `mark_missing=False` 方案成立；② file_scanner.py 用 `os.scandir` 顶层扫描（非递归）→ §6.1 的 dirname 相等过滤正确。

**待确认默认决策全部批准**（§11：1~10 全部按推荐执行），并追加：

1. **README 更新为必做**（§11-9 改为批准）：同 PR 最小更新「自动比对」描述（两模式 → 流程画布单模式），防文档腐烂。
2. `toggle_switch.py` 保留（§8 理由成立，check.sh 仍 import 它；作为通用控件留存不删）。
3. 实现验收要求：§9 各步的一次性断言/offscreen 冒烟必须真跑过并贴结果；store 引擎断言覆盖（无参旧行为不变 / 文件夹过滤 / 组合跨界整组跳过 / tolerance / include_combos=False / mark_missing=False 不标 missing）6 类场景。
4. 细节补强：
   - 节点/连线删除键需 view 有焦点（`setFocusPolicy(StrongFocus)`），防 Delete 无响应；
   - 连线增删与模块配置变更后，需刷新相关匹配模块的「发票 N 路 · 支付 N 路」接入摘要；
   - 配置弹窗的文件夹文件数统计用 scanner 扩展名顶层计数即可（与扫描语义一致），不做 PDF 页数解析。
5. 实现期间只允许动：新增 `app/ui/widgets/match_flow/` 包、`match_flow_dialog.py`、`store.py`、`compare_page.py`、README.md；删除 `auto_match_dialog.py`。不得动 `data/store.json`、`config/app_config.json`、其他页面与主题。
6. 完成后不 commit，交 Claude Code 审查 diff（`git diff` 全部产出）+ 写 `.ai/review.md` + 人类确认后再提交。

---


> **Claude Code 批准（2026-09-03）+ 一处修订**：v2 设计批准实现。修订：`payment.out → match.in`
> 由「可绘制、validate 拦截」改为**直接非法连线**（锁定链语义下支付模块角色唯一 = 链尾结果侧，
> 只接收匹配模块输出；可绘制不可执行是死交互）。连线矩阵终稿：
> 合法 = invoice.out→match.in、match.out→payment.in；其余一律非法并给中文原因。
> 其余设计（自动铺/绑定数据结构/Σ 口径/validate/管线含 skipped）按原文实现。

## v2 设计（文件粒度 + 自动铺候选链）

> 阶段一设计（2026-09-03，Codex 输出，**待 Claude Code 批准后再实现**；本阶段未改源代码）。
> 依据：`.ai/brief.md` v2 语义规格（人类已拍板）、`.ai/decision-log.md` 2026-09-03 两条、
> `.ai/review.md` v1 结论。设计原则：复用 v1 已验收的画布基建（viewportEvent 拖放/删除/平移缩放/
> 引导卡/QGraphicsScene 交互）；模块库 palette 中性化；store.py 引擎不改；不新增依赖。

### v2-1 自动铺布局策略

**入口（MatchFlowDialog v2 打开时）**
1. `store.get_amount_matches()`（无文件夹过滤、tolerance=0.01、include_combos=True，原样调用）→ `matches: list[dict]`；store 为 None 时跳过自动铺（空画布）。
2. 无候选 → 保持空画布 + 引导卡（v1 基建已有），引导文案改为 v2 语义：「未找到金额匹配的未关联配对（无金额或已全部关联）；也可从左侧拖入模块手动搭建」。
3. 有候选 → 全部自动铺，非空白。

**候选对 → 链簇映射（同单元跨候选共享节点）**
- 归一键：`inv_key = tuple(sorted(p["invoice_ids"]))`、`pay_key = tuple(sorted(p["payment_ids"]))`、`pair_key=(inv_key, pay_key)`。
- 注册表：`inv_nodes: dict[inv_key→FlowNode]`、`pay_nodes: dict[pay_key→FlowNode]`。遍历 matches（先按 pair_key 去重，防重叠组合等边缘重复）：
  - 发票单元首见 → `model.add_node(KIND_INVOICE)` 并**预绑定**该单元；再见 → **复用同一节点**（发票节点出 N 条线到 N 个匹配）。
  - 支付单元同理（镜像场景：同一支付节点收 N 条匹配出线，支付节点共享）。
  - 每个候选对新建 1 个 `match` 节点 + 2 条线：`inv.out → match.in`、`match.out → pay.in`（line 生成走 `model.add_wire`，需在 can_connect v2 落地之后）。
- 组合反查：候选 dict 只有 `invoice_ids/is_combo_invoice/invoice_name`；组合单元用 `store.get_combos(kind)` 中 `sorted(c["file_ids"]) == sorted(unit_ids)` 反查 combo_id 完成预绑定（多个同成员组合取首个，边缘可忽略）。

**画布坐标布局（朴素三列金额簇，明确不做自动布点优化）**
- 常量：`X = {invoice: 40, match: 40+NODE_W+70, payment: 40+2*(NODE_W+70)}`；`V_STEP = NODE_H+40`；`CLUSTER_GAP = 80`；起始 `y0=40`。
- 簇键 = `round(unit_amount, 2)`（候选显示金额两侧一致）；全局簇按金额升序。
- 每簇分配共享行带：`rows = max(该簇发票单元数, 匹配数, 支付单元数)`；三列内各自的节点按 `(amount, 显示名)` 升序落在 `y = base + slot*V_STEP`，列内 slot 唯一 → **列内不重叠**；簇与簇之间 `cursor += rows*V_STEP + CLUSTER_GAP`（金额带之间留白）。
- match 节点在其簇行带内按 `(发票显示名, 支付显示名)` 排；不追求线最短/不避让（连线允许斜跨，候选多时可滚动查看）。
- sceneRect：沿用 v1 `_expand_scene_rect`（加/删/移动节点时 union + 外扩 120px）→ 自动出现滚动条；不 fitInView。自动铺后滚动条回左上（或 centerOn(0,0)）即可，不自动缩放。

**节点命名 + 金额徽标**
- 命名（自动铺时写入 `node.name`，用户可再改名）：源节点单文件 = 文件名；组合 = 组合名（引擎候选已给 `invoice_name/payment_name`）；匹配节点 = `匹配 ¥{amount:,.2f}`。
- 金额徽标：源节点右下角圆角徽标显示 `¥ {bind_amount:,.2f}`（= 绑定成员金额和，见 v2-2）；匹配节点显示该对金额；items.paint 新增徽标绘制，配置/绑定变更后 `refresh_content()` 重算。

### v2-2 节点绑定数据结构

**FlowNode（model.py）字段改动**
```python
@dataclass
class FlowNode:
    node_id: str
    kind: str                 # KIND_INVOICE / KIND_PAYMENT / KIND_MATCH
    name: str
    file_ids: list[str] = field(default_factory=list)   # 直接绑定的单文件（非组合成员）
    combo_ids: list[str] = field(default_factory=list)  # 绑定的组合整组（combo_id 引用）
    params: dict = field(default_factory=lambda: {"tolerance": 0.01})  # 仅匹配模块；删 include_combos
    x: float = 0.0
    y: float = 0.0
```
- 删 `folder`；`params` 只留 `tolerance`（`include_combos` 开关是首版删除项）。
- 两字段共存：`file_ids` 与 `combo_ids` 可同时非空（一个节点可绑多个单文件 + 多个组合整组，对应背景「绑定多个同类型文件，也可绑定多个组合」）。
- 与 kind 的关系：仅源模块可绑定；kind 决定数据来源（invoice → `store.get_invoices()` / `get_combos("invoice")`；payment 同理）与合法性（发票节点只能绑发票文件/发票组合）。

**派生语义（Qt-free 帮助函数，放 model 或 dialog 上层）**
- `canonical_file_ids() = file_ids ∪ (各 combo_ids 经 store.get_combo 解析的成员)`（去重、剔除 missing）。
- `bind_amount() = round(Σ 成员 final_amount, 2)`（跳过 missing/无金额成员，与 `_build_match_units` 组合求和一致）→ 链容差比较的统一口径：单文件=自身金额、组合=成员求和、多绑定=全部求和。
- `is_bound() = bool(canonical_file_ids())`；未绑定 → 节点警示「未绑定文件/组合」（橙字，沿用 v1 警示风格）。
- 互斥不变量：单文件不得是已绑组合成员；两个组合若成员重叠不得同选/跨模块同时绑定；已被其它源节点绑定的文件或组合（含重叠）禁用。

**UI 显示内容（items.paint）**
- 信息行：单文件 = 文件名；组合 = `组合「name」（N 文件）`；混合 = `N 文件 · M 组合`；未绑定 = 警示。
- tooltip 逐条列出绑定成员（文件名 + ¥金额 + 已关联标记）；金额徽标显示 `bind_amount()` / 匹配对金额。
- 名称行仍展示 `node.name`（可编辑），名称为空回退默认名（单文件=文件名、组合=组合名，否则「电子发票 N」等）。

**「模块候选绑定控件」数据来源与状态（config_dialog v2，双击源模块）**
- 数据：`store.get_invoices()/get_payments()`（默认排除 missing）、`store.get_combos(kind)`、`store.get_combo_total(combo_id)`；金额取 `amount.final_amount`。
- 列表结构：树形/分组——「组合」组（勾选 = 绑整组，行显示组合名 + N 成员 + ¥总额 + 任一成员已关联则标「已关联」）+「单文件」组（文件行显示文件名 + ¥金额或 — + 已关联灰标）；**单文件区排除组合成员**（成员只在组合行内作子行展示，不可单独勾选，镜像引擎 `_build_match_units` 语义）。
- 状态：已被它模块绑定（含成员重叠）→ disabled + tooltip「已被模块 X 绑定」；已关联 → 可勾选但标「已关联」（执行时该链会进跳过汇总）。
- 冲突校验规则（绑定对话框强制 + `validate()` 兜底）：同一 file_id 不得同时属于两个不同源节点的 canonical 集；组合与其成员互斥；重叠组合互斥。

### v2-3 连线矩阵与链校验

**can_connect 扩展（model.py，Qt-free）**
| 拖放 | 结果 |
|---|---|
| invoice.out → match.in | ✅ |
| payment.out → match.in | ✅（继承 v1 合法项） |
| **match.out → payment.in** | ✅ 新增链尾 |
| 其它（匹配模块间互连、源模块互连、match.out → 非支付目标、发票/支付 .in 作入线目标、自连、重复 (src,dst)） | ❌ 中文原因 |
- canvas linking 状态机配套微调：`update_temp` 的非法判定按源 kind 区分（源模块拖出 → 目标须 match；match 拖出 → 目标须 payment），悬停目标高亮与临时线红/蓝逻辑沿用 v1。

**一条有效链判定（执行单元，每个 match 节点 M）**
- 形态：**恰 1 条入线 + 恰 1 条出线（目标 kind == payment）**。
- 执行语义：入线源须为**发票模块**（发票侧单元）→ 0 条报「缺少发票输入」、≥2 条报「一条链只对应一个发票模块」；出线 0 条报「缺少支付输出（请连到支付模块）」、≥2 条同理。
- **待确认**：brief 矩阵把 `payment.out → match.in` 列为合法。按锁定语义「一条链 = 发票(入匹配.in) + 匹配 + 支付(匹配.out 指向它)」，支付模块作左侧输入**不构成可执行链** → validate 报「匹配模块输入来自支付模块，请改接发票模块」。若意图是支持反向链（支付→匹配→发票），需同时放开 match.out 目标到发票模块——默认按「可绘制、执行被拦」实现，请 Claude 确认。

**validate() 缺项清单（v2，不关窗 + 状态条红字）**
1. 画布无节点 → 「画布为空：请先从左侧拖入模块，或确认存在金额匹配候选」。
2. 某匹配模块缺发票输入 / 缺支付输出 / 入线源为支付模块（见上）。
3. 链上源模块未绑定 → 「发票模块「X」尚未绑定文件或组合」（仅查参与链的源模块，未接线模块惰性不查，同 v1）。
4. 文件冲突 → 「文件「名」同时被两个模块绑定，请先移除其一」（同一共享节点扇出/扇入多条链是允许的，只拦「不同源节点重复引用同一 file_id」）。
5. 无任何形态完整的链且画布非空 → 汇总提示。

**确定并执行管线伪代码（锁定模型，不重算引擎）**
```
def _on_confirm():
    issues = model.validate()
    if issues: 状态条红字 + MkMessage.warning(逐条); return
    chains = model.executable_chains()          # [(match, inv_node, pay_node)]
    if not chains: warning「没有可执行链」; return
    ok_pairs, skipped = [], []
    for m, inv, pay in chains:
        inv_ids, pay_ids = inv.canonical_file_ids(), pay.canonical_file_ids()
        if not inv_ids or not pay_ids: skipped.append("未绑定"); continue
        inv_amt, pay_amt = inv.bind_amount(), pay.bind_amount()
        tol = float(m.params.get("tolerance", 0.01))
        if abs(inv_amt - pay_amt) <= tol:
            ok_pairs.append({"invoice_ids": inv_ids, "payment_ids": pay_ids})
        else:
            skipped.append(f"金额差超出容差：¥{inv_amt} vs ¥{pay_amt}（±{tol}）")
    count = store.batch_link(ok_pairs, auto_linked=True) if ok_pairs else 0
    self.result_summary = {"count": count, "total": len(chains),
                           "found": bool(chains), "skipped": len(skipped),
                           "skip_reasons": skipped[:20]}
    self.accept()      # ComparePage 文案：成功 count/total + 跳过 N 条（沿用旧 found 分支）
```
- 口径注意：`count` 可能 < `len(ok_pairs)`（batch_link 对已关联 pair 内部 no-op）→ 结果文案沿用「没有新增关联…」warning 分支处理。

### v2 其余落点（实现阶段范围，同 brief「相关文件」）
- 改动：`match_flow/model.py`（绑定字段 + can_connect/validate/chains）、`items.py`（信息行/徽标 + 命名）、`canvas.py`（linking 目标按源 kind、引导文案）、`config_dialog.py`（绑定多选控件 + 冲突禁用 + 匹配容差）、`match_flow_dialog.py`（palette 中性化 + 打开即自动铺入口）、`compare_page.py`（结果文案含跳过数，微调）。
- 不做：文件夹绑定/FolderPicker/文件数统计、`include_combos` 开关、自动布点优化、画布配置持久化；`store.py` 引擎与 `merge_* mark_missing` 分支**不改不动**。
- 删除项（v1 残留）：`FlowNode.folder`、palette 彩色图标（`_kind_icon` 与拖拽 pixmap 中性白底）、`_PALETTE_ITEMS` 中文件夹描述文案。

---

## 2026-09-04 追加：端口级拖线判定 + 模块库着色 + 对话框最大化（本轮实现方案）

> 来源：`.ai/brief.md`（三个问题规格已定稿）。改动文件：`items.py` / `canvas.py` /
> `match_flow_dialog.py`；不改 `model.py` can_connect 矩阵、执行语义与 store。

### 问题 1：拖线目标按「端口侧」命中与高亮（P1）
- 端口侧三分：以目标模块卡片中线（`NODE_W/2`）为界，左半 = 输入侧、右半 = 输出侧；
  中线左右 ±`_MID_BAND`(6px) 窄带 = 中部（意图不明 → 无效）。左右半各含端口 ±容差。
- 合法性 = kind 矩阵（沿用 `_is_valid_link_target`，矩阵未动）∧ 命中侧匹配：
  - 发起 out（正向）= 目标模块**输入侧**（inv.out→match.in / match.out→payment.in）；
  - 发起 in（反向）= 目标模块**输出侧**（拖 payment.in 找 match.out、拖 match.in 找 invoice.out）；
  - 中部 / kind 不符 / 侧别不符 → 红临时线、无高亮、释放不建线（红字给侧别提示）。
- items：`_link_target` 拆为 `_link_target_in`/`_link_target_out`，paint 按命中侧亮对应端口；
  合法目标统一沿用绿色卡片描边（`_GREEN`，与旧正向一致；invoice 悬停不再与选中蓝混淆）。
- canvas：`_target_side()` 归类 + `_link_validity()` 判定（update_temp 与 finish_link 共用，
  保证释放与悬停同口径）；`_set_hover_target(item, side)` 按侧置位；`_hover_side` 记录。
- 说明/取舍：正向 UX 由「整模块可落」收紧为「须落输入侧（左半）」，这是规格要求的按侧判定；
  悬停发票/支付（kind 非法）行为与旧一致。

### 问题 2：模块库三项彩色卡片（P2）
- 复用画布节点同一语义色 `items.STYLE`（发票蓝 #409eff/#ecf5ff、支付绿 #67c23a/#f0f9eb、
  匹配橙 #e6a23c/#fdf6ec）：图标 = 主色、卡片底 = 浅底、边框 = 主色；
  hover/选中 = 主色向浅底加深（`_blend`）+ 边框加粗（1.5/2.0）。
- 每项 `DecorationRole` 按 kind 生成 `_kind_icon`；拖拽 pixmap 图标同步用 kind 主色。
- 结构与 QDrag/mime 协议不变（UserRole=kind、MIME_NODE 不变）；选中/hover 文字仍灰阶。
- 替换中性化（旧常量 `_PALETTE_CARD_*`/`_neutral_icon` 删除），符合最新人类改主意。

### 问题 3：MatchFlowDialog 打开最大化（P2）
- 构造期 `_fit_available_screen()`：优先取父窗口所在屏幕 availableGeometry 铺满
  （exec 前即有满屏尺寸）；小于 min size 时退回 1580×920 由最小尺寸兜底。
- `showEvent` 首次 `QTimer.singleShot(0, showMaximized)`（延迟一拍防重入）→ 真最大化。
- min size 保留 1280×680；离屏/极小屏由 isMaximized 或尺寸覆盖可用屏双口径断言。
- 三列布局常量：**维持现 360 列距不变**（评估取舍：自动铺只在打开时铺一次，无法等
  最大化后再算布局；再拉开会让最小宽 1280 窗口出现横向滚动、支付多行换行错位。
  最大化后的横向留白由画布自适应/平移缩放消化，簇保持纵向堆叠）。

### 验证（2026-09-04，offscreen）
- 问题1：真实 MatchFlowDialog + viewport QMouseEvent 模拟 5 条路径 26 断言全过：
  反向支付.in→匹配输出侧高亮/建线、反向悬匹配输入侧红/不建线、反向匹配.in→发票输出侧建线、
  正向 inv.out→匹配输入侧回归、中部悬停无效；截图像素佐证（无效红 302px、合法绿边/端口高亮）。
- 问题2：整窗与逐行像素断言 蓝/绿/橙 主色 + 浅底均 >0（发票 172/7524、支付 172/7472、
  匹配 172/7608），选中行仍含类型主色；截图 `_tmp_diag/palette_colored.png`。
- 问题3：min size 保留、show 后 isMaximized=True（可用屏覆盖断言通过）、布局不崩、远端节点可滚动。
- `bash scripts/check.sh` 全绿。临时脚本已清理；`_tmp_diag/` 截图留 Claude 审后删。

# 审查意见：自动比对流程画布 v2（文件粒度 + 自动铺候选链）

**结论：通过 ✅**（等待人类真机终验后提交；无 CRITICAL/HIGH 问题）

审查人：Claude Code ｜ 2026-09-03 ｜ 本轮基线：画布 v1 全量改动（未提交）+ v2 语义重做

## 审查范围

- v1→v2：model.py 绑定模型重写 / items.py / canvas.py / config_dialog.py / match_flow_dialog.py / compare_page.py 文案
- store.py 引擎不改（v2 锁定链模型：进入 get_amount_matches() 原样调用铺候选，确定逐链校验后 batch_link）

## 验证证据

| 验证 | 结果 |
|---|---|
| `bash scripts/check.sh` | ✅ 全绿 |
| Codex 程序化断言 | ✅ model 34/34、offscreen 48/48、linking 5/5 |
| **Claude 独立抽查 1**（自动铺+落库） | ✅ 3 候选 → 3 链 6 线、共享支付节点入线 2、validate 空、confirm 落库 3 条 |
| **Claude 独立抽查 2**（手动链+容差） | ✅ 手动搭链金额差 0.5>0.01 → skipped=1 原因含金额明细；tolerance 调 0.5 → 通过并落库 |
| **Claude 独立抽查 3**（无候选） | ✅ 自动铺为空，可手动搭链（状态提示引导） |

## 关键设计确认

- 连线矩阵 v2（含批准修订）：合法仅 `invoice.out→match.in`、`match.out→payment.in`；`payment.out→match.in` 直接非法（支付=链尾结果侧）
- 绑定语义：模块 = 文件/组合绑定集合；`bind_amount` Σ 口径（跳过 missing/无金额），与引擎组合求和一致；同 file_id 跨源模块冲突由配置弹窗禁用 + validate 兜底双保险
- 自动铺：同单元跨候选共享节点（发票扇出/支付扇入），每候选对独立匹配模块；三列金额簇朴素布局
- 执行：锁定模型（不重算）——逐链 `abs(inv_amount − pay_amount) ≤ 匹配模块 tolerance` → batch_link(auto_linked=True)；跳过链记录原因
- palette 模块库纯白中性（无彩色分类图标）；画布节点类型色带保留（待真机观感确认）

## 遗留观察（不阻塞）

- 共享发票节点扇出多条链 → 确定一次关联全部（与旧 AutoMatchDialog 全选语义一致；如需逐对确认再议）
- `found=False`（Accepted 无候选）分支在 compare_page 保留兼容
- 已关联文件在绑定列表中仅标记不拦截，执行时由引擎语义自然跳过
- README 的「自动比对」功能描述已含 v1 文件夹语义 → 需同步 v2（同批提交时小改）

## 待办（人类）

1. 真机终验（重点见下）
2. 终验通过后告知，Claude Code 提交全部改动
3. 若需「一键放入默认流程」等增强 → backlog 已有记录

## 修复轮 3 审查结论（2026-09-03 追加）

**结论：通过 ✅**（等人类真机复验后提交）

### 问题 1：场景矩形负向漂移（画布全白）— root cause 修复
- **实证链**：Claude Code 隔离实验（QGraphicsScene setSceneRect/读取正常）→ setSceneRect 调用轨迹（每步 -120 累积）→ item 几何轨迹 → 定位 `_expand_scene_rect` 每节点对整个矩形 `adjusted(-120,…)` 致场景左上无限负漂，scrollbar=0 时内容甩出视口
- 修复：`_scene_rect_set` 标志，margin 仅首次；之后纯 united（Codex 修正：Qt 未显式 set 时 sceneRect() 返回实时 itemsBoundingRect，width≤0 判定分支永不触发，标志方案等价且正确）
- 验证：渲染断言 17/17（sceneRect left/top=-90 ≥ -200；首节点 bbox 与 scrollbar=0 首屏相交；grab 色带 #409eff=8002/#67c23a=7990/#e6a23c=8269 > 0；手动 add_module 首屏可见；远端 (3000,2600) 移动后 scroll max 可达）；check.sh 全绿
- **方法论教训（记录）**：画布可见性缺陷必须用渲染/坐标断言验证——此前 v1/v2 的离屏断言只测 model/事件层，两次漏检同类问题（v1 拖入无反应部分成因同源）

### 问题 2：模块库卡片化
- `_PaletteCardDelegate` 自绘圆角浅底卡片（bg #f7f9fc/边框 #e4e7ed/hover #ecf5ff/选中 #d9ecff）+「模块名粗体 + 类型说明灰字」两行 + 中性图标；QDrag/mime 协议未动
- 选型说明：QSS `::item` 无法承载两行结构（文本换行被归一化 U+2028），故用同文件 delegate；未用 MkCard（需 setItemWidget 自建拖拽源，改动大）
- 像素验证：卡片底/边框/两行文字/选中/hover 反馈存在

### 待办
1. 人类真机复验：自动铺出候选链**首屏可见** + 模块库项卡片观感/拖拽手感（截图：`_tmp_diag/match_flow_fixed.png` 1770×1080）
2. 复验通过 → 提交全部改动（含 README v2 文案同步、_tmp_diag 清理）

## 修复轮 4 审查结论（2026-09-03 追加）

**结论：通过 ✅**（等人类真机复验后提交）

### 问题 1：自动铺按发票单元聚合（1 发票模块 + 1 匹配模块 + N 支付模块）
- model：支付出线放宽 ≥1（0 仍报错）；executable_chains → (match, inv, [pays])；链金额 = 发票金额
- dialog：_build_candidate_chains 以发票单元为聚合键；布局发票/匹配列单元行对齐、支付列共享节点唯一；confirm 按支线逐条容差校验（total=支线数）；文案「候选支线」
- 独立抽查：1×3 → 1/1/3 结构与 3 条出线、confirm 3/3；删 1 支线（未关联新 store）→ 2/2；2×2 → 2 match 各 2 出线（Codex 断言）

### 问题 2：空壳组合（成员全 missing 的组合不再出现在配置候选）
- 双保险：展示层过滤（config 候选/自动铺反查只接受 ≥1 非 missing 成员，部分缺失标注）+ store merge 后 _prune_shell_combos（全 missing 组合自动清理，部分缺失保留）
- 取舍记录：mark_missing=True（文件夹替换语义）重扫后旧文件夹组合成员全 missing → 自动删组合；文件切回可恢复但组合丢失（仅删全 missing、展示层过滤是第一道保险；若不可接受可移除两处 _prune 调用退回纯展示过滤）
- 独立抽查：全 missing 组合被 prune、部分缺失组合保留；存量 3 个空壳组合按要求不主动清（树中可删/未来重扫自然清理），展示层已不再暴露

## PyFlowGraph 范式改造审查结论（2026-09-23 追加）

**结论：通过 ✅**（依用户既定规则直接提交推送）

### 背景
人类指定参考 PyFlowGraph（MIT, bhowiebkr）重构画布**交互与视觉**。Claude 尽调其源码后定规格（不整包引入其 13.4k 行应用与 markdown-it-py 依赖）：对齐交互范式（左键框选/中键右键平移/右键轻点菜单/滚轮直接缩放）+ 核心视觉（连线=起点类型色 3px/选中悬停高亮/节点渐变标题栏+阴影/双层网格）。人类拍板跟随其交互范式。

### 实现
- 新增 `canvas_interaction.py`（FlowInteractionMixin + _FlowViewStyle 橡皮筋样式，右键 press/move/release 三段状态机，3px 阈值区分菜单与平移；Mixin 使 canvas.py 保持 796 行 < 800 约束）
- `canvas.py`：RubberBandDrag、incident 高亮、sceneContentRect 防阴影污染场景矩形、空白画布菜单（全选/清除选择）
- `items.py`：连线类型色（取自 STYLE 唯一色源）、3px/悬停 4px 亮化/选中 lighter(150)、节点渐变标题栏 + darker(120) 分隔线 + 双绘微阴影、选中描边类型色 lighter(130)

### 验证（Codex 46/46 + Claude 独立抽查）
- 独立抽查：RubberBandDrag ✓、多选 ✓、滚轮缩放 1.0→1.15 ✓、连线色（发票 #409eff / 匹配 #e6a23c）✓、菜单路由（节点区/空白区）✓、confirm 回归 2/2 ✓
- Codex：框选整体移动/批量删除、右键拖平移、三类菜单路由、缩放钳制、端口双向拖线四路径、自动铺 1+1+N、场景矩形不漂移、渲染像素（阴影/渐变/双层网格/连线色），check.sh 全绿
- 明确未做（防蔓延）：reroute 节点/分组容器/撤销重做/dark theme

### 遗留
- 空白画布菜单新增「全选/清除选择」文案待人类真机确认
- 真机手感复验（框选/右键平移/滚轮缩放/连线观感）

## 画布模块文件预览（右侧面板）审查结论（2026-09-27 追加）

**结论：通过 ✅**（含 1 处组件边界修复；已按规则提交推送）

### 实现
- 新增 `preview_panel.py`：右侧 420px 可折叠面板（标题+类型徽标 / 文件列表 / 复用 PreviewView）；单选源模块显示绑定文件（组合展开成员并标注组合名）、单选匹配模块显示链两侧分组（发票侧/支付侧）、多选/空选/未绑定/缺失各有提示，缺失置灰不可预览；只读。
- `match_flow_dialog.py` 接入 `scene.selectionChanged`、折叠入口（折叠后留 38px 展开条）、配置更新后刷新。

### 审查修复（Claude 直接修，组件边界）
- Codex 初版在产品代码访问 PreviewView 私有成员（`_pixmap`、`lbl_title`）。已在 `PreviewView` 增加公共接口 `set_title()` / `has_content` 属性（向后兼容，不改行为），`preview_panel` 改用公共接口。

### 验证（Claude 独立抽查 8/8 + Codex 断言）
- 空选占位、单选发票列表+PDF 预览加载、组合成员展开+组合名标注、匹配模块双侧分组、多选提示、折叠隐藏/展开恢复——全部通过；check.sh 全绿。

### 附：退出段错误（segfault）调查（重要方法论记录）
- 抽查脚本自然退出时出现**偶发 segfault**（windows 平台同样复现），定位实验（各 8 次）：
  - 构造画布对话框后**不进事件循环直接退出**：5/8 崩溃（与预览面板无关，noload 同样崩）
  - `dialog.exec()` 模态循环：0/8；`show/close/app.exec` 真实退出路径：0/8；主程序 MainWindow：0/5
- **结论：非产品缺陷**——Python-Qt 在解释器 finalize 阶段、无事件循环时的已知析构时序脆弱（QGraphicsScene 自建 item 的 GC 顺序），**真机应用路径稳定**。
- **约定（写进验证规范）**：此后所有离屏验证脚本退出时用 `dialog.exec()`/事件循环或 `sys.exit()`，不要"构造后裸退出"，避免误报 segfault 干扰审查。

### 遗留
- 真机复验：单击模块看文件、匹配模块双侧核对、折叠手感

## 自动匹配时间条件（两轮）审查结论（2026-09-27 追加）

**结论：通过 ✅**（已按规则提交推送）

### 背景
人类反馈「金额相同就匹配不合理」，拍板新增时间条件：**OCR 票面日期**（发票开票日期/支付时间戳）+ **相差 ≤ N 天**（默认 7，可调）；Claude 补定实操决策：**识别失败回退文件修改时间**（保证条件始终生效、不漏配），来源可辨（ocr/file）。

### 第 1 轮（core + 引擎 + OCR）
- 新增 `date_parser.py`（NFKC 归一化、中文/分隔符/8 位连写三类正则、8 位需上下文防订单号误报、真实日历校验、开票日期优先、11 正 9 反断言）
- models 加 `document_date`/`document_date_source`（旧数据兼容）；store 加 `set_document_date` + 单一回退入口 `get_document_date` + merge 保留；`get_amount_matches(time_tolerance_days=None)`（None=旧行为；单文件日期区间、组合成员 [min,max] 区间、最近距离 ≤ N）
- amount_page OCR 落库同路径解析日期（失败静默留空不阻塞）
- **审查中我三次用错测试夹具**（金额全同/mark_missing 语义/单文件追加 merge）→ 全部为脚本错误，引擎行为逐条正确；教训：夹具须模拟真实「整目录全量扫描」语义

### 第 2 轮（画布接线）
- params 加 `time_tolerance_days=7`/`time_unlimited=False`；配置面板 SpinBox(0~365)+不限制复选框联动；卡片摘要 ≤N天/同日/不限
- 自动铺默认传 7 天；无候选提示含时间说明；confirm 逐支线时间校验（跳过原因含「X 天 > N 天」/「无法确定日期」防御分支）
- preview_panel 列表项显示 `文件名 · 日期（票面/文件）`

### 验证（Claude 独立抽查 + Codex 断言）
- 引擎：None 回归、N 边界含/不含、票面优先、文件时间回退、组合区间重叠/端点/超差——全过
- UI：自动铺 7 天 1 候选 vs 不限 2 候选、confirm 4 天成功/16 天跳过（原因含天数）、配置联动与回写、预览日期标注——全过
- `check.sh` 全绿

### 重要提示（给人类）
- **已有文件需在「计算金额模式」重跑一次 OCR 才会写入票面日期**；未重跑的按文件修改时间兜底（条件仍生效）

## 匹配参数持久化 + 金额页日期列 审查结论（2026-09-27 追加）

**结论：通过 ✅**（已按规则提交推送）

### 问题 1：时间设置在重开画布后丢失（真 bug）
- Root cause：画布每次空白重铺 + 自动铺硬编码 7 天，用户设置仅存内存
- 修复：AppConfig 持久化 `match_time_tolerance_days`/`match_time_unlimited`/`match_amount_tolerance`（金额容差同类问题一并修）；自动铺/新匹配节点读偏好；配置面板保存同步写偏好；AppConfig 实例经 main_window → compare_page → dialog/config_dialog 传递
- 独立抽查 6/6：改 N=15 → 落盘 → **重开画布新匹配节点继承 15**；金额容差 0.5 落盘 ✓
- 取舍：日期列沿用 Codex 决定「只显示 OCR 来源」（回退文件时间显示 —，符合"显示识别出的时间"语义）

### 问题 2：金额页显示识别日期
- 表格列序改为 文件名 / 日期 / 识别金额 / 编辑金额 / 确认；日期列显示 OCR 日期，未识别显示灰字 —
- 独立抽查：表头列序、票面日期显示、无日期 —、**编辑/确认列控件在位（列索引调整回归通过）**

### 验证
- 独立抽查 6/6 + 金额页 4 项断言全过；`check.sh` 全绿
- 审查备注：本次我两次断言脚本自身写错（夹具日期超 7 天致空画布、列索引读错 2/3 应为 3/4），实现均正确——沿用此前教训：夹具须模拟真实数据分布

## 金额页日期手动编辑 审查结论（2026-09-28 追加）

**结论：通过 ✅**（已按规则提交推送）

### 实现
- 新增 `date_edit_cell.py`（DateEditCell）：QDateEdit + 日历弹出 + 「未设置」空值语义（specialValueText + minimumDate=1900-01-01）+ 清除按钮 + committed(file_id, date_iso|"")；_building 防抖、_last_committed 去重、set_readonly；样式与金额编辑单元格范式一致
- amount_page：日期列 setCellWidget 承载 DateEditCell（_date_cells 缓存复用）；提交 → `source="manual"`，清除 → 空值空来源
- **OCR 不覆盖手动**：`_persist_ocr_document_date` 先查 source=="manual" 直接返回（手动修正优先）
- 显示联动：比对页 `_set_date_cell` 支持 manual（tooltip「手动设置」）；preview_panel 标注扩展「票面/手动/文件」

### 验证（Claude 独立抽查 8 项全过 + Codex 断言）
- 单元格放置、OCR 日期载入、空显示「未设置」、手动设置落库 manual、**OCR 不覆盖手动、非手动文件 OCR 正常更新**、清除落空、比对页 manual 显示与标注
- `check.sh` 全绿；回归（金额编辑/确认列、列索引）通过

### 遗留
- 真机复验：日期控件视觉、170px 列宽、日历弹窗在真实桌面的表现

## 金额页日期列：重叠修复 + 选择器放大 审查结论（2026-09-28 追加）

**结论：通过 ✅**（已按规则提交推送）

### 根因（Codex 离屏实证）
重叠**不是控件挤压**（旧 170px 列内文本区 102×34、drop-down 16、清除按钮 42×36 互不相交），而是 `_populate_table` 先用 set_data 往日期列写入了日期文本、之后又被**透明背景的 DateEditCell 覆盖** → 表项文字与编辑器文字**双层绘制**（"未设置"态差异 246 像素、垂直位置不同）。

### 修复
- amount_page：日期表项**留空**、仅由 DateEditCell 绘制（消除双层）；`DATE_COL_WIDTH 170→200`
- date_edit_cell 放大：QDateEdit 高 40/字号 13/padding 6/drop-down ≥26px；清除按钮 48×40；日历弹窗最小 252×286、单元格 ≈35×34、今天/选中 #409eff
- 取舍：内嵌日历已达 ≥30×28 单元格目标，暂无必要切换独立大日历对话框（真机高 DPI/触屏仍局促再议）

### 验证（Claude 独立抽查 9/9 + Codex 几何断言）
- 日期表项无文本（双层消除）、列为 DateEditCell、高 40/字号 13、日历弹窗 ≥252、列宽 200、日期载入、手动编辑落库 manual、金额/确认列控件在位
- Codex 几何 JSON 断言全 true（含 line_vs_arrow_disjoint）；`check.sh` 全绿

## 重命名后位置保持 + 列表透气 审查结论（2026-09-28 追加）

**结论：需修（1 高 / 2 中）→ 已派第 2 轮** ｜ 审查人：Claude Code

### 实现（Codex）
- `store.rename_linked_files`：保序重键（`{new if k == old else k: v}`），重命名条目不再跳到列表末尾
- 新增 `app/ui/widgets/list_view_state.py`：按「顶层行 index」捕获/恢复（当前行、滚动值、展开项）——重命名会改 file_id，按 id 恢复必然失效
- `file_list_panel`：`_populate_tree` 末尾恢复视图；`reload_from_store(keep_view=True, advance=False)`；定位栏空闲整行隐藏；行 padding 6→2px
- `compare_page`：上下改为垂直 QSplitter（初值 420/280 + stretch 3:2、可拖动、列表禁折叠）；`_on_rename` 改走 `reload_from_store(keep_view=True, advance=True)`（不再整目录重扫）

### Claude 独立抽查（自建夹具 24+24 真实文件，19/19 通过）
- 重命名后发票/支付 index 12→12、列表前缀顺序不变、滚动 300→300、选中 12→13（顺延且钳制）、重命名不增删列表项
- **1440×920 可视行数 4~5 → 8**（viewport 287 / row_h 33）；1366×768 为 5 行；splitter 实测 426/284（0.60）
- 定位栏默认隐藏/定位时显示/清除后隐藏；切换文件夹回顶部；查找仍定位；组合重建仍可用
- 直接修正两处：行 padding 4→2px（省 4px/行，+1 行）、`setSizes([3,2])`（伪比例、实为像素）→ `setSizes([420,280])`
- 回退 Codex 误改的 `main.py`（仅丢末尾换行）——**提醒：勿动无关文件**

### 第 2 轮修复项（Codex 执行）
1. **[高] 组合成员重命名后 `combos[*]["file_ids"]` 未更新**（`store.py:322-336` 交叉引用循环只覆盖 linked_*_ids 与 associations；全库仅 combos 遗漏）。后果：成员重命名后脱离组合、组合显示 2 成员只渲染 1、`get_combo_total()` 漏算、自动匹配单元可能重复计入。→ 在同一 old→new 循环里补 combos 重映射。
2. **[中] 恢复时可能把「隐藏行」设为当前项**（`list_view_state.py:55-62`）：查找过滤命中被重命名文件、或定位过滤仍持旧 file_id 时，该行已隐藏，`setCurrentItem()` 仍会设中并触发 `fileSelected`（预览/按钮指向不可见文件）。→ 目标行 `isHidden()` 时跳过选中断；`advance` 时跳过隐藏行与组合父行（组合父行无 ROLE_FILE_ID，选中后不会发 fileSelected、按钮禁用），并回退到捕获行。
3. **[中] 重命名后定位过滤失效**：file_id 变了，`_located_file_ids` 里的旧 id 全部失配（面板显示"已定位 0 个关联文件"且行被隐藏）。→ `_on_rename` 成功分支先 `clear_located_files()` 再重载（两侧）。
4. **[中] 保序重键未防新键冲突**（`store.py:305-320`）：若 `new_id` 已存在（同路径+同秒 mtime 的极小概率），字典推导会静默合并两条记录、丢数据。→ 显式判断：`new_id != old_id and new_id in dict` 时返回 None（宁可失败也不静默损坏）。

### 记录不修（本轮）
- **[接受] 预览区可被拖到 0**：`setCollapsible(1, True)` 会越过 120px 最小高度——这正是「列表优先」的诉求，属预期行为（拖回即可），`setMinimumHeight(120)` 仅作初始下限。
- **[既有·待人类拍板] 双文件重命名非原子**：`store.py:284-291` 第一段 `os.rename` 成功后第二段失败即 `return None`，磁盘已改而 Store 未改（下次扫描标 missing、可能丢关联）。非本次引入 → 记入 backlog。

### 第 2 轮复审结论（2026-09-28 追加）：通过 ✅

Codex 第 2 轮只改 3 个允许文件（store.py / list_view_state.py / compare_page.py），逐条核对：

| 修复项 | 实现核对 | Claude 独立抽查 |
|---|---|---|
| 组合成员重映射 | `store.py` 在 old→new 循环内补 `combos[*].file_ids` 替换（`_data.get("combos", [])` 防御式） | ✅ 成员换成新 id、旧 id 不残留、组合仍 2 成员、get_combo_total 不漏算、index 3→3、滚动 76→76 |
| 隐藏行/组合父行 | `list_view_state._is_visible_file_item`（未隐藏 + 序号列带 file_id）；advance 向后找文件行、找不到回退捕获行 | ✅ 顺延落点 INV_05.pdf（跳过组合父行）；查找过滤下重命名后 `currentItem()=None`、`selectedItems()=[]` |
| 定位过滤失效 | `_on_rename` 成功分支先 `clear_located_files()` 两侧再重载 | ✅ `_located_file_ids` 清空、定位栏隐藏、列表 12 行完整、当前项可见 |
| 重键冲突保护 | 冲突判断移到**磁盘重命名之前**（这点很关键：被拒的请求不应改盘） | ✅ 注入同 id 条目后返回 None、记录数 4→4 不变、原文件仍在磁盘、目标新文件未创建 |

- Claude 另修 2 处：① `set_located_files` 只在进入定位视图（file_ids 非空）时清空查找词 —— 否则本轮新加的 `clear_located_files()` 会连用户搜索词一起吞掉（`清除` 按钮语义也更正确）；② `_is_visible_file_item` 补注释说明 ROLE_FILE_ID(=UserRole) 的取值耦合。
- **独立抽查合计 39/39 通过**（第 1 轮 19 + 第 2 轮 20），`check.sh` 全绿。
- Codex 第 2 轮 `git status` 干净（未再触碰 main.py）；上一轮误改的 main.py 末尾换行已由 Claude 回退。

**遗留（已记入 backlog）**：双文件重命名非原子（P2，既有问题，待人类拍板）；file_list_panel.py 1020 行、store.py 923 行超 800 约束（P3）；分隔条位置未持久化（P3）。

## 组合定位 / 组合重命名 / 按钮布局 审查结论（2026-09-28 追加）

**结论：通过 ✅**（已按规则提交推送） ｜ 审查人：Claude Code

### 1. 组合右键「定位所有」另一侧空白 —— 一行解包 bug（Claude 定位根因）
- `file_list_panel._combo_partner_ids` 写成 `for pid, _ in self._partner_entries(f)`，
  而 `_partner_entries` 返回 **(文件名, file_id)** → 传出去的是**文件名**当 id 用，
  另一侧 `set_located_files()` 按 id 过滤 → 全部不匹配 → 空白。
- 其余 4 处调用点（:461/:831/:936/:963）本来正确，故只有「组合菜单」路径坏、
  子文件右键与「取消所有关联」正常——与人类观察完全吻合。
- 修复 1 行；Claude 独立抽查：`_combo_partner_ids` 返回 file_id（非文件名）、
  发票组合定位→支付侧只剩「支付组合B」且展开、反向同理、清除定位恢复全量。

### 2. 组合重命名（新增）
- 新增 `app/core/rename_plan.py`（Qt-free，101 行）：按 (目录,扩展名) 编号规划目标名、
  冲突检测（组外文件占用即失败，不跳号）、**两阶段重命名 + 失败回滚**、重键碰撞检测。
- `store.rename_group(invoice_ids, payment_ids, new_base, combo_ids)`：先算全部目标名 →
  冲突检测 → 磁盘两阶段改名 → 重键（保序）→ `_remap_file_ids`（linked_*_ids/associations/
  combos.file_ids）→ 组合名同步 → 只 `_save()`+`_notify()` 一次。
  `rename_linked_files` 降为薄封装，`(发票名, 支付名)|None` 语义不变。
  **顺带修掉 backlog 的 P2「双文件重命名非原子」**：失败回滚，不再留磁盘/Store 不一致。
- UI：`重命名关联` 启用条件 = 两侧均有选中（文件或组合）且两组间 ≥1 条关联
  （`group_link_exists`）；默认名优先组合名；组合场景提示「已统一重命名 N 个文件…」。
- Claude 独立抽查：组合重命名 → 磁盘 `统一名.pdf/统一名_2.pdf`、组合名同步、组合
  file_ids 指向新 id、**关联按编号对齐仍成立**、未参与组合的文件未被改名、
  列表项数/滚动/顺延保持；失败路径（目标被占用）返回 None 且磁盘零改动。

### 3. 布局
- 删除顶部工具栏行；`自动比对` 与关联三键同一行（左起第 1 个），两侧等量 stretch 居中，
  进度标签贴该行最右；页面只剩「列表块 + 按钮行」两段。
- Claude 独立抽查（1440×920）：按钮同行同 y、顺序正确、位于列表下方、标签在右、
  `layout().count()==2`、列表块 y=0、**可视行数 8 → 9**。

### 验证
- Claude 独立抽查 **34/34**（本轮 27 + 回归 7），`check.sh` 全绿；README 第 4 条已同步新语义。
- 本轮我 3 个断言写错（夹克里混入未参与组合的文件、按位置猜配对）→ 修正断言后全过，
  代码行为正确；沿用既有教训：**夹具必须模拟真实数据分布**。

### 遗留 / 提示
- 编号是「跨两侧共用」的（键为 (目录,扩展名)）：若发票与支付恰好同目录同扩展名，
  编号会连续（`新名.pdf/新名_2.pdf/新名_3.pdf`）。实际两者分属不同文件夹，无影响。
- `rename_paths` 两阶段会在同目录短暂出现 `.rectmp` 临时名；崩溃中断可能残留
  （与既有单文件路径同级风险，已由回滚覆盖异常路径）。
- backlog：store.py 954 行、file_list_panel.py 1020 行仍超 800 约束。

## 改名自愈 / 失效关联清理 / 导出 Excel 审查结论（2026-09-29 追加）

**结论：通过 ✅**（已按规则提交推送） ｜ 审查人：Claude Code

### 1. 资源管理器改名后组合掉队 + 关联/OCR 丢失
- **根因**：`generate_file_id = sha1(path|mtime)` 把路径算进 id → 改名即换 id；
  旧记录被标 `missing` 但仍被组合/关联引用，新记录一无所知 → 组合成员掉队但计数不变，
  OCR 金额与票面日期需重跑。
- **实现**：新增 `app/core/file_identity.py`（Qt-free 纯逻辑）：身份键 `(size, mtime, ext)`，
  **候选唯一且未被多条新记录争抢才采纳**；`merge_*` 在「标 missing 后、`_prune_shell_combos` 前」规划并
  `_adopt_renamed`：新记录继承 amount / document_date(_source) / `linked_*_ids`，删除旧 missing 记录，
  `_remap_file_ids` 重映射（含 `combos.file_ids`）；NEW·旧 id 不复用（复用会导致下次重扫再次对不上）。
- **新增**：文件行右键「重命名」（组合成员、独立文件皆可），走 `rename_group` 单文件模式，**不 advance**（停原位）。
- **Claude 独立抽查**：真实 `os.rename` + 重扫 → 组合仍 2 有效成员且指向新 id、旧 missing 记录已删、
  关联/`1234.5` 金额/`2026-03-05` 票面日期全部接管、列表无孤立顶层项；**歧义场景（两条同 size+mtime+ext）
  不误配**；应用内改名 → 组合成员身份保留、行 index 不变、金额 88.0 与手动日期 2026-07-01 保留、磁盘确已改名。

### 2. 失效关联仍计数且无法清理
- **根因**：`_link_state` 直接数 `linked_*_ids` 原始条数（不校验对象是否存在/是否 missing）；
  `_partner_entries` 跳过 missing 对象 → 展开子行与「取消所有关联」都碰不到这些 id；
  「取消关联」按钮要求两侧都选中，失效对象在另一侧根本选不到 → 无处可清。
- **实现**：`_link_state` 改为 4 元组（有效?/有效数/全自动/失效数），只统计「记录存在且非 missing」；
  `StatusBadge` 宽 78→96 并支持 `已关联 N ⚠M` / `失效 N`（警示黄 + tooltip）；新增
  `store.prune_dangling_links(file_id)`（按文件、只动自身一侧引用，**不静默删对方数据**）；
  三处「取消所有关联」入口连带清理；新增右键「清理失效关联」（仅确有失效时出现）。
- **Claude 独立抽查**（复刻人类场景）：关联 2 成员组合 → `已关联 2`；删一侧后 → `已关联 1 ⚠1`（**不再是 3**）；
  再关联一张 → `已关联 2 ⚠1`（失效不叠加）；清理返回 1 条、失效条目与 associations 残留清空、徽标回到 `已关联 2`。

### 3. 导出 Excel
- **实现**：`[导出 Excel]` 加入按钮行（重命名关联右侧）；`app/core/excel_export.py` 用**标准库**
  `zipfile` + XML 写最小 xlsx（全 `inlineStr`，五类 XML 转义），**未新增任何依赖**（openpyxl/xlsxwriter 本机均无，
  pandas 是传递依赖且写 xlsx 同样需要引擎，故不用）；`build_association_rows` 只导出**有效关联**，
  含金额（2 位小数）、日期（附票面/手动/文件来源）、所属组合、自动/手动。
- **Claude 独立抽查**：`zipfile` + `ElementTree` 读回 → 五个必要成员齐全、行数 = 表头 + 有效关联数、
  表头正确、金额与文件名与 store 一致；**真实 `&` `'` 文件名**与**合成 `< > "` 值**均无损读回；
  UI 全链路（打桩 `QFileDialog`）点击导出按钮 → 文件生成、提示「已导出 1 条关联」、内容含改名后文件名。

### 验证
- Claude 独立抽查 **44/44**（主脚本 29 + UI 层 15），`check.sh` 全绿，`excel_export` 自检 OK，
  `file_identity` 歧义/唯一两分支直测 OK。README 已补「单文件重命名 / 导出 Excel」与两条 FAQ。
- **Codex 反向指出我脚本两处错误**（值得记录）：① 我把「1 有效 + 1 失效」断言成 `已关联 2`，
  按 brief 的有效计数规则应为 `已关联 1 ⚠1`（实现是对的）；② 我用 `< >` 做真实 `os.rename`，
  Windows 非法文件名会崩。→ 已改为打桩喂值 + 只用合法字符做真实改名。

### 遗留（已记 backlog）
- `store.py` 1047 行、`file_list_panel.py` 1117 行仍超 800 行约束（本轮新逻辑均落在新模块）。
- 改名自愈是启发式（size+mtime+ext）：极端情况下同尺寸同秒修改的两个文件无法区分 → 按设计跳过不猜。

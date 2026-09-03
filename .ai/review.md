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

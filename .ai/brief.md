# 任务简报：端口级拖线判定 + 模块库着色 + 对话框最大化

## 问题 1（P1 交互）：拖线目标应为「端口级」命中与高亮

**用户实测**：从支付记录模块**输入端**拖出连线，移到匹配模块上时**匹配模块的输入端（左）亮起**；而正确语义应让**匹配模块输出端（右）亮起**（因为发起端是支付.in，目标必须是匹配.out）。用户期望：拖到目标模块的错误一侧（如匹配.in 区域）时端口不亮、临时线红色、松开不连——即**按端口左右侧判定**而非整模块判定。

**现实现（问题）**：`canvas.py` update_temp 只做 kind 级判定（目标模块 kind 是否合法）→ `_set_hover_target` 置整模块 `_link_target` → items.py 里 `_link_target` 固定高亮**左输入端口**（`_draw_port(…, self._link_target)`），导致反向拖线时亮错端口。

**规格**：
1. 目标命中按**端口侧**：把目标模块场景范围按左右半区分「输入侧（左半，含 in 端口 ±容差）」「输出侧（右半，含 out 端口 ±容差）」「中部」。
2. 合法性矩阵（发起端口侧 × 目标端口侧）：
   - 发起 out（正向，现有）：合法目标 = 匹配模块**输入侧**（悬停匹配.in 侧亮输入端口）；悬停输出侧/中部 → 目标无效（不亮、临时线红）；发票/支付模块输入侧同样无效
   - 发起 in（反向，新行为）：合法目标 = 发票模块**输出侧**（拖匹配.in 时）；= 匹配模块**输出侧**（拖支付.in 时）；悬停到目标模块输入侧/中部或非法 kind → 无效红
   - 释放时命中必须也在合法侧才建线；仍经 model.create_wire/can_connect 兜底（矩阵不变）
3. 端口级高亮：items 的 `_link_target` 拆为 `_link_target_in`/`_link_target_out`（按命中侧亮对应端口 + 模块边框描同色），canvas `_set_hover_target(item, side)` 传入侧别
4. 现有正向（输出端口发起）行为不回归：拖 inv.out → 悬停匹配.in 侧亮输入端口，此前就是如此

## 问题 2（P2 视觉）：模块库三项用不同颜色呈现

用户改主意（v2 中性化 → 现在要彩色区分）：模块库「电子发票/支付记录/匹配」三张卡片**分别着色**。用画布节点同一语义色：发票蓝 #409eff（浅底 #ecf5ff）、支付绿 #67c23a（#f0f9eb）、匹配橙 #e6a23c（#fdf6ec）。实现：`_PaletteCardDelegate` 按 kind 取色（图标/卡片底色/边框/选中 hover 用类型色），保持卡片结构与 QDrag/mime 协议不变。

## 问题 3（P2 布局）：自动比对界面打开即最大化占满屏幕（像主界面）

MatchFlowDialog 当前固定 resize(1580,920)。要求打开即占满可用屏幕（与主窗口最大化观感一致）：改为**启动时最大化**（availableGeometry 或 showMaximized 语义，主界面即最大化）。实现建议：在 dialog 构造后（或 compare_page exec 前/或 dialog 内 showEvent/QTimer）最大化；保留 setMinimumSize；布局列距等无需再为固定宽优化（画布随视口自适应场景滚动即可）。**同时检查三列布局常量**：最大化后视口很宽，簇横向留白会变大——可把簇间改为横向也多排？不，用户此前选"加宽不改布局"，保持簇纵向堆叠；列距常量维持现 360 或适度再拉开（评估后定，别让单簇占太窄）。

## 相关文件
- `app/ui/widgets/match_flow/items.py`（端口侧高亮状态拆分）、`app/ui/widgets/match_flow/canvas.py`（目标侧判定/linking）、`match_flow_dialog.py`（palette delegate 着色 + 对话框最大化）
- 不改 model.can_connect 矩阵/执行语义/store

## 验证要求
- 问题 1：offscreen 真实对话框 + viewport 事件模拟：拖 支付.in → 悬停匹配**输出侧** → 输出端口高亮态置位（断言 item._link_target_out True/_link_target_in False）→ 释放建线（match→payment 方向）；拖 支付.in → 悬停匹配**输入侧** → 临时线红、无端口亮、释放不建线；拖 匹配.in → 悬停发票**输出侧**建线 invoice→match；正向 inv.out→匹配.in 行为回归断言；中部悬停无效
- 问题 2：像素断言三类卡片主色像素（蓝/绿/橙各 >0）+ 渲染截图 _tmp_diag/palette_colored.png
- 问题 3：对话框 exec 前尺寸/窗口状态断言（showMaximized 后 isMaximized=True 或可用屏占比 ≥95%）；布局不崩、场景可滚
- `D:/Using_small_tools/Git/bin/bash.exe scripts/check.sh` 全绿；临时脚本用后清理（截图留 Claude 审后删）；不 commit，交 Claude Code 审查 + 人类真机复验

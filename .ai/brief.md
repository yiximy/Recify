# 任务简报：按 PyFlowGraph 范式改造自动比对画布（交互与视觉）

## 背景与依据

人类指定参考 **https://github.com/bhowiebkr/PyFlowGraph**（MIT License, © 2025 Bryan Howard）重构画布**交互与视觉**。已尽调其源码（Claude Code 克隆至临时目录提取规格）：PySide6 节点图编辑器，核心做法可直接借鉴；它是含执行引擎/Mini-IDE 的完整应用（~13.4k 行），**不整包引入**（新增 markdown-it-py 等依赖且严重超范围），只**对齐其交互范式与视觉语言**到现有 `match_flow` 画布（保留本项目的自动铺/聚合/端口级判定/执行管线/store 对接）。

## A. 交互范式（跟随 PyFlowGraph，人类已拍板）

当前：左键空白拖 = 平移、Ctrl+滚轮 = 缩放、右键 = 菜单。
改为（PyFlowGraph 范式）：
1. **左键空白拖 = 框选**（RubberBandDrag 语义；框选样式用 Elegant Light 蓝系半透填充+虚线边）。框选多选后：拖动任一选中节点=整体移动、Delete 批量删除（现有 delete_selected 已支持多选，接线后验证）
2. **平移 = 中键拖 或 右键拖**（press+move 超过阈值即平移，光标改 ClosedHand）
3. **右键轻点（位移 < 3px 且未平移）= 上下文菜单**（菜单从 press 迁移到 release 判定；节点/连线/画布菜单均保留）
4. **滚轮 = 直接缩放**（PyFlowGraph：无修饰键；步进 1.15，钳制 0.4~2.5 沿用）；不再需要 Ctrl+滚轮
5. 不冲突既有：连线拖拽中（linking）左键语义不变；Esc/失焦取消、双击配置、端口双向拖线（四路径）全部保留

## B. 视觉（对齐 PyFlowGraph 的核心视觉语言）

1. **连线颜色 = 起点模块类型色**（发票模块出线=蓝 #409eff；匹配模块出线=橙 #e6a23c），线宽 **3px**；hover = 4px + 亮化；选中 = 4px + `lighter(150)`（替换现有统一灰蓝 #a8b2c1）
2. **选中/悬停节点时其关联连线同步高亮**（PyFlowGraph `highlight_connections` 语义）
3. 节点卡片升级：圆角 8 保留；**标题栏垂直渐变**（类型色 `lighter(115)` → 本色）+ 标题栏底部 `darker(120)` 分隔线；卡片**微阴影**（boundingRect 扩边绘制半透明阴影，注意 sceneRect 计算不受污染）
4. 选中描边：类型色 `lighter(130)` 2px（替换固定蓝框）
5. 网格：双层（细 6px 更浅 + 主 24px），沿用现有浅色底
6. 端口：半径 6 + 白描边 2 保持；端口级判定/高亮逻辑不变

## C. 明确不做（防范围蔓延）

- 不做 reroute 中转节点（双击连线插入）、不做分组容器（group）、不做撤销重做系统（均超出"交互与视觉"，如需要另立任务）
- 不采用其 dark theme；保持 Elegant Light + MonkeyQt 一致
- 不动 `model.py`（矩阵/校验/链）、自动铺聚合、confirm 管线、`store.py`、`compare_page.py` 逻辑（文案若受影响微调）

## D. 相关文件

- `app/ui/widgets/match_flow/canvas.py`：FlowCanvas 交互范式（框选/平移/菜单 release 判定/滚轮缩放/网格双层）、FlowScene 选中联动连线高亮、连线颜色取值
- `app/ui/widgets/match_flow/items.py`：FlowNodeItem 渐变标题栏/阴影/选中描边、FlowWireItem 颜色与线宽/选中态、悬停联动
- 参考实现位置（临时克隆，实现时可再取）：`/tmp/tmp.yqlcKEW3mq/PyFlowGraph/src/core/{node,pin,connection}.py`、`src/ui/editor/node_editor_view.py`（如果临时目录已被清理，按 brief 规格实现即可，不必重新克隆）

## E. 验证要求（Codex 必跑，含渲染级）

1. 交互：框架选（模拟左键空白拖 → `scene.selectedItems()` 断言多选）、右键拖平移（滚动条值变化）、右键轻点走菜单路径（monkeypatch QMenu.exec 计数断言）、滚轮缩放（transform m11 变化且钳制生效）
2. 视觉：连线 pen 颜色 == 起点模块类型色（属性断言）+ 渲染像素（蓝/橙线像素 > 0）；选中节点后 incident 连线选中态断言；节点阴影/渐变标题栏像素断言；网格双层
3. 回归：端口双向拖线四路径、自动铺 1+1+N 结构、confirm 落库计数、场景矩形不漂移（首屏相交）、`D:/Using_small_tools/Git/bin/bash.exe scripts/check.sh` 全绿
4. 截图 `_tmp_diag/` 留 2-3 张（框选态/连线类型色/整体）供 Claude 审查后删；临时脚本用后清理

## F. 约束

- 不新增第三方依赖；不改 `data/store.json`、`config/app_config.json`；不 commit（完成后由 Claude 审查并按既定规则提交推送）
- 保留 `items.STYLE` 端口/类型语义色作为唯一配色来源（连线颜色从中取，别再引入第二套色表）

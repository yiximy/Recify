# 任务简报

## 当前任务

修复「比对关联模式」两个问题。版本回退点：`265bc72`（此前 commit），当前工作区已含上一次 5 问题修复（未提交）。

## 问题 1：多选（含组合父行）时「取消所有关联」只对右键文件生效

**位置**：`app/ui/widgets/file_list_panel.py` `_on_tree_context_menu`

**用户现象**：
- 选中「16 个文件 + 1 个组合父行」→ 右键「取消所有关联」→ 弹出「确定要取消[高速费1.pdf]的全部关联吗？」（只对右键那个文件）
- 取消选中组合父行 → 右键「取消所有关联」→ 弹出「确定要取消16个文件的全部关联吗？」（批量，正确）

**根因**（代码分析）：
```python
top_files = [
    i for i in selected
    if i.parent() is None and i.data(COL_SEQ, ROLE_FILE_ID)
]
multi = (
    is_top_level
    and len(top_files) >= 2
    and len(top_files) == len(selected)
)
```
组合父行是顶层项但**没有** `ROLE_FILE_ID`（只有 `ROLE_COMBO_ID`），所以当选中含组合父行时 `top_files` 少算一个 → `len(top_files) != len(selected)` → `multi=False` → 走单文件分支。

**要求**：
- 多选判定应把组合父行也纳入：选中的顶层项 = 顶层独立文件 + 组合父行（按 `ROLE_COMBO_ID` 识别）
- 「取消所有关联」对组合父行应展开为**其全部成员文件**一起取消
- 确认框文本：`确定要取消 N 个文件的全部关联吗？`（N = 独立文件数 + 组合成员数）
- 完成提示：`已取消 N 个文件的全部关联，共 M 条`
- 保持「定位所有」仍按单选/右键文件逻辑（不被多选影响）

## 问题 2：父子行视觉区分不足（drawRow 颜色太浅）

**位置**：`app/ui/widgets/file_list_panel.py` `_HierarchyTree.drawRow` + 配色常量

**诊断结论（像素级验证）**：
Claude Code 已用离屏渲染 + PIL 像素分析确认：**drawRow 代码本身生效**——截图中实际存在 4 种背景色：
- `#ffffff` 独立文件行（RGB 255,255,255）
- `#dce8fb` 关联子行（RGB 220,232,251）
- `#ecf5ff` 组合父行（RGB 236,245,255）
- `#f5f7fa` 成员行（RGB 245,247,250）

但 4 种颜色与白色差异仅 10~35 RGB 值，肉眼几乎无法分辨，用户误以为"代码没生效"。

**用户要求**：先用**红色**测试子行背景是否真正生效（例如关联子行用 `#ffdddd` 或更红），确认渲染通路没问题，再做最终配色。

**要求**：
1. **红色测试**：将关联对象子行背景临时改为明显红色（如 `#ffcccc`/`#ffdddd`，文字保持深色可读），成员行改为次明显色（如 `#fff3f3` 或保留浅灰加深），组合父行保持浅蓝加深——确保 4 层肉眼可辨
2. 强调条加宽或加深（`_ACCENT_WIDTH` 可到 5-6px）
3. 如果红色在真机仍不生效 → 排查是否被 QSS `QTreeWidget::item` 或主题覆盖（可改用 `setBackground` + 移除 QSS 的 `::item { background: transparent }`，或在 `drawRow` 中 super() 之后再 fillRect）
4. 完成后再综合调色（可保留红色系或换回柔和的对比色系，但必须肉眼可辨）

## 验收标准

- [ ] 问题 1：多选（含组合父行）→「取消所有关联」→ 确认框提示全部文件数（独立+成员），全部解除
- [ ] 问题 1：不含组合父行的多选行为不回归（仍批量）
- [ ] 问题 2：真机截图/离屏像素验证 4 层背景色肉眼可辨（子行先用红色验证）
- [ ] 全部通过 `bash scripts/check.sh`
- [ ] 不破坏：定位/组合/批量关联/重命名/一键关联/自动比对审阅

## 相关文件

- `app/ui/widgets/file_list_panel.py`（两个问题都在这）

## 备注

- 先读 `AGENTS.md`、`CLAUDE.md`、本 brief，再写 `.ai/plan.md`
- 不要改 `data/store.json` 和 `config/app_config.json`；不新增第三方依赖
- 每次修改后跑 `bash scripts/check.sh`（Windows：`D:/Using_small_tools/Git/bin/bash.exe scripts/check.sh`）
- 可参考 `_debug_shot.png`（离屏截图）和 `_debug_screenshot.py`（渲染脚本）验证配色；验证后清理这两个调试文件

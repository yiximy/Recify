# 任务简报（修复轮 4：自动铺按发票单元聚合 + 空壳组合清理）

## 问题 1（P1）：自动铺冗余——一对多应聚合为「1 发票模块 + 1 匹配模块 + N 支付模块」

**用户反馈**：一张发票 A 自动匹配 3 张支付记录时，当前自动铺出 3 条独立链（3 个匹配模块各连 1 张支付），冗余。期望：**1 个发票模块 → 1 个匹配模块 → 3 个支付模块**（匹配模块输出端可接多个支付模块）。

**规格变更**：
1. **自动铺聚合**：按**发票侧单元**（单文件单元或组合单元）聚合所有候选——同一发票单元与多个同额支付单元匹配时只建 1 个匹配模块；连线 = 发票模块.out→匹配.in 一条；匹配.out → **每个**同额支付单元模块一条（多出线）。支付模块跨候选仍共享。多发票单元 × 多支付单元（多对多）→ 每个发票单元各自 1 个匹配模块（发票单元是聚合键）。
2. **连线矩阵不变**（invoice.out→match.in、match.out→payment.in）。
3. **执行/校验放宽**：匹配模块「恰 1 条发票入线」保持；支付出线由「恰 1」放宽为「≥1」（0 仍报错）；`executable_chains` 返回 (match, inv, [pays…])；确定管线 = 每匹配模块的发票单元 × **每个**出线支付单元逐一容差校验产 pair；跳过汇总逐支线。
4. 节点/匹配模块金额显示 = 发票单元金额；接入摘要「支付 N 路」沿用（现有 items 已支持）。布局算法适配（match 列每发票单元 1 节点）。
5. 回归注意：手动搭链时用户可能仍想一条链一个支付（现行为），放宽后手动连 1 个支付完全兼容；删单条支线 = 删 match→pay 线。

## 问题 2（P2）：配置界面出现「已删除」的空壳组合

**用户反馈**：发票/支付模块配置界面的组合候选里，显示"以前组合过但已删除"的组合。

**Root cause（Claude Code 实证，查了 data/store.json）**：3 个现存组合（安徽项目开发所使用的AI费用1 / 机票1+附加项 / 酒店住宿费）的**成员文件全部 missing**（源文件移除或文件夹切换重扫标记缺失）。组合记录本身未删——比对页树因成员全 missing 不显示其成员（观感像删了），而 `config_dialog` 的组合候选列表直接 `store.get_combos(kind)` **不过滤无效组合** → 空壳组合被列出来。

**修复规格**：
1. **展示层**：config_dialog 组合候选（及 dialog 侧 `_find_combo_id` 反查）只接受「至少含 1 个非 missing 成员」的有效组合；无效组合不进候选列表。对部分成员缺失的组合可标注缺失成员数（若简单）。
2. **治本（评审后定）**：为 store 增加空壳组合清理——建议在 `merge_invoices/merge_payments`（重扫合并后）自动移除「该 kind 下成员全部 missing」的组合（组合内文件已全部消失，保留无意义且引擎本就跳过）；需兼容 `config/app_config.json` 与 store 旧数据（setdefault 模式）。方案若涉及语义风险（自动删用户分组），codex 先在窗口说明取舍再实现。
3. 行为一致：FileListPanel 树中组合父行显示逻辑不必改（现状 OK）；已有关联到全 missing 组合成员的关联不动。

## 相关文件
- 问题 1：`match_flow/model.py`（executable_chains/validate/chain 结构）、`match_flow_dialog.py`（_build_candidate_chains/_layout_chains/_on_confirm）、`match_flow/items.py` 摘要若需适配
- 问题 2：`match_flow/config_dialog.py`（候选过滤）、`app/core/store.py`（空壳清理，评审后）
- 不改 data/store.json、config/app_config.json（用户数据只读——空壳清理作用于**未来** merge 行为，不清现有数据；现有 3 个空壳组合由用户在树中删除或不管）；不新增依赖；每次修改跑 `D:/Using_small_tools/Git/bin/bash.exe scripts/check.sh`；临时脚本用后清理；不 commit，交 Claude Code 审查 + 人类真机复验

## 验证要求（Codex 必跑）
- 问题 1：离屏临时 store 构造 1 发票单元 × 3 支付单元（同额）→ 自动铺 = 1 inv + 1 match + 3 pay、match.out 3 条；多对多（2×2）→ 2 match 各 2 出线；confirm 全量落库 4 条（2×2）；删一条支线后 confirm 3 条；渲染断言（色带 > 0 + 首屏相交）
- 问题 2：临时 store 造成员全 missing 组合 + 有效组合 → config 候选仅含有效组合；merge 清理后 get_combos 不含空壳；check.sh 全绿

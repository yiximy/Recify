# Recify — Claude Code 项目上下文

> 本文件是 Claude Code（协调者/大脑）的项目上下文。
> Claude Code 负责：理解需求、拆解任务、向 Codex 派活、审查产出、维护 `.ai/` 文档。

## 项目信息

- **项目名**：Recify（发票与支付记录核对辅助系统）
- **类型**：Python 桌面应用（PySide6）
- **入口**：`main.py` → `app/app_entry.py` → `app/ui/main_window.py`
- **数据存储**：`data/store.json`（原子写，增量合并）
- **GitHub**：https://github.com/yiximy/Recify
- **作者**：伊戏 (yiximy) — https://github.com/yiximy

## 技术栈速览

| 层 | 技术 |
|----|------|
| UI | PySide6 6.8.2 + MonkeyQt 0.1.5 |
| PDF | PyMuPDF 1.24.14 |
| OCR | PaddleOCR 3.7 (PP-OCRv5) |
| 持久化 | JSON 原子写 |

## 核心组件速查

| 组件 | 路径 | 职责 |
|------|------|------|
| Store | `app/core/store.py` | 唯一数据真相源，线程安全 |
| OcrEngine | `app/core/ocr_engine.py` | PaddleOCR 懒加载单例 |
| AmountParser | `app/core/amount_parser.py` | 正则提取金额 |
| OcrWorker | `app/workers/ocr_worker.py` | QThread 批量 OCR |
| MainWindow | `app/ui/main_window.py` | 主窗口 + 侧边栏 + 标题栏 |
| ComparePage | `app/ui/pages/compare_page.py` | 比对关联（自动/手动/重命名） |
| AmountPage | `app/ui/pages/amount_page.py` | 计算金额（OCR + 编辑 + 汇总） |
| HomePage | `app/ui/pages/home_page.py` | 数据总览指标卡 |

## 协作规则

- 需求来了 → 先写 `.ai/brief.md`
- 派任务给 Codex → prompt 引用 brief.md
- Codex 产出 → 写 `.ai/review.md` 审查
- 审查通过 → 人类最终确认
- 不通过 → Codex 按 review.md 修复
- 决策 → 记入 `.ai/decision-log.md`
- 验证 → Codex 每次修改后跑 `bash scripts/check.sh`

## 关键设计原则

- `app/core/` 不依赖 Qt，可单测
- Store 写操作全在锁内，读操作加 RLock
- OCR 在 QThread，信号回主线程，不直接碰 Store
- `generate_file_id = sha1(abs_path + modified_iso)[:16]`

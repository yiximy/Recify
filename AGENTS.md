# Recify — Codex 项目规范

> 本文件是 Codex 的工作规范。Codex 是**实现者**，负责分析、方案、实现、修复；
> Claude Code 是协调者/大脑，负责分配任务与审查结果。

## 项目信息

- **项目名**：Recify（发票与支付记录核对辅助系统）
- **类型**：Python 桌面应用
- **UI 框架**：PySide6 6.8.2 + MonkeyQt 0.1.5（Elegant Light 主题）
- **OCR 引擎**：PaddleOCR 3.7（PP-OCRv5，本地 CPU）
- **PDF 渲染**：PyMuPDF 1.24.14
- **入口**：`main.py`
- **数据存储**：`data/store.json`（原子写 JSON）
- **GitHub**：https://github.com/yiximy/Recify

## 代码规范

- Python 3.10+，遵循 PEP 8
- 所有函数签名使用类型注解
- 导入顺序：标准库 → 第三方 → 项目内部（按 isort）
- 注释与文档字符串使用中文
- 保持函数短小（<50 行）、文件聚焦（<800 行）
- 不可变性优先，避免副作用

## 项目架构

```
UI 层 (app/ui)       ─ py 文件，依赖 Qt
  pages/             ─ home_page / compare_page / amount_page
  widgets/           ─ 可复用组件
业务层 (app/core)    ─ 纯 Python，不依赖 Qt
workers (app/workers) ─ QThread 桥接
数据层               ─ data/store.json + config/app_config.json
```

## 核心规则

1. **Store 是唯一数据真相源**：所有数据读写通过 `app/core/store.py` 的 `Store` 类，线程安全（RLock）
2. **原子写**：保存时先写 `.tmp` 再 `os.replace`
3. **OCR 在后台线程**：`OcrWorker` 继承 `BaseWorker`（QThread），通过信号回主线程
4. **file_id 稳定**：`sha1(abs_path + modified_iso)[:16]`，路径不变则 ID 可复现
5. **增量合并**：重扫时保留已有关联和金额，不覆盖

## 协作规则（Codex × Claude Code）

- **读任务**：先读 `.ai/brief.md` 和 `.ai/plan.md`
- **做方案**：把方案写入 `.ai/plan.md`
- **改代码**：只改本次任务相关的文件，不要顺手重构无关代码
- **验证**：每次修改后运行 `scripts/check.sh`（`bash scripts/check.sh`）
  - 失败则修复后重跑，最多 3 轮
  - 3 轮仍失败则说明卡点，请 Claude Code 介入
- **提交**：完成并验证通过后，说明改了什么、为什么这样改
- **不要做的事**：
  - 不要修改 `data/store.json`（用户运行数据）
  - 不要修改 `config/app_config.json`（用户偏好）
  - 不要新增依赖（除非任务明确要求）
  - 不要改 UI 主题/颜色（保持 Elegant Light 一致性）

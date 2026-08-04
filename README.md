# 发票与支付记录核对辅助系统

基于 Python + PySide6 + PaddleOCR 的桌面工具，辅助完成发票（PDF）与支付记录（截图）的 OCR 金额识别、关联核对与汇总计算，提高报销处理效率。

创造灵感：本人因出差频繁，发票与支付记录经常堆积如山，核对工作耗时费力。为此，我开发了一个自动化辅助工具，让繁琐的核对变得轻松高效。

## 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [环境配置](#环境配置)
- [使用指南](#使用指南)
- [架构设计](#架构设计)
- [目录结构](#目录结构)
- [常见问题](#常见问题)

## 功能特性

### 三大核心模式

| 模式         | 功能                                    |
| ---------- | ------------------------------------- |
| **数据总览**   | 指标卡展示发票数、支付记录数、已关联数、已确认金额合计           |
| **比对关联模式** | 左右双栏文件列表 + 双预览区，手动关联 / 自动比对 / 重命名关联文件 |
| **计算金额模式** | OCR 识别金额（支持图片与 PDF），人工校对，汇总计算         |

### 亮点功能

- **双类型 OCR**：既支持支付截图（JPG/PNG），也支持发票 PDF（自动渲染后识别合计金额），一键切换
- **自动比对关联**：基于金额自动匹配发票与支付记录，支持两种模式自由切换：
  - *审阅模式*（默认）：逐对展示匹配结果，双预览同步，人工确认每一对
  - *一键关联模式*：批量关联所有金额匹配项，自动标记区分于手动关联
- **关联文件重命名**：关联后可将发票与支付记录重命名为统一名称，便于从文件名辨识关联关系
- **金额筛选**：按金额范围过滤文件列表，支持批量全选/取消
- **实时预览**：PDF 翻页/缩放、图片自适应显示，双栏同步
- **数据持久化**：所有关联、金额、确认态原子写入本地 JSON文件
- **数据安全性**：所有数据在本地存储，不上传至服务器，确保隐私安全

## 技术栈

| 层      | 技术                                 |
| ------ | ---------------------------------- |
| UI 框架  | PySide6 6.8.2 + MonkeyQt 0.1.5     |
| PDF 渲染 | PyMuPDF / fitz 1.24.14             |
| OCR    | PaddleOCR 3.7（PP-OCRv5，本地 CPU 推理）  |
| 持久化    | JSON 文件（原子写：`.tmp` → `os.replace`） |
| 后台线程   | QThread（OCR 批量识别）                  |
| 语言     | Python 3.10+（推荐 3.12）              |

## 环境配置

```bash
# 1. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# 2. 安装 PaddlePaddle
python -m pip install paddlepaddle==3.0.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/

# 3. 安装其余依赖
pip install -r requirements.txt
```

## 使用指南

```bash
python main.py
```

### 推荐工作流程

**第一步 — 准备数据**

1. 进入「比对关联模式」
2. 分别选择**发票文件夹**（PDF）和**支付记录文件夹**（图片）
3. 系统自动扫描并显示文件列表

**第二步 — OCR 金额识别**

1. 切换到「计算金额模式」
2. 选择识别类型：**发票** 或 **图片**
3. 点击「开始OCR识别」，等待进度条完成
4. 核对识别金额，必要时手动修正（直接在编辑金额列输入）
5. 勾选「确认」复选框，点击「计算总额」查看汇总
6. 切换类型标签可分别处理发票和支付记录

**第三步 — 建立关联**

1. 回到「比对关联模式」
2. **自动比对**：
   - 点击「自动比对」→ 系统查找金额匹配的未关联对
   - *审阅开启*（默认）：逐对确认，双预览同步显示，点击「关联选中项」推进
   - *审阅关闭*：一键自动关联所有匹配对
3. **手动关联**：从左右列表分别选中发票与支付记录，点击「关联选中项」
4. **重命名关联**：选中已关联对，点击「重命名关联」，输入统一名称

## 架构设计

三层分层，依赖严格单向（UI → 业务 → 数据）：

```
UI 层 (app/ui)           MkWindow + MkMenu + QStackedWidget
                         ├── pages/    home_page / compare_page / amount_page
                         └── widgets/  file_list_panel / preview_view / toggle_switch …

业务层 (app/core)        FileScanner / PdfRenderer / OcrEngine / AmountParser / Store
                         纯 Python，不依赖 Qt，可脱离 UI 单测

workers (app/workers)    QThread 桥接：OcrWorker（OCR 在后台线程，进度信号回主线程）

数据层                   data/store.json（原子写 + 增量合并）
                         config/app_config.json（UI 偏好）
                         cache/  logs/
```

关键设计决策：

- **Store 是唯一数据真相源**：所有 UI 操作通过 Store 读写，线程安全（`RLock`），支持 QThread 后台调用
- **增量合并**：`file_id = sha1(abs_path + modified_iso)[:16]`，路径稳定的文件重扫时保留已有关联与金额，不会重复创建
- **原子写**：`write .tmp → os.replace()`，崩溃不损坏数据

## 目录结构

```
├── main.py                      # 程序入口
├── requirements.txt
├── config\app_config.json       # UI 偏好（主题 / 窗口尺寸 / 最近菜单）
├── data\store.json              # 主数据（关联 + 金额，原子写）
├── cache\  logs\
└── app\
    ├── app_entry.py             # QApplication 启动、主题、全局异常钩子
    ├── core\
    │   ├── models.py            # 数据模型（InvoiceFile / PaymentFile / AmountRecord / Association）
    │   ├── store.py             # JSON 持久化（原子写 + 增量合并 + 线程安全）
    │   ├── file_scanner.py      # 文件夹扫描与格式过滤
    │   ├── pdf_renderer.py      # fitz 渲染 PDF → QImage / QPixmap
    │   ├── ocr_engine.py        # PaddleOCR 懒加载单例封装
    │   ├── amount_parser.py     # 金额正则提取与置信度加权
    │   └── app_config.py        # 偏好配置读写
    ├── workers\
    │   ├── base_worker.py       # QThread 基类（progress / finished_ok / failed 信号）
    │   └── ocr_worker.py        # 批量 OCR 线程（支持 image + pdf）
    └── ui\
        ├── main_window.py       # 主窗口 + 侧边栏导航
        ├── theme.py             # 主题与字体应用
        ├── widgets\
        │   ├── file_list_panel.py      # 文件列表面板（树形展开关联对象）
        │   ├── preview_view.py         # 预览视图（PDF 翻页 / 图片缩放）
        │   ├── folder_picker.py        # 文件夹选择条
        │   ├── amount_edit_cell.py     # 金额编辑单元格
        │   ├── confirm_checkbox.py     # 确认复选框（自绘矢量对号）
        │   ├── status_badge.py         # 关联状态徽标（未关联 / 手动关联 / 自动关联）
        │   ├── toggle_switch.py        # 滑动开关（是否审阅）
        │   └── table_utils.py          # 表格平滑滚动增强
        └── pages\
            ├── home_page.py            # 数据总览页
            ├── compare_page.py         # 比对关联页
            └── amount_page.py          # 计算金额页
```

## 常见问题

**启动相关**

> **首次 OCR 卡住？** PaddleOCR 首次使用需下载 PP-OCRv5 模型，状态栏会提示「正在加载 OCR 模型」。模型缓存在本地，后续启动不再下载。
>
> **模型缓存在哪里？** 程序自动设置 `PADDLE_PDX_CACHE_HOME` 到项目目录 `cache/paddlex/`。因 PaddlePaddle C++ 推理引擎不支持含非 ASCII 字符的路径，若项目路径含中文则回退到所在盘根目录。
>
> **PDF 预览空白或报错？** 确认 PyMuPDF 已安装（`python -c "import fitz; print(fitz.__doc__)"`）。加密或损坏的 PDF 无法渲染，错误记录在 `logs/app.log`。
>
> **numpy 版本冲突？** paddleocr 要求 `numpy<2.4`。安装时会自动回退；若手动升级导致报错，执行 `pip install "numpy<2.4"`。

**数据相关**

> **重启后数据还在吗？** 在。全部关联与金额以原子写存入 `data/store.json`，崩溃不损坏。文件被移动或删除时仅标记 `missing`，不删除记录。
>
> **切换发票/图片类型后金额丢失？** 不会。Invoice 与 Payment 各自独立存储，切换类型只是切换显示，不影响已持久化的数据。

**功能相关**

> **自动比对没找到匹配？** 确认发票与支付记录两边都已完成 OCR 识别并确认金额。仅匹配金额相等且尚未关联的对。
>
> **重命名关联后下次扫描会丢失关联吗？** 不会。重命名操作同步更新了 Store 内的 file\_id 及所有交叉引用，重扫后关联关系完整保留。


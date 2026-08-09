#!/usr/bin/env bash
# Recify 统一验证脚本
# 用法: bash scripts/check.sh
# 退出码 0 = 通过，非 0 = 失败

set -e
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== Recify 项目验证 ==="
echo ""

# ── 1. Python 语法检查 ──
echo "[1/3] Python 语法检查..."
FAILED=0
while IFS= read -r f; do
    python -m py_compile "$f" || FAILED=1
done < <(find app main.py -name "*.py" -not -path "*__pycache__*" -not -path "*.pyc")
if [ "$FAILED" -ne 0 ]; then
    echo "❌ 语法检查失败"
    exit 1
fi
echo "✅ 语法检查通过"

# ── 2. 核心模块导入测试 ──
echo ""
echo "[2/3] 核心模块导入测试..."
python -c "
from app.core.models import InvoiceFile, PaymentFile, AmountRecord, Association, now_iso, generate_file_id
from app.core.store import Store
from app.core.amount_parser import AmountParser, AmountCandidate
from app.core.file_scanner import FileScanner
from app.core.pdf_renderer import PdfRenderer
from app.core.ocr_engine import OcrEngine, OcrLine
from app.core.app_config import AppConfig
from app.workers.ocr_worker import OcrWorker
print('  core + workers imports OK')
"
echo "✅ 导入测试通过"

# ── 3. UI 模块导入测试 ──
echo ""
echo "[3/3] UI 模块导入测试..."
python -c "
from app.ui.widgets.file_list_panel import FileListPanel
from app.ui.widgets.toggle_switch import ToggleSwitch
from app.ui.widgets.status_badge import StatusBadge
from app.ui.widgets.amount_edit_cell import AmountEditCell
from app.ui.widgets.confirm_checkbox import ConfirmCheckBox
from app.ui.widgets.folder_picker import FolderPicker
from app.ui.widgets.preview_view import PreviewView
from app.ui.pages.amount_page import AmountPage
from app.ui.pages.compare_page import ComparePage
from app.ui.pages.home_page import HomePage
from app.ui.main_window import MainWindow
from app.ui import theme
print('  UI imports OK')
"
echo "✅ UI 导入测试通过"

echo ""
echo "=== 全部验证通过 ==="

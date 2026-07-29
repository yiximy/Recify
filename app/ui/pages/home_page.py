# -*- coding: utf-8 -*-
"""数据总览页：指标卡展示 + 快速指引"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from monkeyqt import MkCard


class HomePage(QWidget):
    """数据总览页面，展示发票/支付/关联/金额统计指标。"""

    def __init__(self, store=None, parent=None):
        super().__init__(parent)
        self.store = store
        self._value_labels: dict = {}
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # ── 页面标题 ──
        title = QLabel("数据总览")
        title_font = QFont("Microsoft YaHei UI", 18, QFont.Weight.DemiBold)
        title.setFont(title_font)
        title.setStyleSheet("color: #303133;")
        layout.addWidget(title)

        # ── 指标卡行 ──
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(16)

        self.card_invoices = self._make_metric_card("发票总数", "0", "份")
        metrics_row.addWidget(self.card_invoices)

        self.card_payments = self._make_metric_card("支付记录总数", "0", "份")
        metrics_row.addWidget(self.card_payments)

        self.card_linked = self._make_metric_card("已关联支付", "0", "份")
        metrics_row.addWidget(self.card_linked)

        self.card_amount = self._make_metric_card("已确认金额合计", "¥0.00", "元")
        metrics_row.addWidget(self.card_amount)

        layout.addLayout(metrics_row)

        # ── 快速指引卡 ──
        guide_card = MkCard(title="快速指引")
        guide_card.content_layout.addWidget(self._make_guide_label(
            "① 选择文件夹",
            "在「比对关联模式」页分别选择发票文件夹（PDF）与支付记录文件夹（图片）。"
        ))
        guide_card.content_layout.addWidget(self._make_guide_label(
            "② OCR 计算金额",
            "切到「计算金额模式」，选择类型（发票/图片）和文件夹后点击「开始OCR识别」，"
            "核对/修正金额并勾选确认，最后点击「计算总额」汇总。"
        ))
        guide_card.content_layout.addWidget(self._make_guide_label(
            "③ 建立关联",
            "回到「比对关联模式」，点击「自动比对」基于金额自动匹配，"
            "开启「是否审阅」逐对确认，或关闭后一键自动关联。也可手动选中关联。"
        ))
        layout.addWidget(guide_card)

        layout.addStretch()

    def _make_metric_card(self, title: str, value: str, unit: str) -> MkCard:
        """构建单个指标卡。"""
        card = MkCard(title=title)

        # 大号数值
        value_label = QLabel(value)
        value_font = QFont("Microsoft YaHei UI", 32, QFont.Weight.Bold)
        value_label.setFont(value_font)
        value_label.setStyleSheet("color: #409eff;")
        value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        card.content_layout.addWidget(value_label)

        # 单位说明
        unit_label = QLabel(unit)
        unit_label.setStyleSheet("color: #909399; font-size: 12px;")
        card.content_layout.addWidget(unit_label)

        self._value_labels[title] = value_label
        return card

    def _make_guide_label(self, step: str, desc: str) -> QLabel:
        """构建指引条目。"""
        label = QLabel(f"<b style='color:#303133;'>{step}</b>　"
                       f"<span style='color:#606266;'>{desc}</span>")
        label.setWordWrap(True)
        label.setStyleSheet("font-size: 13px;")
        return label

    def _connect_signals(self):
        """连接 Store 变更信号。"""
        if self.store:
            self.store.on_changed(self._on_store_changed)

    # ── 数据刷新 ────────────────────────────────────────────

    def _refresh_metrics(self):
        """从 Store 刷新指标卡数据。"""
        if not self.store:
            return
        summary = self.store.get_summary()
        self._value_labels["发票总数"].setText(str(summary.get("invoice_count", 0)))
        self._value_labels["支付记录总数"].setText(str(summary.get("payment_count", 0)))
        self._value_labels["已关联支付"].setText(str(summary.get("linked_payments", 0)))
        total = summary.get("total_amount", 0)
        self._value_labels["已确认金额合计"].setText(f"¥{total:.2f}")

    def _on_store_changed(self):
        """Store 变更时刷新指标。"""
        self._refresh_metrics()

    def on_page_activated(self):
        """页面激活时刷新数据。"""
        self._refresh_metrics()

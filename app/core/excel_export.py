# -*- coding: utf-8 -*-
"""关联信息导出为最小 xlsx（Qt-free，仅用标准库）。

不引入 ``openpyxl`` / ``xlsxwriter``：直接按 OOXML 约定用 ``zipfile`` + XML
拼出最小可用工作簿（``[Content_Types].xml`` / ``_rels/.rels`` /
``xl/workbook.xml`` / ``xl/_rels/workbook.xml.rels`` /
``xl/worksheets/sheet1.xml``）。

单元格取值取舍：金额与日期都写成**格式化字符串**（``inlineStr``），
金额固定 2 位小数（``f"{amount:.2f}"``）；这样无需在表格里再处理数字格式，
且便于文本校验。全部文本都做 XML 转义，文件名含 ``& < > " '`` 也不会破坏文件。
"""
from __future__ import annotations

import zipfile

# 表头（列顺序即导出列顺序）
HEADERS = [
    "发票文件名", "发票金额", "发票日期",
    "支付记录文件名", "支付金额", "支付日期",
    "所属组合", "关联方式",
]

# 日期来源的中文后缀标签
_DATE_SOURCE_LABELS = {"ocr": "票面", "manual": "手动", "file": "文件"}


# ── 数据构建（业务逻辑，UI 不得重复实现）──────────────────────

def _amount_text(file) -> str:
    """金额列文本：``final_amount`` 保留 2 位，无金额返回空串。"""
    amount = getattr(file, "amount", None)
    value = amount.final_amount if amount is not None else None
    return "" if value is None else f"{value:.2f}"


def _date_text(store, file) -> str:
    """日期列文本：ISO 日期 + 来源后缀（票面/手动/文件）。"""
    date_iso, source = store.get_document_date(file)
    if not date_iso:
        return ""
    label = _DATE_SOURCE_LABELS.get(source, "")
    return f"{date_iso}（{label}）" if label else date_iso


def _combo_name_map(store) -> dict[str, str]:
    """file_id -> 所属组合名（发票/支付两类合并，先到先得）。"""
    names: dict[str, str] = {}
    for kind in ("invoice", "payment"):
        for combo in store.get_combos(kind):
            for file_id in combo.get("file_ids", []):
                names.setdefault(file_id, combo.get("name", ""))
    return names


def _combo_text(combo_names: dict[str, str], invoice_id: str,
                payment_id: str) -> str:
    """组合列：两侧都在组合里时用 ``↔`` 连接，否则取有值的一侧。"""
    inv_name = combo_names.get(invoice_id, "")
    pay_name = combo_names.get(payment_id, "")
    if inv_name and pay_name:
        return f"{inv_name} ↔ {pay_name}"
    return inv_name or pay_name


def build_association_rows(store) -> list[list[str]]:
    """生成导出数据：首行表头 + 每条**有效**关联一行。

    有效 = 关联双方的记录都存在且 ``missing == False``；未关联的文件不出现，
    失效关联被跳过（不做额外汇总页）。关联方式取自冗余关联表的 ``auto_linked``。
    """
    rows: list[list[str]] = [list(HEADERS)]
    invoices = {f.file_id: f for f in store.get_invoices()}
    payments = {f.file_id: f for f in store.get_payments()}
    combo_names = _combo_name_map(store)

    seen: set[tuple[str, str]] = set()
    for assoc in store.get_associations():
        invoice_id = assoc.get("invoice_id", "")
        payment_id = assoc.get("payment_id", "")
        if (invoice_id, payment_id) in seen:
            continue
        seen.add((invoice_id, payment_id))
        invoice = invoices.get(invoice_id)
        payment = payments.get(payment_id)
        if invoice is None or payment is None:
            continue
        rows.append([
            invoice.file_name, _amount_text(invoice), _date_text(store, invoice),
            payment.file_name, _amount_text(payment), _date_text(store, payment),
            _combo_text(combo_names, invoice_id, payment_id),
            "自动" if assoc.get("auto_linked") else "手动",
        ])
    return rows


# ── xlsx 写入 ────────────────────────────────────────────────

def _escape(text: str) -> str:
    """XML 文本/属性转义；``&`` 必须最先替换。"""
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&apos;"))


def _col_letter(index: int) -> str:
    """0 基列号 -> Excel 列字母（0->A, 26->AA）。"""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _cell(ref: str, value) -> str:
    """构造一个 inlineStr 单元格（空值写空字符串）。"""
    text = "" if value is None else str(value)
    return (f'<c r="{ref}" t="inlineStr"><is>'
            f'<t xml:space="preserve">{_escape(text)}</t></is></c>')


def _sheet_xml(rows: list[list]) -> str:
    body = []
    for row_index, values in enumerate(rows, start=1):
        cells = "".join(
            _cell(f"{_col_letter(i)}{row_index}", value)
            for i, value in enumerate(values)
        )
        body.append(f'<row r="{row_index}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(body)}</sheetData></worksheet>'
    )


def write_xlsx(path: str, rows: list[list], sheet_name: str = "关联信息") -> None:
    """把 ``rows`` 写成最小 xlsx 文件（单工作表，全部 inlineStr）。"""
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{_escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", _sheet_xml(rows))


# ── 自检：生成临时文件 → 标准库读回校验 ─────────────────────

if __name__ == "__main__":
    import os
    import tempfile
    import xml.etree.ElementTree as ET

    demo = [
        list(HEADERS),
        ["发票&测试<>.pdf", "100.00", "2026-03-05（票面）",
         "支付'记录'.png", "100.00", "2026-03-05（文件）", "组合A", "手动"],
    ]
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "self_check.xlsx")
        write_xlsx(out, demo)
        with zipfile.ZipFile(out) as archive:
            required = {
                "[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
                "xl/_rels/workbook.xml.rels", "xl/worksheets/sheet1.xml",
            }
            assert required <= set(archive.namelist()), "缺少必要成员"
            xml_text = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        root = ET.fromstring(xml_text)  # 特殊字符未转义会在此抛错
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        assert len(root.findall(".//m:row", ns)) == len(demo), "行数不符"
        texts = [node.text or "" for node in root.iter(
            "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")]
        assert texts[0] == "发票文件名" and "发票&测试<>.pdf" in texts, texts
        assert "100.00" in texts, texts
    print("excel_export self-check OK")

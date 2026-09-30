# -*- coding: utf-8 -*-
"""关联明细 + 费用报销表导出为 xlsx（Qt-free，仅标准库 zipfile + XML）。

不引入 ``openpyxl`` / ``xlsxwriter``：直接按 OOXML 约定用 ``zipfile`` + XML
拼出工作簿（``[Content_Types].xml`` / ``_rels/.rels`` / ``xl/workbook.xml`` /
``xl/_rels/workbook.xml.rels`` / ``xl/styles.xml`` / ``xl/worksheets/sheetN.xml``）。

写入器支持多工作表与具名样式（见 ``STYLE_INDEX``）：金额等数字写成**真数值**
（``<v>``），合计行写 ``SUM`` 公式（同时带缓存值），列宽/行高/合并对齐模板
「费用报销表」。文本仍做 XML 转义，文件名含 ``& < > " '`` 也不会破坏文件。

旧接口 ``build_association_rows`` / ``write_xlsx`` 保持可用；导出用的「关联明细」
为 9 列（见 ``DETAIL_HEADERS``），先按标签分组、组内按日期升序排序，同一关联组内
取值相同的列再纵向合并单元格。
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from typing import Any, Optional

# 旧接口 build_association_rows 的表头（8 列，含「关联方式」）
HEADERS = [
    "发票文件名", "发票金额", "发票日期",
    "支付记录文件名", "支付金额", "支付日期",
    "所属组合", "关联方式",
]

# 关联明细工作表表头（9 列，无「关联方式」；列顺序即导出列顺序）
DETAIL_HEADERS = [
    "发票文件名", "发票金额", "发票日期",
    "支付记录文件名", "支付金额", "支付日期",
    "所属组合", "发票标签", "支付标签",
]

# 费用报销表布局（对齐参考模板，列宽容差 0.1）
SUMMARY_HEADERS = ["序号", "日期", "摘要", "票据张数", "金额", "备注"]
SUMMARY_COL_WIDTHS = (9, 20.48, 42.89, 11.56, 17.11, 25.18)
DETAIL_COL_WIDTHS = (30, 12, 20, 30, 12, 20, 24, 22, 22)

# 具名样式 -> cellXfs 索引（与 _STYLES_XML 中顺序一致）
STYLE_INDEX = {
    "default": 0,
    "title": 1,
    "subtitle": 2,
    "header": 3,
    "center": 4,
    "text": 5,
    "number": 6,
    "total": 7,
}


# ── 写入器数据模型 ──────────────────────────────────────────

@dataclass
class Cell:
    """单元格：纯值 / 具名样式 / 公式（``formula`` 不含前导 '='）。"""

    value: Any = None
    style: Optional[str] = None
    formula: Optional[str] = None


@dataclass
class Sheet:
    """一个工作表：名称 + 行数据 + 合并区 + 列宽 + 行高。"""

    name: str
    rows: list
    merges: tuple = ()
    col_widths: tuple = ()
    row_heights: dict = field(default_factory=dict)


# ── 数据构建（业务逻辑，UI 不得重复实现）──────────────────────

def _amount_value(file) -> Optional[float]:
    """金额列数值：``final_amount``，无金额返回 None。"""
    amount = getattr(file, "amount", None)
    if amount is None:
        return None
    return amount.final_amount


def _amount_display(value: Optional[float]) -> str:
    """金额显示文本：保留 2 位；无金额返回空串（与 number 样式显示一致）。"""
    return "" if value is None else f"{value:.2f}"


def _amount_text(file) -> str:
    """金额列文本：``final_amount`` 保留 2 位，无金额返回空串。"""
    return _amount_display(_amount_value(file))


def _date_text(store, file) -> str:
    """日期列文本：仅 ``YYYY-MM-DD``（不含来源后缀）。"""
    date_iso, _source = store.get_document_date(file)
    return date_iso or ""


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


def _association_records(store):
    """逐条产出**有效**关联：``{'invoice', 'payment', 'combo', 'auto'}``。

    有效 = 关联双方的记录都存在且 ``missing == False``；未关联的文件不出现，
    失效关联被跳过。关联方式取自冗余关联表的 ``auto_linked``。
    """
    invoices = {f.file_id: f for f in store.get_invoices()}
    payments = {f.file_id: f for f in store.get_payments()}
    combo_names = _combo_name_map(store)

    seen: set = set()
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
        yield {
            "invoice": invoice,
            "payment": payment,
            "combo": _combo_text(combo_names, invoice_id, payment_id),
            "auto": bool(assoc.get("auto_linked")),
        }


def build_association_rows(store) -> list[list[str]]:
    """生成关联明细数据：首行表头 + 每条**有效**关联一行（全部文本）。"""
    rows: list[list[str]] = [list(HEADERS)]
    for rec in _association_records(store):
        rows.append([
            rec["invoice"].file_name,
            _amount_text(rec["invoice"]),
            _date_text(store, rec["invoice"]),
            rec["payment"].file_name,
            _amount_text(rec["payment"]),
            _date_text(store, rec["payment"]),
            rec["combo"],
            "自动" if rec["auto"] else "手动",
        ])
    return rows


def _combo_tags(store, kind: str) -> dict[str, list]:
    """file_id -> 所属组合（指定 kind）的标签并集（保序去重）。"""
    result: dict[str, list] = {}
    for combo in store.get_combos(kind):
        tags = combo.get("tags", []) or []
        for file_id in combo.get("file_ids", []):
            bucket = result.setdefault(file_id, [])
            for tag in tags:
                if tag not in bucket:
                    bucket.append(tag)
    return result


def _file_tags(file, combo_tags: dict[str, list]) -> list:
    """标签列取值：记录自身标签 + 所属组合标签（保序去重）。"""
    merged: list = []
    for tag in list(getattr(file, "tags", []) or []) + combo_tags.get(
            file.file_id, []):
        if tag and tag not in merged:
            merged.append(tag)
    return merged


def _association_groups(records: list, group_keys: Optional[list] = None) -> list:
    """按「相邻行共享支付或发票 file_id」划分关联组，返回记录下标闭区间列表。

    相邻两行只要支付记录 file_id 相同或发票 file_id 相同即属同一组，因此
    「1 支付 ↔ N 发票」「1 发票 ↔ N 支付」两种方向都能形成连续分组。
    ``group_keys`` 给出每行的主分组键时，仅同键相邻行才可归入同一组，
    避免标签分组边界被共享的支付/发票打通（不得跨标签组合并）。
    """
    groups: list = []
    start = 0
    for index in range(1, len(records)):
        previous = records[index - 1]
        current = records[index]
        same_group = (
            previous["payment"].file_id == current["payment"].file_id
            or previous["invoice"].file_id == current["invoice"].file_id
        )
        if group_keys is not None and group_keys[index] != group_keys[index - 1]:
            same_group = False
        if not same_group:
            groups.append((start, index - 1))
            start = index
    if records:
        groups.append((start, len(records) - 1))
    return groups


def _apply_group_merges(rows: list, display: list, groups: list) -> list:
    """组内同值且非空的列纵向合并：置空非左上角单元格，返回 mergeCell 引用。

    ``rows`` 第 0 行为表头，记录下标 i 对应 Excel 第 i+2 行；``display`` 为每行
    的显示文本（金额已格式化、日期已去后缀），据其判断组内取值是否完全相同。
    不同组之间绝不合并，单行组不产生合并。
    """
    merges: list = []
    for start, end in groups:
        if end <= start:
            continue
        for column in range(len(DETAIL_HEADERS)):
            values = [display[i][column] for i in range(start, end + 1)]
            head = values[0]
            if not head or any(value != head for value in values):
                continue
            letter = _col_letter(column)
            merges.append(f"{letter}{start + 2}:{letter}{end + 2}")
            for i in range(start + 1, end + 1):
                rows[i + 1][column] = Cell(None, rows[i + 1][column].style)
    return merges


def _detail_group_key(rec, invoice_combo_tags, payment_combo_tags, tag_rank,
                      unknown_rank, untagged_rank) -> tuple:
    """主分组键 ``(组序号, 组名)``：发票标签优先，其次支付标签，都无则「未标注」。

    文件可带多个标签，取 ``tag_rank`` 中序号最靠前（即传入标签顺序最靠前）的一个，
    与「费用报销表」的类别顺序对齐；未在传入顺序中的标签统一排在已选标签之后，
    「未标注」再居最后。
    """
    best: Optional[tuple] = None
    for holder, combo_tags in ((rec["invoice"], invoice_combo_tags),
                               (rec["payment"], payment_combo_tags)):
        for tag in _file_tags(holder, combo_tags):
            rank = tag_rank.get(tag, unknown_rank)
            if best is None or (rank, tag) < best:
                best = (rank, tag)
        if best is not None:
            break
    return best if best is not None else (untagged_rank, "")


def _detail_sort_key(store, rec, group_key) -> tuple:
    """关联明细排序键：组序号 → 组名 → 日期升序 → (支付文件名, 发票文件名)。

    日期取发票票面日期，缺失时回退支付日期；两者都缺的行排组内最后。
    文件名参与排序保证同日稳定、可复现。
    """
    date_iso = (_date_text(store, rec["invoice"])
                or _date_text(store, rec["payment"]))
    return (
        group_key[0],
        group_key[1],
        date_iso == "",
        date_iso,
        rec["payment"].file_name,
        rec["invoice"].file_name,
    )


def build_detail_sheet(store, tags=None) -> Sheet:
    """关联明细工作表：9 列（无「关联方式」）、日期无来源后缀、组内同值列合并。

    先按标签分组、组内按日期升序排序，再计算合并（合并依赖相邻性）：
    主分组键 = 发票标签（无则支付标签，都无则「未标注」固定最后）；``tags``
    为组间顺序（默认 ``store.get_all_tags()``），导出时传入对话框勾选顺序，
    与「费用报销表」保持一致；组内按日期升序（发票票面日期，缺失回退支付日期），
    同日按 ``(支付记录文件名, 发票文件名)`` 稳定排序。
    """
    tag_order = list(tags) if tags is not None else store.get_all_tags()
    tag_rank = {tag: index for index, tag in enumerate(tag_order)}
    unknown_rank = len(tag_order)
    untagged_rank = unknown_rank + 1

    invoice_combo_tags = _combo_tags(store, "invoice")
    payment_combo_tags = _combo_tags(store, "payment")

    pairs = [
        (_detail_group_key(rec, invoice_combo_tags, payment_combo_tags,
                           tag_rank, unknown_rank, untagged_rank), rec)
        for rec in _association_records(store)
    ]
    pairs.sort(key=lambda pair: _detail_sort_key(store, pair[1], pair[0]))
    group_keys = [key for key, _rec in pairs]
    records = [rec for _key, rec in pairs]

    rows: list = [[Cell(text, "header") for text in DETAIL_HEADERS]]
    display: list = []
    for rec in records:
        invoice = rec["invoice"]
        payment = rec["payment"]
        invoice_amount = _amount_value(invoice)
        payment_amount = _amount_value(payment)
        invoice_date = _date_text(store, invoice)
        payment_date = _date_text(store, payment)
        invoice_tags = "、".join(_file_tags(invoice, invoice_combo_tags))
        payment_tags = "、".join(_file_tags(payment, payment_combo_tags))
        rows.append([
            Cell(invoice.file_name, "text"),
            Cell(invoice_amount, "number"),
            Cell(invoice_date, "center"),
            Cell(payment.file_name, "text"),
            Cell(payment_amount, "number"),
            Cell(payment_date, "center"),
            Cell(rec["combo"], "text"),
            Cell(invoice_tags, "text"),
            Cell(payment_tags, "text"),
        ])
        display.append([
            invoice.file_name,
            _amount_display(invoice_amount),
            invoice_date,
            payment.file_name,
            _amount_display(payment_amount),
            payment_date,
            rec["combo"],
            invoice_tags,
            payment_tags,
        ])

    merges = _apply_group_merges(
        rows, display, _association_groups(records, group_keys))
    return Sheet(
        name="关联明细",
        rows=rows,
        merges=tuple(merges),
        col_widths=DETAIL_COL_WIDTHS,
        row_heights={1: 22},
    )


def build_summary_sheet(store, tags, include_untagged: bool,
                        unit_text: str) -> Sheet:
    """费用报销表工作表：标题 / 报销单位+期间 / 表头 / 数据行 / 合计行。

    ``tags`` 为要包含的标签名列表（顺序即行顺序）；``include_untagged`` 为真时
    追加「未分类」行。金额列写入真数值，合计行 D/E 写 SUM 公式（带缓存值）。
    """
    stats = store.get_tag_stats()
    by_tag = {c["tag"]: c for c in stats["tags"]}
    selected = [by_tag[t] for t in tags if t in by_tag]
    if include_untagged:
        selected.append(stats["untagged"])

    starts = [c["date_start"] for c in selected if c["date_start"]]
    ends = [c["date_end"] for c in selected if c["date_end"]]
    period = store.format_date_range(
        min(starts) if starts else "", max(ends) if ends else ""
    )

    rows: list = []
    rows.append([Cell("费用报销表", "title")] + [Cell(None, "title")] * 5)
    subtitle = f"报销单位：{unit_text or ''}          费用报销期间：{period}"
    rows.append([Cell(subtitle, "subtitle")] + [Cell(None, "subtitle")] * 5)
    rows.append([Cell(text, "header") for text in SUMMARY_HEADERS])

    first_data = 4
    for index, cat in enumerate(selected):
        rows.append([
            Cell(index + 1, "center"),
            Cell(cat["date_text"], "center"),
            Cell(cat["tag"], "text"),
            Cell(cat["count"], "center"),
            Cell(cat["amount"], "number"),
            Cell(cat["note"], "text"),
        ])

    total_row = first_data + len(selected)
    if selected:
        last_data = total_row - 1
        d_cell = Cell(
            formula=f"SUM(D{first_data}:D{last_data})",
            value=sum(c["count"] for c in selected),
            style="center",
        )
        e_cell = Cell(
            formula=f"SUM(E{first_data}:E{last_data})",
            value=round(sum(c["amount"] for c in selected), 2),
            style="number",
        )
    else:
        d_cell = Cell(0, "center")
        e_cell = Cell(0, "number")
    rows.append([
        Cell(None, "total"),
        Cell(None, "total"),
        Cell("合计", "total"),
        d_cell,
        e_cell,
        Cell(None, "total"),
    ])

    heights = {1: 36, 2: 25, 3: 25, total_row: 20}
    for offset in range(len(selected)):
        heights[first_data + offset] = 20

    return Sheet(
        name="费用报销表",
        rows=rows,
        merges=("A1:F1", "A2:F2"),
        col_widths=SUMMARY_COL_WIDTHS,
        row_heights=heights,
    )


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


def _num_text(value) -> str:
    """数字 -> XML 文本：整数原样、浮点用 repr 保精度（显示交给 number 格式）。"""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    return repr(float(value))


def _style_index(style) -> Optional[int]:
    if style is None:
        return None
    if isinstance(style, int):
        return style
    return STYLE_INDEX.get(style, 0)


def _cell_xml(ref: str, raw) -> str:
    """把纯值 / ``Cell`` 渲染为单元格 XML。"""
    cell = raw if isinstance(raw, Cell) else Cell(value=raw)
    style = _style_index(cell.style)
    s_attr = f' s="{style}"' if style is not None else ""

    if cell.formula:
        inner = f"<f>{_escape(cell.formula)}</f>"
        if cell.value is not None:
            inner += f"<v>{_num_text(cell.value)}</v>"
        return f'<c r="{ref}"{s_attr}>{inner}</c>'

    value = cell.value
    if value is None or (isinstance(value, str) and value == ""):
        return f'<c r="{ref}"{s_attr}/>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"{s_attr}><v>{_num_text(value)}</v></c>'
    return (f'<c r="{ref}"{s_attr} t="inlineStr"><is>'
            f'<t xml:space="preserve">{_escape(str(value))}</t></is></c>')


def _sheet_xml(sheet: Sheet) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
    ]
    if sheet.col_widths:
        cols = "".join(
            f'<col min="{i}" max="{i}" width="{_num_text(w)}" customWidth="1"/>'
            for i, w in enumerate(sheet.col_widths, start=1)
        )
        parts.append(f"<cols>{cols}</cols>")

    rows_xml = []
    for row_index, values in enumerate(sheet.rows, start=1):
        attrs = f' r="{row_index}"'
        height = sheet.row_heights.get(row_index)
        if height:
            attrs += f' ht="{_num_text(height)}" customHeight="1"'
        cells = "".join(
            _cell_xml(f"{_col_letter(i)}{row_index}", value)
            for i, value in enumerate(values)
        )
        rows_xml.append(f"<row{attrs}>{cells}</row>")
    parts.append(f'<sheetData>{"".join(rows_xml)}</sheetData>')

    if sheet.merges:
        merged = "".join(f'<mergeCell ref="{ref}"/>' for ref in sheet.merges)
        parts.append(f'<mergeCells count="{len(sheet.merges)}">{merged}</mergeCells>')

    parts.append("</worksheet>")
    return "".join(parts)


_STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<numFmts count="1"><numFmt numFmtId="176" formatCode="#,##0.00"/></numFmts>'
    '<fonts count="3">'
    '<font><sz val="12"/><color rgb="FF000000"/><name val="宋体"/><charset val="134"/></font>'
    '<font><sz val="20"/><color rgb="FF000000"/><name val="宋体"/><charset val="134"/></font>'
    '<font><sz val="11"/><color rgb="FF000000"/><name val="宋体"/><charset val="134"/></font>'
    '</fonts>'
    '<fills count="2">'
    '<fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '</fills>'
    '<borders count="2">'
    '<border><left/><right/><top/><bottom/><diagonal/></border>'
    '<border>'
    '<left style="thin"><color auto="1"/></left>'
    '<right style="thin"><color auto="1"/></right>'
    '<top style="thin"><color auto="1"/></top>'
    '<bottom style="thin"><color auto="1"/></bottom>'
    '<diagonal/></border>'
    '</borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="8">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>'
    '<xf numFmtId="176" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
    '</cellXfs>'
    '</styleSheet>'
)

_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    '</Relationships>'
)


def _content_types(sheet_count: int) -> str:
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f'{overrides}'
        '</Types>'
    )


def _workbook_xml(sheets: list) -> str:
    entries = "".join(
        f'<sheet name="{_escape(sheet.name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, sheet in enumerate(sheets, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{entries}</sheets>'
        '</workbook>'
    )


def _workbook_rels(sheet_count: int) -> str:
    rels = "".join(
        f'<Relationship Id="rId{i}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, sheet_count + 1)
    )
    styles = (
        f'<Relationship Id="rId{sheet_count + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{rels}{styles}'
        '</Relationships>'
    )


def write_report(path: str, sheets: list) -> None:
    """把多个 ``Sheet`` 写成一个多工作表 xlsx（具名样式 + 真数值 + SUM）。"""
    sheet_list = list(sheets)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types(len(sheet_list)))
        archive.writestr("_rels/.rels", _ROOT_RELS)
        archive.writestr("xl/workbook.xml", _workbook_xml(sheet_list))
        archive.writestr("xl/_rels/workbook.xml.rels",
                         _workbook_rels(len(sheet_list)))
        archive.writestr("xl/styles.xml", _STYLES_XML)
        for i, sheet in enumerate(sheet_list, start=1):
            archive.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(sheet))


def write_xlsx(path: str, rows: list, sheet_name: str = "关联信息") -> None:
    """兼容旧接口：单工作表写出 ``rows``（纯值，数字自动写真数值）。"""
    write_report(path, [Sheet(name=sheet_name, rows=rows)])


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
                "xl/_rels/workbook.xml.rels", "xl/styles.xml",
                "xl/worksheets/sheet1.xml",
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

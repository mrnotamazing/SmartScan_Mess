"""A small .xlsx writer (standard library only) with native Excel charts.

Enough for the live mess logs: several sheets of text/number cells, a bold
frozen header row, column widths, and clustered-column or line charts that
reference the sheet's cells (so they stay correct if someone edits the data).
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

Cell = str | int | float | None


@dataclass
class Chart:
    title: str
    kind: str  # "bar" (clustered columns) or "line"
    categories_col: int  # 0-based column holding the x labels
    series_cols: list[int]  # 0-based columns, one series each (header row = series name)
    colors: list[str]  # hex like "2A78D6", one per series
    anchor: tuple[int, int, int, int]  # from_col, from_row, to_col, to_row (0-based)
    y_title: str = ""


@dataclass
class Sheet:
    name: str  # max 31 characters, no []:*?/\
    header: list[str]
    rows: list[list[Cell]]
    widths: list[float] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref: str, v: Cell, style: int = 0) -> str:
    st = f' s="{style}"' if style else ""
    if v is None or v == "":
        return f'<c r="{ref}"{st}/>'
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"{st}><v>{v}</v></c>'
    return f'<c r="{ref}" t="inlineStr"{st}><is><t xml:space="preserve">{escape(str(v))}</t></is></c>'


def _sheet_xml(sh: Sheet, has_drawing: bool) -> str:
    cols = ""
    if sh.widths:
        cols = "<cols>" + "".join(
            f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(sh.widths)
        ) + "</cols>"
    rows = ['<row r="1">' + "".join(_cell(f"{_col(c)}1", h, 1) for c, h in enumerate(sh.header)) + "</row>"]
    for r, row in enumerate(sh.rows, start=2):
        rows.append(f'<row r="{r}">' + "".join(_cell(f"{_col(c)}{r}", v) for c, v in enumerate(row)) + "</row>")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        f"{cols}<sheetData>{''.join(rows)}</sheetData>"
        '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
        + ('<drawing r:id="rId1"/>' if has_drawing else "")
        + "</worksheet>"
    )


def _chart_xml(sh: Sheet, ch: Chart, n_rows: int) -> str:
    q = "'" + sh.name.replace("'", "''") + "'"
    last = n_rows + 1
    cats = [row[ch.categories_col] if ch.categories_col < len(row) else "" for row in sh.rows]
    cat_cache = f'<c:strCache><c:ptCount val="{len(cats)}"/>' + "".join(
        f'<c:pt idx="{i}"><c:v>{escape(str(c))}</c:v></c:pt>' for i, c in enumerate(cats)
    ) + "</c:strCache>"
    sers = []
    for k, (col, color) in enumerate(zip(ch.series_cols, ch.colors)):
        L = _col(col)
        vals = [row[col] if col < len(row) else None for row in sh.rows]
        num_cache = f'<c:numCache><c:formatCode>General</c:formatCode><c:ptCount val="{len(vals)}"/>' + "".join(
            f'<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>' for i, v in enumerate(vals) if isinstance(v, (int, float))
        ) + "</c:numCache>"
        if ch.kind == "line":
            sp = f'<c:spPr><a:ln w="28575" cap="rnd"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill></a:ln></c:spPr>'
            extra = '<c:marker><c:symbol val="circle"/><c:size val="6"/>' \
                    f'<c:spPr><a:solidFill><a:srgbClr val="{color}"/></a:solidFill></c:spPr></c:marker>'
        else:
            sp = f'<c:spPr><a:solidFill><a:srgbClr val="{color}"/></a:solidFill></c:spPr>'
            extra = '<c:invertIfNegative val="0"/>'
        sers.append(
            f'<c:ser><c:idx val="{k}"/><c:order val="{k}"/>'
            f'<c:tx><c:strRef><c:f>{q}!${L}$1</c:f><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>{escape(sh.header[col])}</c:v></c:pt></c:strCache></c:strRef></c:tx>'
            f"{sp}{extra}"
            f'<c:cat><c:strRef><c:f>{q}!${_col(ch.categories_col)}$2:${_col(ch.categories_col)}${last}</c:f>{cat_cache}</c:strRef></c:cat>'
            f'<c:val><c:numRef><c:f>{q}!${L}$2:${L}${last}</c:f>{num_cache}</c:numRef></c:val>'
            + ('<c:smooth val="0"/>' if ch.kind == "line" else "")
            + "</c:ser>"
        )
    if ch.kind == "line":
        plot = f'<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>{"".join(sers)}' \
               '<c:marker val="1"/><c:axId val="5001"/><c:axId val="5002"/></c:lineChart>'
    else:
        plot = f'<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/><c:varyColors val="0"/>{"".join(sers)}' \
               '<c:gapWidth val="60"/><c:overlap val="-8"/><c:axId val="5001"/><c:axId val="5002"/></c:barChart>'
    grid = '<c:spPr><a:ln w="6350"><a:solidFill><a:srgbClr val="E3E2DE"/></a:solidFill></a:ln></c:spPr>'
    ytitle = (
        f'<c:title><c:tx><c:rich><a:bodyPr rot="-5400000" vert="horz"/><a:p><a:pPr><a:defRPr sz="900" b="0"/></a:pPr>'
        f'<a:r><a:rPr sz="900" b="0"/><a:t>{escape(ch.y_title)}</a:t></a:r></a:p></c:rich></c:tx><c:overlay val="0"/></c:title>'
        if ch.y_title else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<c:roundedCorners val="0"/><c:chart>'
        f'<c:title><c:tx><c:rich><a:bodyPr/><a:p><a:pPr><a:defRPr sz="1200" b="1"/></a:pPr><a:r><a:rPr sz="1200" b="1"/>'
        f"<a:t>{escape(ch.title)}</a:t></a:r></a:p></c:rich></c:tx><c:overlay val=\"0\"/></c:title>"
        '<c:autoTitleDeleted val="0"/><c:plotArea><c:layout/>'
        f"{plot}"
        '<c:catAx><c:axId val="5001"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/>'
        '<c:axPos val="b"/><c:numFmt formatCode="General" sourceLinked="0"/><c:majorTickMark val="none"/>'
        '<c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/><c:crossAx val="5002"/><c:crosses val="autoZero"/>'
        '<c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/><c:noMultiLvlLbl val="0"/></c:catAx>'
        f'<c:valAx><c:axId val="5002"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/>'
        f'<c:axPos val="l"/><c:majorGridlines>{grid}</c:majorGridlines>{ytitle}<c:numFmt formatCode="General" sourceLinked="0"/>'
        '<c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>'
        '<c:crossAx val="5001"/><c:crosses val="autoZero"/><c:crossBetween val="between"/></c:valAx>'
        "</c:plotArea>"
        '<c:legend><c:legendPos val="t"/><c:overlay val="0"/></c:legend><c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/>'
        "</c:chart></c:chartSpace>"
    )


def _drawing_xml(charts: list[Chart], first_rid: int = 1) -> str:
    anchors = []
    for k, ch in enumerate(charts):
        c0, r0, c1, r1 = ch.anchor
        anchors.append(
            "<xdr:twoCellAnchor>"
            f"<xdr:from><xdr:col>{c0}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{r0}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>"
            f"<xdr:to><xdr:col>{c1}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{r1}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>"
            f'<xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="{k + 2}" name="Chart {k + 1}"/>'
            "<xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr>"
            '<xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm>'
            '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">'
            '<c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
            f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId{first_rid + k}"/>'
            "</a:graphicData></a:graphic></xdr:graphicFrame><xdr:clientData/></xdr:twoCellAnchor>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">' + "".join(anchors) + "</xdr:wsDr>"
    )


STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFECEBE7"/><bgColor indexed="64"/></patternFill></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


def build_xlsx(sheets: list[Sheet]) -> bytes:
    buf = io.BytesIO()
    ct = [
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]
    wb_sheets, wb_rels = [], []
    chart_no = drawing_no = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, sh in enumerate(sheets, start=1):
            has_drawing = bool(sh.charts)
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(sh, has_drawing))
            ct.append(f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                      'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
            wb_sheets.append(f'<sheet name="{escape(sh.name)}" sheetId="{i}" r:id="rId{i}"/>')
            wb_rels.append(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>')
            if not has_drawing:
                continue
            drawing_no += 1
            z.writestr(f"xl/worksheets/_rels/sheet{i}.xml.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing{drawing_no}.xml"/>'
                       "</Relationships>")
            z.writestr(f"xl/drawings/drawing{drawing_no}.xml", _drawing_xml(sh.charts))
            ct.append(f'<Override PartName="/xl/drawings/drawing{drawing_no}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>')
            rels = []
            for k, ch in enumerate(sh.charts, start=1):
                chart_no += 1
                z.writestr(f"xl/charts/chart{chart_no}.xml", _chart_xml(sh, ch, len(sh.rows)))
                ct.append(f'<Override PartName="/xl/charts/chart{chart_no}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>')
                rels.append(f'<Relationship Id="rId{k}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/chart{chart_no}.xml"/>')
            z.writestr(f"xl/drawings/_rels/drawing{drawing_no}.xml.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(rels) + "</Relationships>")
        n = len(sheets)
        wb_rels.append(f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   f"<sheets>{''.join(wb_sheets)}</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(wb_rels) + "</Relationships>")
        z.writestr("xl/styles.xml", STYLES)
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' + "".join(ct) + "</Types>")
    return buf.getvalue()

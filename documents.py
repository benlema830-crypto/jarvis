"""Write Word (.docx) or Markdown documents from Markdown-style text JARVIS composes.

Files go to Documents\\JARVIS Documents and never overwrite an existing file. The .docx
writer is a small standard-library implementation supporting headings, paragraphs,
bullet and numbered lists, **bold**, *italic* and simple pipe tables, which covers
letters, invoices, proposals and briefs without adding a dependency.
"""
import datetime
import os
from pathlib import Path
import re
import zipfile
from xml.sax.saxutils import escape

FOLDER = Path.home() / "Documents" / "JARVIS Documents"
MAX_CHARS = 200_000

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="22"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="140" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr><w:rFonts w:ascii="Calibri Light" w:hAnsi="Calibri Light"/><w:sz w:val="52"/><w:color w:val="1F3A3D"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="320" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/><w:color w:val="1F3A3D"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/><w:color w:val="2E5E5A"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:sz w:val="23"/></w:rPr></w:style>
<w:style w:type="table" w:styleId="Grid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders>
<w:top w:val="single" w:sz="4" w:color="A0B4B2"/><w:left w:val="single" w:sz="4" w:color="A0B4B2"/><w:bottom w:val="single" w:sz="4" w:color="A0B4B2"/>
<w:right w:val="single" w:sz="4" w:color="A0B4B2"/><w:insideH w:val="single" w:sz="4" w:color="A0B4B2"/><w:insideV w:val="single" w:sz="4" w:color="A0B4B2"/>
</w:tblBorders><w:tblCellMar><w:left w:w="100" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
</w:styles>"""
_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""
_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""
_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""


def _runs(text: str) -> str:
    """**bold** and *italic* spans to Word runs."""
    out = []
    for part in re.split(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)", text):
        if not part:
            continue
        props = ""
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            part, props = part[2:-2], "<w:b/>"
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            part, props = part[1:-1], "<w:i/>"
        rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
        out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(part)}</w:t></w:r>')
    return "".join(out)


def _para(text: str, style: str = "", indent: int = 0) -> str:
    ppr = ""
    if style or indent:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + \
              (f'<w:ind w:left="{indent}" w:hanging="260"/>' if indent else "") + "</w:pPr>"
    return f"<w:p>{ppr}{_runs(text)}</w:p>"


def _table(rows: list[list[str]]) -> str:
    cells = lambda row, head: "".join(
        f'<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/></w:tcPr>{_para(f"**{c}**" if head and c else c)}</w:tc>' for c in row)
    body = "".join(f"<w:tr>{cells(row, i == 0)}</w:tr>" for i, row in enumerate(rows))
    return f'<w:tbl><w:tblPr><w:tblStyle w:val="Grid"/><w:tblW w:w="5000" w:type="pct"/></w:tblPr>{body}</w:tbl><w:p/>'


def to_docx_xml(title: str, markdown: str) -> str:
    parts, table, number = [_para(title, "Title")] if title else [], [], 0
    for raw in markdown.splitlines() + [""]:
        line = raw.rstrip()
        if line.strip().startswith("|") and line.strip().endswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                table.append(cells)
            continue
        if table:
            width = max(len(r) for r in table)
            parts.append(_table([r + [""] * (width - len(r)) for r in table]))
            table = []
        heading = re.match(r"^(#{1,3})\s+(.*)", line)
        bullet = re.match(r"^\s*[-*•]\s+(.*)", line)
        numbered = re.match(r"^\s*\d+[.)]\s+(.*)", line)
        if heading:
            parts.append(_para(heading.group(2), f"Heading{len(heading.group(1))}"))
        elif bullet:
            parts.append(_para("•\t" + bullet.group(1), indent=360))
        elif numbered:
            number += 1
            parts.append(_para(f"{number}.\t" + numbered.group(1), indent=360))
            continue
        elif line.strip():
            parts.append(_para(line.strip()))
        number = 0
    body = "".join(parts)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
            f'{body}<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1200" w:right="1200" '
            'w:bottom="1200" w:left="1200" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>')


def _destination(title: str, extension: str) -> Path:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title).strip(" .")[:80] or "Document"
    FOLDER.mkdir(parents=True, exist_ok=True)
    path, n = FOLDER / f"{name}{extension}", 2
    while path.exists():
        path, n = FOLDER / f"{name} ({n}){extension}", n + 1
    return path


def create(title: str, content: str, fmt: str = "docx", open_after: bool = True) -> str:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("The document needs content.")
    if len(content) > MAX_CHARS:
        raise ValueError("That document is too long to write in one go.")
    fmt = fmt.lower().strip(". ")
    if fmt not in ("docx", "md"):
        raise ValueError("Format must be docx or md.")
    path = _destination(title, "." + fmt)
    if fmt == "md":
        path.write_text((f"# {title}\n\n" if title else "") + content.strip() + "\n", encoding="utf-8")
    else:
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties '
                'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                f'<dc:title>{escape(title)}</dc:title><dc:creator>JARVIS</dc:creator>'
                f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created></cp:coreProperties>')
        with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", _TYPES)
            z.writestr("_rels/.rels", _RELS)
            z.writestr("docProps/core.xml", core)
            z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
            z.writestr("word/styles.xml", _STYLES)
            z.writestr("word/document.xml", to_docx_xml(title, content))
    if open_after:
        os.startfile(path)
    return str(path)

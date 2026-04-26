"""Minimal OOXML helpers for LT1 briefing evaluation and mock artifacts.

These utilities avoid a hard runtime dependency during evaluation while still
producing and inspecting valid-enough `.docx` packages for the benchmark.
"""

from __future__ import annotations

import base64
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape


_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}

_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl7VwAAAABJRU5ErkJggg=="
)


def write_placeholder_png(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_PNG_1X1)
    return target


def create_briefing_docx(
    path: str | Path,
    *,
    title: str,
    summary: str,
    interpretation: str,
    news_items: list[dict[str, str]],
    risks: list[str],
    sources: list[dict[str, str]],
    chart_path: str | Path | None = None,
) -> Path:
    """Create a small OOXML Word document with headings, links, and an image."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    chart_rel = ""
    if chart_path is not None:
        chart_file = Path(chart_path)
        if not chart_file.exists():
            write_placeholder_png(chart_file)
        chart_rel = _image_paragraph("rIdImage1", chart_file.name)

    hyperlink_rels = [
        _relationship_xml(index + 2, item["url"])
        for index, item in enumerate(news_items + sources)
    ]
    rels_xml = _document_rels_xml(
        image_name=chart_file.name if chart_rel and chart_path is not None else None,
        hyperlink_rels=hyperlink_rels,
    )

    news_blocks = []
    rel_index = 2
    for item in news_items:
        news_blocks.append(_hyperlink_paragraph(item["title"], f"rId{rel_index}", suffix=f" - {item.get('snippet', '')}".strip()))
        rel_index += 1

    source_blocks = []
    for item in sources:
        source_blocks.append(_hyperlink_paragraph(item["url"], f"rId{rel_index}"))
        rel_index += 1

    body_xml = "".join(
        [
            _title_paragraph(title),
            _heading_paragraph("Executive Summary"),
            _text_paragraph(summary),
            _heading_paragraph("Price & Indicators"),
            chart_rel,
            _text_paragraph(interpretation),
            _heading_paragraph("News & Catalysts"),
            *news_blocks,
            _heading_paragraph("Risks"),
            *(_text_paragraph(risk) for risk in risks),
            _heading_paragraph("Sources"),
            *source_blocks,
            _section_properties(),
        ]
    )

    document_xml = _document_xml(body_xml)

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types_xml(include_image=bool(chart_rel)))
        zf.writestr("_rels/.rels", _root_rels_xml())
        zf.writestr("docProps/core.xml", _core_xml(title))
        zf.writestr("docProps/app.xml", _app_xml())
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/styles.xml", _styles_xml())
        zf.writestr("word/_rels/document.xml.rels", rels_xml)
        if chart_rel and chart_path is not None:
            zf.write(chart_path, arcname=f"word/media/{Path(chart_path).name}")

    return target


def inspect_docx(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    with zipfile.ZipFile(target) as zf:
        document_root = ET.fromstring(zf.read("word/document.xml"))
        rels_root = ET.fromstring(zf.read("word/_rels/document.xml.rels"))

    rel_targets = {
        rel.attrib.get("Id", ""): rel.attrib.get("Target", "")
        for rel in rels_root.findall("rel:Relationship", _NS)
        if rel.attrib.get("Type", "").endswith("/hyperlink")
    }

    headings: list[str] = []
    for paragraph in document_root.findall(".//w:p", _NS):
        style = paragraph.find("./w:pPr/w:pStyle", _NS)
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", _NS)).strip()
        if style is not None and style.attrib.get(f"{{{_NS['w']}}}val", "").startswith("Heading"):
            headings.append(text)

    hyperlink_targets = []
    for hyperlink in document_root.findall(".//w:hyperlink", _NS):
        rel_id = hyperlink.attrib.get(f"{{{_NS['r']}}}id", "")
        target_url = rel_targets.get(rel_id)
        if target_url:
            hyperlink_targets.append(target_url)

    return {
        "headings": headings,
        "inline_images": len(document_root.findall(".//w:drawing", _NS)),
        "hyperlink_count": len(hyperlink_targets),
        "hyperlink_targets": hyperlink_targets,
    }


def _content_types_xml(*, include_image: bool) -> str:
    image_override = '<Default Extension="png" ContentType="image/png"/>' if include_image else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f"{image_override}"
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        "</Types>"
    )


def _root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>"
    )


def _document_rels_xml(*, image_name: str | None, hyperlink_rels: list[str]) -> str:
    image_rel = (
        '<Relationship Id="rIdImage1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        f'Target="media/{escape(image_name)}"/>'
        if image_name else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{image_rel}{''.join(hyperlink_rels)}"
        "</Relationships>"
    )


def _relationship_xml(index: int, target: str) -> str:
    return (
        f'<Relationship Id="rId{index}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
        f'Target="{escape(target)}" TargetMode="External"/>'
    )


def _core_xml(title: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{escape(title)}</dc:title>"
        "<dc:creator>Apex Agent</dc:creator>"
        "</cp:coreProperties>"
    )


def _app_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>Apex Agent</Application>"
        "</Properties>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:qFormat/></w:style>'
        '<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/></w:style>'
        "</w:styles>"
    )


def _document_xml(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
        'xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
        'xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:w10="urn:schemas-microsoft-com:office:word" '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
        'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" '
        'xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk" '
        'xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml" '
        'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
        'mc:Ignorable="w14 wp14">'
        f"<w:body>{body}</w:body>"
        "</w:document>"
    )


def _title_paragraph(text: str) -> str:
    return _text_paragraph(text)


def _heading_paragraph(text: str) -> str:
    return (
        "<w:p><w:pPr><w:pStyle w:val=\"Heading1\"/></w:pPr>"
        f"<w:r><w:t>{escape(text)}</w:t></w:r></w:p>"
    )


def _text_paragraph(text: str) -> str:
    return f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(text)}</w:t></w:r></w:p>"


def _hyperlink_paragraph(text: str, rel_id: str, *, suffix: str = "") -> str:
    suffix_xml = f"<w:r><w:t xml:space=\"preserve\">{escape(suffix)}</w:t></w:r>" if suffix else ""
    return (
        "<w:p>"
        f"<w:hyperlink r:id=\"{escape(rel_id)}\">"
        "<w:r><w:rPr><w:rStyle w:val=\"Hyperlink\"/></w:rPr>"
        f"<w:t>{escape(text)}</w:t></w:r></w:hyperlink>"
        f"{suffix_xml}</w:p>"
    )


def _image_paragraph(rel_id: str, filename: str) -> str:
    return (
        "<w:p><w:r><w:drawing>"
        "<wp:inline distT=\"0\" distB=\"0\" distL=\"0\" distR=\"0\">"
        "<wp:extent cx=\"5486400\" cy=\"3200400\"/>"
        f"<wp:docPr id=\"1\" name=\"{escape(filename)}\"/>"
        "<a:graphic>"
        "<a:graphicData uri=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
        "<pic:pic>"
        "<pic:nvPicPr><pic:cNvPr id=\"0\" name=\"chart\"/><pic:cNvPicPr/></pic:nvPicPr>"
        "<pic:blipFill>"
        f"<a:blip r:embed=\"{escape(rel_id)}\"/>"
        "<a:stretch><a:fillRect/></a:stretch>"
        "</pic:blipFill>"
        "<pic:spPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"5486400\" cy=\"3200400\"/></a:xfrm>"
        "<a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom></pic:spPr>"
        "</pic:pic></a:graphicData></a:graphic>"
        "</wp:inline></w:drawing></w:r></w:p>"
    )


def _section_properties() -> str:
    return (
        "<w:sectPr>"
        "<w:pgSz w:w=\"12240\" w:h=\"15840\"/>"
        "<w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\" "
        "w:header=\"720\" w:footer=\"720\" w:gutter=\"0\"/>"
        "</w:sectPr>"
    )

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
}

for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def q(name: str) -> str:
    prefix, local = name.split(":")
    return f"{{{NS[prefix]}}}{local}"


def w_el(local: str, attrs: dict[str, str] | None = None) -> ET.Element:
    el = ET.Element(q(f"w:{local}"))
    if attrs:
        for key, value in attrs.items():
            el.set(q(f"w:{key}"), value)
    return el


def text_of(el: ET.Element) -> str:
    return "".join(t.text or "" for t in el.findall(".//w:t", NS)).strip()


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def child(el: ET.Element, local: str) -> ET.Element | None:
    return el.find(f"w:{local}", NS)


def ensure_first(parent: ET.Element, local: str) -> ET.Element:
    existing = child(parent, local)
    if existing is not None:
        return existing
    el = w_el(local)
    parent.insert(0, el)
    return el


def ensure_ppr(p: ET.Element) -> ET.Element:
    return ensure_first(p, "pPr")


def ensure_rpr(r: ET.Element) -> ET.Element:
    return ensure_first(r, "rPr")


def remove_children(parent: ET.Element, locals_: list[str]) -> None:
    names = {q(f"w:{name}") for name in locals_}
    for item in list(parent):
        if item.tag in names:
            parent.remove(item)


def append_ordered(parent: ET.Element, element: ET.Element) -> None:
    # OOXML is forgiving, but keeping pPr/rPr children near the front avoids
    # Word repair prompts in stricter readers.
    parent.append(element)


def set_p_style(p: ET.Element, style_id: str | None) -> ET.Element:
    ppr = ensure_ppr(p)
    pstyle = child(ppr, "pStyle")
    if style_id is None:
        if pstyle is not None:
            ppr.remove(pstyle)
        return ppr
    if pstyle is None:
        pstyle = w_el("pStyle")
        ppr.insert(0, pstyle)
    pstyle.set(q("w:val"), style_id)
    return ppr


def set_jc(ppr: ET.Element, value: str | None) -> None:
    remove_children(ppr, ["jc"])
    if value:
        append_ordered(ppr, w_el("jc", {"val": value}))


def set_spacing(ppr: ET.Element, **kwargs: str | None) -> None:
    remove_children(ppr, ["spacing"])
    attrs = {k: v for k, v in kwargs.items() if v is not None}
    if attrs:
        append_ordered(ppr, w_el("spacing", attrs))


def set_indent(ppr: ET.Element, **kwargs: str | None) -> None:
    remove_children(ppr, ["ind"])
    attrs = {k: v for k, v in kwargs.items() if v is not None}
    if attrs:
        append_ordered(ppr, w_el("ind", attrs))


def clear_para_direct(p: ET.Element, keep_section: bool = True) -> ET.Element:
    ppr = ensure_ppr(p)
    keep = []
    if keep_section:
        sect = child(ppr, "sectPr")
        if sect is not None:
            keep.append(sect)
    pstyle = child(ppr, "pStyle")
    if pstyle is not None:
        keep.insert(0, pstyle)
    for item in list(ppr):
        ppr.remove(item)
    for item in keep:
        ppr.append(item)
    return ppr


def set_fonts(rpr: ET.Element, east_asia: str, ascii_font: str = "Times New Roman") -> None:
    remove_children(rpr, ["rFonts"])
    fonts = w_el(
        "rFonts",
        {
            "hint": "eastAsia",
            "ascii": ascii_font,
            "hAnsi": ascii_font,
            "eastAsia": east_asia,
            "cs": ascii_font,
        },
    )
    rpr.insert(0, fonts)


def set_size(rpr: ET.Element, half_points: str) -> None:
    remove_children(rpr, ["sz", "szCs"])
    append_ordered(rpr, w_el("sz", {"val": half_points}))
    append_ordered(rpr, w_el("szCs", {"val": half_points}))


def set_on_off(rpr: ET.Element, local: str, enabled: bool) -> None:
    remove_children(rpr, [local, f"{local}Cs"])
    if enabled:
        append_ordered(rpr, w_el(local))
        append_ordered(rpr, w_el(f"{local}Cs"))


def set_color(rpr: ET.Element, color: str = "000000") -> None:
    remove_children(rpr, ["color"])
    append_ordered(rpr, w_el("color", {"val": color}))


def format_text_runs(
    p: ET.Element,
    *,
    east_asia: str = "宋体",
    ascii_font: str = "Times New Roman",
    size: str = "24",
    bold: bool = False,
    italic: bool = False,
    color: str = "000000",
    keep_existing_bold: bool = False,
) -> None:
    for r in p.findall("w:r", NS):
        if not "".join(t.text or "" for t in r.findall(".//w:t", NS)):
            continue
        rpr = ensure_rpr(r)
        existing_bold = child(rpr, "b") is not None
        set_fonts(rpr, east_asia, ascii_font)
        set_size(rpr, size)
        set_on_off(rpr, "b", bold or (keep_existing_bold and existing_bold))
        set_on_off(rpr, "i", italic)
        set_color(rpr, color)


def format_keyword(p: ET.Element, english: bool = False) -> None:
    ppr = set_p_style(p, None)
    remove_children(ppr, ["jc", "spacing", "ind"])
    set_spacing(ppr, line="300", lineRule="auto")
    if english:
        set_indent(ppr, firstLine="482")
    else:
        set_indent(ppr, left="902", hanging="482")
    label_seen = False
    for r in p.findall("w:r", NS):
        run_text = "".join(t.text or "" for t in r.findall(".//w:t", NS))
        if not run_text:
            continue
        rpr = ensure_rpr(r)
        set_fonts(rpr, "宋体", "Times New Roman")
        set_size(rpr, "24")
        set_on_off(rpr, "i", False)
        if not label_seen:
            set_on_off(rpr, "b", True)
            label_seen = True
        else:
            set_on_off(rpr, "b", False)
        set_color(rpr)


def format_body(p: ET.Element, *, first_line: str = "480") -> None:
    ppr = set_p_style(p, None)
    remove_children(ppr, ["jc", "spacing", "ind", "outlineLvl"])
    set_jc(ppr, "both")
    set_spacing(ppr, line="360", lineRule="auto")
    if first_line != "0":
        set_indent(ppr, firstLine=first_line)
    format_text_runs(p, east_asia="宋体", ascii_font="Times New Roman", size="24", bold=False, italic=False)


def format_reference(p: ET.Element) -> None:
    ppr = set_p_style(p, None)
    remove_children(ppr, ["jc", "spacing", "ind", "outlineLvl"])
    set_jc(ppr, "left")
    set_spacing(ppr, line="360", lineRule="auto")
    format_text_runs(p, east_asia="宋体", ascii_font="Times New Roman", size="24", bold=False, italic=False)


def format_heading(p: ET.Element, style_id: str) -> None:
    set_p_style(p, style_id)
    clear_para_direct(p)
    format_text_runs(p, east_asia="黑体", ascii_font="Times New Roman", size={"2": "32", "3": "30", "4": "28"}.get(style_id, "24"), bold=True, italic=False)


def format_toc_entry(p: ET.Element, style_id: str) -> None:
    set_p_style(p, style_id)
    ppr = clear_para_direct(p)
    set_spacing(ppr, line="312", lineRule="auto")
    if style_id == "26":
        set_indent(ppr, left="210")
    elif style_id == "27":
        set_indent(ppr, left="420")
    format_text_runs(p, east_asia="宋体", ascii_font="Times New Roman", size="28", bold=False, italic=False)


def format_caption(p: ET.Element) -> None:
    ppr = set_p_style(p, None)
    remove_children(ppr, ["jc", "spacing", "ind", "outlineLvl"])
    set_jc(ppr, "center")
    set_indent(ppr, firstLine="360")
    format_text_runs(p, east_asia="黑体", ascii_font="黑体", size="18", bold=False, italic=False)


def format_cover_like_template(p: ET.Element, txt: str) -> None:
    ppr = set_p_style(p, None)
    remove_children(ppr, ["jc", "spacing", "ind", "outlineLvl"])
    c = compact(txt)
    if c == "本科生毕业论文（设计）":
        set_jc(ppr, "center")
        set_spacing(ppr, line="240", lineRule="auto")
        set_indent(ppr, firstLine="0")
        format_text_runs(p, east_asia="宋体", ascii_font="Times New Roman", size="72", bold=True, italic=False)
    elif c.startswith("中文题目") or c.startswith("英文题目"):
        if c.startswith("中文题目"):
            set_jc(ppr, "center")
        set_spacing(ppr, line="240", lineRule="auto")
        set_indent(ppr, left="1558", right="368", hanging="1275")
        format_text_runs(p, east_asia="宋体", ascii_font="Times New Roman", size="32", bold=False, italic=False, keep_existing_bold=True)
    elif c.startswith(("学生姓名", "学号", "学院", "专业", "指导教师")):
        set_spacing(ppr, line="240", lineRule="auto")
        set_indent(ppr, firstLine="283", right="368")
        format_text_runs(p, east_asia="宋体", ascii_font="Times New Roman", size="32", bold=False, italic=False, keep_existing_bold=True)
    elif re.fullmatch(r"\d{4}年\d{1,2}月", c) or re.fullmatch(r"\d{4}年\d{1,2}月", c.replace("0", "")):
        set_jc(ppr, "center")
        set_spacing(ppr, before="156", line="240", lineRule="auto")
        set_indent(ppr, firstLine="0")
        format_text_runs(p, east_asia="宋体", ascii_font="Times New Roman", size="32", bold=True, italic=False)
    elif "承诺书" in txt:
        set_jc(ppr, "center")
        set_spacing(ppr, line="240", lineRule="auto")
        set_indent(ppr, firstLine="0")
        format_text_runs(p, east_asia="宋体", ascii_font="Times New Roman", size="32", bold=True, italic=False)
    elif txt.startswith("本人郑重承诺"):
        set_spacing(ppr, line="240", lineRule="auto")
        set_indent(ppr, firstLine="570")
        format_text_runs(p, east_asia="宋体", ascii_font="Times New Roman", size="28", bold=False, italic=False)
    elif txt.startswith("学士学位论文") or re.match(r"^\d{4}年\s*\d+\s*月\s*\d+\s*日$", txt):
        set_jc(ppr, "right")
        set_spacing(ppr, line="240", lineRule="auto")
        set_indent(ppr, firstLine="570")
        format_text_runs(p, east_asia="宋体", ascii_font="Times New Roman", size="28", bold=False, italic=False)


def format_table(tbl: ET.Element, content_width: int) -> None:
    tbl_pr = child(tbl, "tblPr")
    if tbl_pr is None:
        tbl_pr = w_el("tblPr")
        tbl.insert(0, tbl_pr)
    remove_children(tbl_pr, ["tblW", "tblInd"])
    tbl_pr.insert(0, w_el("tblW", {"w": str(content_width), "type": "dxa"}))
    tbl_pr.insert(1, w_el("tblInd", {"w": "0", "type": "dxa"}))

    grid = child(tbl, "tblGrid")
    rows = tbl.findall("w:tr", NS)
    first_cells = rows[0].findall("w:tc", NS) if rows else []
    if grid is not None:
        cols = grid.findall("w:gridCol", NS)
        widths = [int(col.get(q("w:w"), "0") or "0") for col in cols]
    else:
        widths = []
    if not widths and first_cells:
        widths = [content_width // len(first_cells)] * len(first_cells)
    if widths:
        total = sum(widths) or content_width
        scaled = [max(360, round(w * content_width / total)) for w in widths]
        drift = content_width - sum(scaled)
        if scaled:
            scaled[-1] += drift
        if grid is None:
            grid = w_el("tblGrid")
            tbl.insert(1 if tbl_pr is not None else 0, grid)
        for item in list(grid):
            grid.remove(item)
        for width in scaled:
            grid.append(w_el("gridCol", {"w": str(width)}))
    else:
        scaled = []

    for ri, tr in enumerate(rows):
        cells = tr.findall("w:tc", NS)
        for ci, tc in enumerate(cells):
            tc_pr = child(tc, "tcPr")
            if tc_pr is None:
                tc_pr = w_el("tcPr")
                tc.insert(0, tc_pr)
            remove_children(tc_pr, ["vAlign", "tcMar", "tcW"])
            tc_pr.append(w_el("vAlign", {"val": "center"}))
            mar = w_el("tcMar")
            for side in ["top", "bottom", "left", "right"]:
                mar.append(w_el(side, {"w": "80" if side in {"top", "bottom"} else "120", "type": "dxa"}))
            tc_pr.append(mar)
            if scaled and ci < len(scaled):
                tc_pr.append(w_el("tcW", {"w": str(scaled[ci]), "type": "dxa"}))
            for p in tc.findall(".//w:p", NS):
                ppr = set_p_style(p, None)
                remove_children(ppr, ["jc", "spacing", "ind", "outlineLvl"])
                set_jc(ppr, "center")
                set_spacing(ppr, line="300", lineRule="auto")
                format_text_runs(p, east_asia="宋体" if ri else "黑体", ascii_font="Times New Roman", size="21", bold=(ri == 0), italic=False)


def scale_drawings(root: ET.Element, max_cx: int) -> int:
    changed = 0
    for extent in root.findall(".//wp:extent", NS):
        cx = int(extent.get("cx", "0") or "0")
        cy = int(extent.get("cy", "0") or "0")
        if cx > max_cx and cy > 0:
            ratio = max_cx / cx
            new_cx = int(cx * ratio)
            new_cy = int(cy * ratio)
            extent.set("cx", str(new_cx))
            extent.set("cy", str(new_cy))
            changed += 1
            inline = None
            # The matching a:ext is normally in the same drawing subtree.
            for anc in root.findall(".//w:drawing", NS):
                if extent in list(anc.iter()):
                    inline = anc
                    break
            if inline is not None:
                for aext in inline.findall(".//a:ext", NS):
                    aext.set("cx", str(new_cx))
                    aext.set("cy", str(new_cy))
    return changed


def merge_styles(template_zip: zipfile.ZipFile, work_dir: Path) -> None:
    template_styles = ET.fromstring(template_zip.read("word/styles.xml"))
    target_path = work_dir / "word" / "styles.xml"
    target_styles = ET.parse(target_path).getroot()

    # Keep the submitted document's Normal style so the untouched cover pages
    # do not reflow; import only the template styles that are applied below.
    wanted = {"2", "3", "4", "5", "9", "17", "18", "21", "22", "24", "25", "26", "27"}
    template_by_id = {
        st.get(q("w:styleId")): st
        for st in template_styles.findall("w:style", NS)
        if st.get(q("w:styleId")) in wanted
    }
    for style_id, template_style in template_by_id.items():
        for existing in list(target_styles.findall("w:style", NS)):
            if existing.get(q("w:styleId")) == style_id:
                target_styles.remove(existing)
        target_styles.append(template_style)
    ET.ElementTree(target_styles).write(target_path, encoding="UTF-8", xml_declaration=True)


def apply_document_format(work_dir: Path) -> dict[str, int]:
    document_path = work_dir / "word" / "document.xml"
    root = ET.parse(document_path).getroot()

    # Template page setup: A4; top/bottom 2.54 cm; left/right 3.17 cm.
    content_width_twips = 11906 - 1800 - 1800
    for section_index, sect in enumerate(root.findall(".//w:sectPr", NS)):
        # The submitted thesis already has a JLU cover section whose field
        # underlines are tuned for the long title. Leave that section intact
        # and normalize the body section to the provided template geometry.
        if section_index == 0:
            continue
        pg_sz = child(sect, "pgSz")
        if pg_sz is None:
            pg_sz = w_el("pgSz")
        if pg_sz not in list(sect):
            sect.insert(0, pg_sz)
        pg_sz.set(q("w:w"), "11906")
        pg_sz.set(q("w:h"), "16838")

        pg_mar = child(sect, "pgMar")
        if pg_mar is None:
            pg_mar = w_el("pgMar")
        if pg_mar not in list(sect):
            sect.insert(1, pg_mar)
        for key, value in {
            "top": "1440",
            "right": "1800",
            "bottom": "1440",
            "left": "1800",
            "header": "851",
            "footer": "992",
            "gutter": "0",
        }.items():
            pg_mar.set(q(f"w:{key}"), value)
        cols = child(sect, "cols")
        if cols is None:
            cols = w_el("cols")
        if cols not in list(sect):
            sect.append(cols)
        cols.set(q("w:space"), "425")
        cols.set(q("w:num"), "1")

    table_paras = {id(p) for tbl in root.findall(".//w:tbl", NS) for p in tbl.findall(".//w:p", NS)}
    state = "front"
    actual_body_started = False
    counts = {
        "heading1": 0,
        "heading2": 0,
        "heading3": 0,
        "toc": 0,
        "body": 0,
        "caption": 0,
        "table": 0,
        "reference": 0,
        "image_scaled": 0,
    }

    for p in root.findall(".//w:p", NS):
        if id(p) in table_paras:
            continue
        txt = text_of(p)
        has_drawing = p.find(".//w:drawing", NS) is not None
        if not txt:
            if has_drawing:
                ppr = set_p_style(p, None)
                remove_children(ppr, ["jc", "spacing", "ind", "outlineLvl"])
                set_jc(ppr, "center")
                set_spacing(ppr, before="120", after="120", line="240", lineRule="auto")
            continue

        c = compact(txt)
        has_dots = "..." in txt or "……" in txt

        if c in {"摘要", "Abstract", "目录", "插图清单", "附表清单"}:
            state = {
                "摘要": "abstract_cn",
                "Abstract": "abstract_en",
                "目录": "toc",
                "插图清单": "fig_list",
                "附表清单": "table_list",
            }[c]
            format_heading(p, "2")
            counts["heading1"] += 1
            continue

        if re.match(r"^第\s*\d+\s*章", txt) and not has_dots:
            state = "body"
            actual_body_started = True
            format_heading(p, "2")
            counts["heading1"] += 1
            continue

        if c in {"参考文献", "致谢"} and not has_dots:
            state = "references" if c == "参考文献" else "thanks"
            actual_body_started = True
            format_heading(p, "2")
            counts["heading1"] += 1
            continue

        if state in {"fig_list", "table_list"} and has_dots:
            # The provided template has a manual TOC but no figure/table-list
            # sample. Preserve the submitted figure/table-list layout, which
            # already fits cleanly on the page.
            continue

        if state == "toc" and has_dots:
            if re.match(r"^第\s*\d+\s*章", txt) or c.startswith(("参考文献", "致谢")):
                style_id = "25"
            elif re.match(r"^\d+\.\d+\.\d+", txt):
                style_id = "27"
            else:
                style_id = "26"
            format_toc_entry(p, style_id)
            counts["toc"] += 1
            continue

        if actual_body_started and re.match(r"^\d+\.\d+\.\d+", txt):
            format_heading(p, "4")
            counts["heading3"] += 1
            continue

        if actual_body_started and re.match(r"^\d+\.\d+", txt):
            format_heading(p, "3")
            counts["heading2"] += 1
            continue

        if actual_body_started and re.match(r"^[图表]\s*\d+[.-]\d+", txt):
            format_caption(p)
            counts["caption"] += 1
            continue

        if c.startswith("关键词"):
            format_keyword(p, english=False)
            continue
        if c.lower().startswith("keywords"):
            format_keyword(p, english=True)
            continue

        if state == "abstract_en":
            ppr = set_p_style(p, "9")
            remove_children(ppr, ["jc", "spacing", "ind", "outlineLvl"])
            set_jc(ppr, "both")
            set_spacing(ppr, before="0", after="0", line="360", lineRule="atLeast")
            set_indent(ppr, firstLine="480")
            format_text_runs(p, east_asia="宋体", ascii_font="Times New Roman", size="24", bold=False, italic=False)
            counts["body"] += 1
        elif state in {"abstract_cn", "body", "thanks"}:
            format_body(p)
            counts["body"] += 1
        elif state == "references":
            format_reference(p)
            counts["reference"] += 1
        elif state == "front":
            continue

    for tbl in root.findall(".//w:tbl", NS):
        format_table(tbl, content_width_twips)
        counts["table"] += 1

    counts["image_scaled"] = scale_drawings(root, content_width_twips * 635)
    ET.ElementTree(root).write(document_path, encoding="UTF-8", xml_declaration=True)
    return counts


def unpack_docx(docx: Path, work_dir: Path) -> None:
    with zipfile.ZipFile(docx) as zf:
        zf.extractall(work_dir)


def pack_docx(work_dir: Path, out_docx: Path) -> None:
    if out_docx.exists():
        out_docx.unlink()
    with zipfile.ZipFile(out_docx, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(work_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(work_dir).as_posix())


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: format_thesis.py TEMPLATE.docx INPUT.docx OUTPUT.docx")
    template = Path(sys.argv[1])
    input_docx = Path(sys.argv[2])
    output_docx = Path(sys.argv[3])
    output_docx.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="chemaster-docx-") as tmp:
        work_dir = Path(tmp)
        unpack_docx(input_docx, work_dir)
        with zipfile.ZipFile(template) as template_zip:
            merge_styles(template_zip, work_dir)
            if "word/numbering.xml" in template_zip.namelist():
                numbering_out = work_dir / "word" / "numbering.xml"
                numbering_out.parent.mkdir(parents=True, exist_ok=True)
                numbering_out.write_bytes(template_zip.read("word/numbering.xml"))
        counts = apply_document_format(work_dir)
        pack_docx(work_dir, output_docx)

    backup = input_docx.with_suffix(".原始备份.docx")
    if not backup.exists():
        shutil.copy2(input_docx, backup)
    print(f"formatted={output_docx}")
    print(f"backup={backup}")
    for key, value in counts.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()

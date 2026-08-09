from __future__ import annotations

import collections
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def q(name: str) -> str:
    prefix, local = name.split(":")
    return f"{{{NS[prefix]}}}{local}"


def val(el: ET.Element | None, attr: str = "w:val") -> str | None:
    if el is None:
        return None
    return el.attrib.get(q(attr))


def text_of(p: ET.Element) -> str:
    return "".join(t.text or "" for t in p.findall(".//w:t", NS)).strip()


def spacing_summary(ppr: ET.Element | None) -> dict:
    sp = ppr.find("w:spacing", NS) if ppr is not None else None
    if sp is None:
        return {}
    keys = ["before", "after", "line", "lineRule"]
    return {k: sp.attrib.get(q(f"w:{k}")) for k in keys if sp.attrib.get(q(f"w:{k}"))}


def indent_summary(ppr: ET.Element | None) -> dict:
    ind = ppr.find("w:ind", NS) if ppr is not None else None
    if ind is None:
        return {}
    keys = ["firstLine", "left", "right", "hanging"]
    return {k: ind.attrib.get(q(f"w:{k}")) for k in keys if ind.attrib.get(q(f"w:{k}"))}


def run_summary(rpr: ET.Element | None) -> dict:
    if rpr is None:
        return {}
    rfonts = rpr.find("w:rFonts", NS)
    size = rpr.find("w:sz", NS)
    color = rpr.find("w:color", NS)
    return {
        "fonts": dict(rfonts.attrib) if rfonts is not None else {},
        "sz": val(size),
        "bold": rpr.find("w:b", NS) is not None,
        "italic": rpr.find("w:i", NS) is not None,
        "color": val(color),
    }


def p_summary(ppr: ET.Element | None) -> dict:
    if ppr is None:
        return {}
    jc = ppr.find("w:jc", NS)
    outline = ppr.find("w:outlineLvl", NS)
    return {
        "jc": val(jc),
        "spacing": spacing_summary(ppr),
        "indent": indent_summary(ppr),
        "outline": val(outline),
    }


def style_summaries(root: ET.Element) -> dict:
    result = {}
    for st in root.findall("w:style", NS):
        st_type = st.attrib.get(q("w:type"))
        style_id = st.attrib.get(q("w:styleId"))
        name = val(st.find("w:name", NS))
        if not style_id:
            continue
        result[style_id] = {
            "type": st_type,
            "name": name,
            "basedOn": val(st.find("w:basedOn", NS)),
            "next": val(st.find("w:next", NS)),
            "pPr": p_summary(st.find("w:pPr", NS)),
            "rPr": run_summary(st.find("w:rPr", NS)),
        }
    return result


def sect_summary(root: ET.Element) -> list[dict]:
    sects = []
    for sect in root.findall(".//w:sectPr", NS):
        pg_sz = sect.find("w:pgSz", NS)
        pg_mar = sect.find("w:pgMar", NS)
        cols = sect.find("w:cols", NS)
        sects.append(
            {
                "pgSz": dict(pg_sz.attrib) if pg_sz is not None else {},
                "pgMar": dict(pg_mar.attrib) if pg_mar is not None else {},
                "cols": dict(cols.attrib) if cols is not None else {},
            }
        )
    return sects


def para_style(p: ET.Element) -> str:
    ppr = p.find("w:pPr", NS)
    if ppr is None:
        return "Normal"
    st = ppr.find("w:pStyle", NS)
    return val(st) or "Normal"


def para_direct_summary(p: ET.Element) -> dict:
    ppr = p.find("w:pPr", NS)
    runs = []
    for r in p.findall("w:r", NS):
        if text_of(r):
            runs.append(run_summary(r.find("w:rPr", NS)))
        if len(runs) >= 3:
            break
    return {"pPr": p_summary(ppr), "runs": runs}


def extract(docx: Path) -> dict:
    with zipfile.ZipFile(docx) as zf:
        document = ET.fromstring(zf.read("word/document.xml"))
        styles = ET.fromstring(zf.read("word/styles.xml"))
        settings = ET.fromstring(zf.read("word/settings.xml"))
        numbering = ET.fromstring(zf.read("word/numbering.xml")) if "word/numbering.xml" in zf.namelist() else None

    paras = document.findall(".//w:p", NS)
    nonempty = [(p, text_of(p)) for p in paras if text_of(p)]
    counter = collections.Counter(para_style(p) for p, _ in nonempty)
    samples = []
    for p, txt in nonempty[:120]:
        samples.append(
            {
                "style": para_style(p),
                "text": txt[:120],
                "direct": para_direct_summary(p),
            }
        )
    tables = document.findall(".//w:tbl", NS)
    return {
        "path": str(docx),
        "paragraph_count": len(nonempty),
        "table_count": len(tables),
        "style_counts": counter.most_common(40),
        "styles": style_summaries(styles),
        "sections": sect_summary(document),
        "first_samples": samples,
        "settings_default_tab": val(settings.find(".//w:defaultTabStop", NS)),
        "numbering_present": numbering is not None,
    }


def main() -> None:
    out = {}
    for arg in sys.argv[1:]:
        p = Path(arg)
        out[p.name] = extract(p)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

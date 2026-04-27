#!/usr/bin/env python3
"""Extract chemical structure candidates, predict SMILES, and annotate a PDF.

The main command is intentionally single-step:

    python scripts/annotate_pdf_smiles.py article.pdf

Outputs are written to output/chem_pdf/<pdf-name>/:
  - crops/*.png
  - figures/*.png
  - manifest.jsonl
  - results.csv
  - contact_sheet.png
  - <pdf-name>_annotated.pdf
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import shutil
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import fitz
import numpy as np
from PIL import Image, ImageDraw

from extract_chemical_structure_candidates import Candidate, find_candidates, slugify

try:
    fitz.TOOLS.mupdf_display_errors(False)
    fitz.TOOLS.mupdf_display_warnings(False)
except Exception:
    pass


@dataclass(frozen=True)
class SourceImage:
    source_id: str
    page_index: int
    kind: str
    rgb: np.ndarray
    page_bbox: fitz.Rect
    image_path: Path


def image_bytes_to_rgb(image_bytes: bytes) -> np.ndarray:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return np.asarray(image)


def pixmap_to_rgb(pix: fitz.Pixmap) -> np.ndarray:
    mode = "RGBA" if pix.alpha else "RGB"
    image = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
    return np.asarray(image.convert("RGB"))


def crop_page_bbox(
    candidate: Candidate, image_width: int, image_height: int, page_bbox: fitz.Rect
) -> fitz.Rect:
    x1, y1, x2, y2 = candidate.bbox
    sx = page_bbox.width / max(image_width, 1)
    sy = page_bbox.height / max(image_height, 1)
    return fitz.Rect(
        page_bbox.x0 + x1 * sx,
        page_bbox.y0 + y1 * sy,
        page_bbox.x0 + x2 * sx,
        page_bbox.y0 + y2 * sy,
    )


def iter_source_images(
    doc: fitz.Document,
    figures_dir: Path,
    pdf_slug: str,
    render_pages: bool,
    render_dpi: int,
    include_embedded: bool = True,
) -> Iterable[SourceImage]:
    for page_index, page in enumerate(doc):
        page_number = page_index + 1
        block_index = 0
        if include_embedded:
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 1 or "image" not in block:
                    continue
                block_index += 1
                rgb = image_bytes_to_rgb(block["image"])
                ext = block.get("ext") or "png"
                source_id = f"p{page_number:03d}_img{block_index:02d}"
                image_path = figures_dir / f"{pdf_slug}_{source_id}.{ext}"
                Image.fromarray(rgb).save(image_path)
                yield SourceImage(
                    source_id=source_id,
                    page_index=page_index,
                    kind="embedded",
                    rgb=rgb,
                    page_bbox=fitz.Rect(block["bbox"]),
                    image_path=image_path,
                )

        if render_pages:
            zoom = render_dpi / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            rgb = pixmap_to_rgb(pix)
            source_id = f"p{page_number:03d}_page"
            image_path = figures_dir / f"{pdf_slug}_{source_id}.png"
            Image.fromarray(rgb).save(image_path)
            yield SourceImage(
                source_id=source_id,
                page_index=page_index,
                kind="rendered_page",
                rgb=rgb,
                page_bbox=page.rect,
                image_path=image_path,
            )


def decimer_segmentation_available() -> bool:
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    try:
        import decimer_segmentation  # noqa: F401

        return True
    except Exception:
        return False


def find_decimer_candidates(rgb: np.ndarray, max_candidates: int) -> list[Candidate]:
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    from decimer_segmentation import segment_chemical_structures

    _, bboxes = segment_chemical_structures(
        rgb,
        expand=True,
        visualization=False,
        return_bboxes=True,
    )

    height, width = rgb.shape[:2]
    candidates: list[Candidate] = []
    for bbox in bboxes[:max_candidates]:
        x1, y1, x2, y2 = [int(v) for v in bbox]
        x1 = max(0, min(width - 1, x1))
        y1 = max(0, min(height - 1, y1))
        x2 = max(x1 + 1, min(width, x2))
        y2 = max(y1 + 1, min(height, y2))
        candidates.append(
            Candidate(
                bbox=(x1, y1, x2, y2),
                score=1.0,
                features={
                    "width": float(x2 - x1),
                    "height": float(y2 - y1),
                    "area_ratio": float(((x2 - x1) * (y2 - y1)) / max(width * height, 1)),
                },
            )
        )
    return candidates


def resolve_locator_engine(requested: str) -> str:
    if requested == "auto":
        return "decimer" if decimer_segmentation_available() else "heuristic"
    return requested


def locate_candidates(
    rgb: np.ndarray,
    locator_engine: str,
    min_score: float,
    max_candidates: int,
) -> list[Candidate]:
    if locator_engine == "decimer":
        return find_decimer_candidates(rgb, max_candidates=max_candidates)
    return find_candidates(
        rgb,
        min_score=min_score,
        max_candidates=max_candidates,
    )


class SmilesPredictor:
    def __init__(self, engine: str) -> None:
        self.engine = engine
        self.available = False
        self.error: str | None = None
        self._predict = None

        if engine == "none":
            self.error = "SMILES prediction disabled"
            return

        try:
            os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
            from DECIMER import predict_SMILES

            self._predict = predict_SMILES
            self.available = True
        except Exception as exc:  # noqa: BLE001 - dependency import failures vary.
            self.error = f"DECIMER unavailable: {exc}"

    def predict(self, crop_path: Path) -> tuple[str, str | None]:
        if not self.available or self._predict is None:
            return "", self.error
        try:
            smiles = self._predict(str(crop_path))
            if isinstance(smiles, (list, tuple)):
                smiles = smiles[0] if smiles else ""
            smiles = str(smiles).strip()
            return smiles, None
        except Exception as exc:  # noqa: BLE001 - OCR failures should not stop a batch.
            return "", f"prediction failed: {exc}"


def maybe_canonicalize_smiles(smiles: str) -> tuple[str, bool, str | None]:
    if not smiles:
        return "", False, None
    try:
        from rdkit import Chem
        from rdkit import RDLogger

        RDLogger.DisableLog("rdApp.*")
    except Exception:
        return smiles, True, None

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return "", False, "RDKit could not parse predicted SMILES"
    return Chem.MolToSmiles(mol, canonical=True), True, None


def classify_smiles(
    smiles: str,
    canonical_smiles: str,
    smiles_valid: bool,
    warning: str,
    max_smiles_length: int,
) -> str:
    if not smiles:
        return "not_predicted"
    if warning:
        return "low_confidence"
    if not smiles_valid or not canonical_smiles:
        return "low_confidence"
    if len(canonical_smiles) > max_smiles_length:
        return "too_long"
    return "valid"


def label_for_record(record: dict, max_length: int = 90) -> str:
    status = record.get("smiles_status") or "not_predicted"
    if status == "valid":
        return shorten(record.get("canonical_smiles", ""), max_length)
    if status == "too_long":
        return "SMILES low confidence: predicted string too long"
    if status == "low_confidence":
        return "SMILES low confidence: see CSV"
    return "SMILES: pending"


def record_to_csv_row(record: dict) -> dict:
    return {
        "id": record["id"],
        "page": record["page"],
        "score": record["score"],
        "smiles": record.get("smiles", ""),
        "canonical_smiles": record.get("canonical_smiles", ""),
        "smiles_valid": record.get("smiles_valid", False),
        "smiles_status": record.get("smiles_status", ""),
        "crop_path": record["crop_path"],
        "source_kind": record["source_kind"],
        "locator_engine": record.get("locator_engine", ""),
        "source_image": record["source_image"],
        "warning": record.get("warning", ""),
    }


def write_results(records: list[dict], pdf_out: Path) -> None:
    manifest = pdf_out / "manifest.jsonl"
    with manifest.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    csv_path = pdf_out / "results.csv"
    fieldnames = [
        "id",
        "page",
        "score",
        "smiles",
        "canonical_smiles",
        "smiles_valid",
        "smiles_status",
        "crop_path",
        "source_kind",
        "locator_engine",
        "source_image",
        "warning",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record_to_csv_row(record))


def shorten(value: str, limit: int = 70) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def write_annotated_pdf(
    input_pdf: Path, doc: fitz.Document, records: list[dict], output_pdf: Path
) -> None:
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas

    by_page: dict[int, list[dict]] = {}
    for record in records:
        page = record.get("page")
        page_bbox = record.get("page_bbox")
        if page is None or not page_bbox:
            continue
        by_page.setdefault(int(page) - 1, []).append(record)

    overlay_buffer = io.BytesIO()
    overlay = canvas.Canvas(overlay_buffer)
    for page_index in range(doc.page_count):
        page_rect = doc[page_index].rect
        page_width = float(page_rect.width)
        page_height = float(page_rect.height)
        overlay.setPageSize((page_width, page_height))

        for record in sorted(
            by_page.get(page_index, []), key=lambda r: (r["page_bbox"][1], r["page_bbox"][0])
        ):
            rect = fitz.Rect(record["page_bbox"])
            label = label_for_record(record, max_length=90)

            overlay.setStrokeColorRGB(1.0, 0.12, 0.05)
            overlay.setLineWidth(0.9)
            overlay.rect(
                rect.x0,
                page_height - rect.y1,
                rect.width,
                rect.height,
                stroke=1,
                fill=0,
            )

            label_width = min(max(rect.width, 115), page_width - rect.x0 - 8)
            label_height = 22 if len(label) < 45 else 34
            label_x0 = rect.x0
            label_y0 = max(4, rect.y0 - label_height - 2)
            if label_y0 <= 4:
                label_y0 = min(page_height - label_height - 4, rect.y1 + 2)
            label_x1 = min(page_width - 4, label_x0 + label_width)
            label_y1 = min(page_height - 4, label_y0 + label_height)

            overlay.setFillColorRGB(1.0, 0.98, 0.78)
            overlay.setStrokeColorRGB(1.0, 0.12, 0.05)
            overlay.setLineWidth(0.4)
            overlay.rect(
                label_x0,
                page_height - label_y1,
                label_x1 - label_x0,
                label_y1 - label_y0,
                stroke=1,
                fill=1,
            )

            overlay.setFillColorRGB(0.05, 0.05, 0.05)
            overlay.setFont("Helvetica", 5.5)
            for line_index, line in enumerate(textwrap.wrap(label, width=34, max_lines=2)):
                overlay.drawString(
                    label_x0 + 3,
                    page_height - label_y0 - 8 - (line_index * 7),
                    line,
                )

        overlay.showPage()

    overlay.save()
    overlay_buffer.seek(0)

    source_reader = PdfReader(str(input_pdf), strict=False)
    overlay_reader = PdfReader(overlay_buffer, strict=False)
    writer = PdfWriter()
    for page_index, page in enumerate(source_reader.pages):
        if page_index < len(overlay_reader.pages):
            page.merge_page(overlay_reader.pages[page_index])
        writer.add_page(page)

    with output_pdf.open("wb") as handle:
        writer.write(handle)


def make_contact_sheet(records: list[dict], output_path: Path) -> None:
    if not records:
        return
    cols = 3
    cell_w, cell_h = 330, 250
    rows = (len(records) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "white")
    draw = ImageDraw.Draw(sheet)

    for index, record in enumerate(records):
        crop_path = Path(record["crop_path"])
        if not crop_path.exists():
            continue
        image = Image.open(crop_path).convert("RGB")
        image.thumbnail((300, 170))
        x = (index % cols) * cell_w + 12
        y = (index // cols) * cell_h + 58
        label = f'#{index + 1} p{record["page"]} s={record["score"]:.2f}'
        smiles = label_for_record(record, max_length=52)
        draw.text((x, y - 45), label, fill=(0, 0, 0))
        draw.text((x, y - 28), smiles, fill=(120, 0, 0))
        sheet.paste(image, (x, y))

    sheet.save(output_path)


def process_pdf(args: argparse.Namespace, pdf: Path) -> Path:
    pdf = pdf.expanduser().resolve()
    if not pdf.exists():
        raise FileNotFoundError(pdf)

    pdf_slug = slugify(pdf.stem)
    pdf_out = Path(args.out).resolve() / pdf_slug
    crops_dir = pdf_out / "crops"
    figures_dir = pdf_out / "figures"
    if args.clean:
        shutil.rmtree(pdf_out, ignore_errors=True)
    crops_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf)
    predictor = SmilesPredictor(args.smiles_engine)
    locator_engine = resolve_locator_engine(args.locator_engine)
    use_page_locator = locator_engine == "decimer"
    records: list[dict] = []

    for source in iter_source_images(
        doc,
        figures_dir=figures_dir,
        pdf_slug=pdf_slug,
        render_pages=args.render_pages or use_page_locator,
        render_dpi=args.render_dpi,
        include_embedded=not use_page_locator,
    ):
        height, width = source.rgb.shape[:2]
        candidates = locate_candidates(
            source.rgb,
            locator_engine=locator_engine,
            min_score=args.min_score,
            max_candidates=args.max_candidates_per_source,
        )
        for candidate_index, candidate in enumerate(candidates, start=1):
            crop_id = f"{pdf_slug}_{source.source_id}_c{candidate_index:02d}"
            crop_path = crops_dir / f"{crop_id}.png"
            x1, y1, x2, y2 = candidate.bbox
            Image.fromarray(source.rgb[y1:y2, x1:x2]).save(crop_path)

            page_rect = crop_page_bbox(candidate, width, height, source.page_bbox)
            smiles, warning = predictor.predict(crop_path)
            canonical_smiles, smiles_valid, canonical_warning = maybe_canonicalize_smiles(smiles)
            warnings = "; ".join(
                value for value in [warning, canonical_warning] if value
            )
            smiles_status = classify_smiles(
                smiles=smiles,
                canonical_smiles=canonical_smiles,
                smiles_valid=smiles_valid,
                warning=warnings,
                max_smiles_length=args.max_smiles_length,
            )

            record = {
                "id": crop_id,
                "pdf": str(pdf),
                "page": source.page_index + 1,
                "source_kind": source.kind,
                "locator_engine": locator_engine,
                "source_image": str(source.image_path),
                "crop_path": str(crop_path),
                "source_bbox_xyxy": [
                    round(source.page_bbox.x0, 3),
                    round(source.page_bbox.y0, 3),
                    round(source.page_bbox.x1, 3),
                    round(source.page_bbox.y1, 3),
                ],
                "bbox_xyxy": list(candidate.bbox),
                "page_bbox": [
                    round(page_rect.x0, 3),
                    round(page_rect.y0, 3),
                    round(page_rect.x1, 3),
                    round(page_rect.y1, 3),
                ],
                "score": round(candidate.score, 4),
                "features": {
                    key: round(value, 4) for key, value in candidate.features.items()
                },
                "smiles": smiles,
                "canonical_smiles": canonical_smiles,
                "smiles_valid": smiles_valid,
                "smiles_status": smiles_status,
                "warning": warnings,
            }
            records.append(record)

    write_results(records, pdf_out)
    make_contact_sheet(records, pdf_out / "contact_sheet.png")

    annotated_pdf = pdf_out / f"{pdf_slug}_annotated.pdf"
    if args.annotate:
        write_annotated_pdf(pdf, doc, records, annotated_pdf)
    doc.close()

    print(f"{pdf}: {len(records)} candidates")
    if predictor.error:
        print(f"SMILES engine: {predictor.error}")
    print(f"locator engine: {locator_engine}")
    print(f"output: {pdf_out}")
    return pdf_out


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract likely chemical structures, predict SMILES, and annotate PDF."
    )
    parser.add_argument("pdfs", nargs="+", help="Input PDF files")
    parser.add_argument("--out", default="output/chem_pdf", help="Output directory")
    parser.add_argument("--min-score", type=float, default=0.85)
    parser.add_argument("--max-candidates-per-source", type=int, default=16)
    parser.add_argument(
        "--locator-engine",
        choices=("auto", "decimer", "heuristic"),
        default="heuristic",
        help="heuristic is the default; decimer uses DECIMER-Segmentation on rendered pages; auto tries decimer when installed.",
    )
    parser.add_argument(
        "--render-pages",
        action="store_true",
        help="Also process rendered full pages. Slower but helps vector/scanned PDFs.",
    )
    parser.add_argument("--render-dpi", type=int, default=220)
    parser.add_argument(
        "--max-smiles-length",
        type=int,
        default=180,
        help="Canonical SMILES longer than this are kept in CSV but marked low confidence in the PDF.",
    )
    parser.add_argument(
        "--smiles-engine",
        choices=("decimer", "none"),
        default="decimer",
        help="DECIMER predicts SMILES when installed; none only annotates candidates.",
    )
    parser.add_argument("--no-annotate", dest="annotate", action="store_false")
    parser.add_argument("--no-clean", dest="clean", action="store_false")
    parser.set_defaults(annotate=True, clean=True)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    for pdf in args.pdfs:
        process_pdf(args, Path(pdf))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

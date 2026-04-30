#!/usr/bin/env python3
"""Extract likely chemical-structure image crops from scientific PDFs.

This is step 1 of a PDF -> structure-image -> SMILES workflow.  It does not
perform optical chemical structure recognition.  It creates candidate crops
that can later be passed to DECIMER, MolScribe, OSRA, or another OCSR engine.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
from PIL import Image, ImageDraw


PDFIMAGES = shutil.which("pdfimages")
PDFINFO = shutil.which("pdfinfo")
PDFTOPPM = shutil.which("pdftoppm")


@dataclass(frozen=True)
class Candidate:
    bbox: tuple[int, int, int, int]
    score: float
    features: dict[str, float]


def slugify(value: str) -> str:
    value = re.sub(r"\s+", "-", value.strip())
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    return value.strip("-") or "pdf"


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def page_count(pdf: Path) -> int | None:
    if not PDFINFO:
        return None
    proc = subprocess.run(
        [PDFINFO, str(pdf)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    return None


def extract_pdf_images(pdf: Path, tmp_dir: Path) -> list[Path]:
    if not PDFIMAGES:
        raise RuntimeError("Missing poppler tool: pdfimages")
    prefix = tmp_dir / "embedded"
    run([PDFIMAGES, "-png", "-p", str(pdf), str(prefix)])
    return sorted(tmp_dir.glob("embedded-*.png"))


def render_pdf_pages(pdf: Path, tmp_dir: Path, dpi: int) -> list[Path]:
    if not PDFTOPPM:
        raise RuntimeError("Missing poppler tool: pdftoppm")
    prefix = tmp_dir / "page"
    run([PDFTOPPM, "-r", str(dpi), "-png", str(pdf), str(prefix)])
    return sorted(tmp_dir.glob("page-*.png"))


def parse_page_from_name(path: Path) -> int | None:
    embedded = re.search(r"-(\d{3,})-\d{3,}\.png$", path.name)
    if embedded:
        return int(embedded.group(1))
    rendered = re.search(r"-(\d+)\.png$", path.name)
    if rendered:
        return int(rendered.group(1))
    return None


def load_rgb(path: Path) -> np.ndarray:
    image = Image.open(path).convert("RGB")
    return np.asarray(image)


def ink_mask(rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]

    dark_or_colored = (gray < 242) | ((saturation > 35) & (value < 250))
    mask = dark_or_colored.astype(np.uint8) * 255

    mask = cv2.medianBlur(mask, 3)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    return mask


def expand_box(
    box: tuple[int, int, int, int], pad: int, width: int, height: int
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    return max(0, x1 - pad), max(0, y1 - pad), min(width, x2 + pad), min(height, y2 + pad)


def line_features(gray_crop: np.ndarray, mask_crop: np.ndarray) -> dict[str, float]:
    h, w = gray_crop.shape
    edges = cv2.Canny(gray_crop, 60, 180)
    min_len = max(8, min(w, h) // 14)
    threshold = max(8, min(w, h) // 18)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=threshold,
        minLineLength=min_len,
        maxLineGap=4,
    )
    if lines is None:
        return {
            "line_count": 0.0,
            "short_line_ratio": 0.0,
            "non_axis_line_ratio": 0.0,
            "median_line_length": 0.0,
        }

    lengths: list[float] = []
    non_axis = 0
    short_lines = 0
    for line in lines[:, 0, :]:
        x1, y1, x2, y2 = [int(v) for v in line]
        length = math.hypot(x2 - x1, y2 - y1)
        if length <= 0:
            continue
        angle = abs(math.degrees(math.atan2(y2 - y1, x2 - x1))) % 180
        axis_angle = min(angle, abs(angle - 90), abs(angle - 180))
        if axis_angle > 12:
            non_axis += 1
        if length < max(35, 0.45 * max(w, h)):
            short_lines += 1
        lengths.append(length)

    if not lengths:
        return {
            "line_count": 0.0,
            "short_line_ratio": 0.0,
            "non_axis_line_ratio": 0.0,
            "median_line_length": 0.0,
        }

    line_count = float(len(lengths))
    return {
        "line_count": line_count,
        "short_line_ratio": short_lines / line_count,
        "non_axis_line_ratio": non_axis / line_count,
        "median_line_length": float(np.median(lengths)),
    }


def component_count(mask_crop: np.ndarray) -> int:
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask_crop, connectivity=8)
    usable = 0
    for idx in range(1, count):
        area = int(stats[idx, cv2.CC_STAT_AREA])
        if 3 <= area <= 5000:
            usable += 1
    return usable


def score_box(
    rgb: np.ndarray, base_mask: np.ndarray, box: tuple[int, int, int, int]
) -> Candidate | None:
    height, width = base_mask.shape
    x1, y1, x2, y2 = expand_box(box, pad=10, width=width, height=height)
    bw = x2 - x1
    bh = y2 - y1
    area = bw * bh
    image_area = width * height

    if bw < 42 or bh < 32:
        return None
    if area < 1_600 or area > image_area * 0.45:
        return None

    aspect = bw / max(bh, 1)
    if aspect < 0.18 or aspect > 7.5:
        return None

    mask_crop = base_mask[y1:y2, x1:x2]
    gray_crop = cv2.cvtColor(rgb[y1:y2, x1:x2], cv2.COLOR_RGB2GRAY)
    density = float(np.count_nonzero(mask_crop) / max(mask_crop.size, 1))
    if density < 0.008 or density > 0.62:
        return None

    lines = line_features(gray_crop, mask_crop)
    components = float(component_count(mask_crop))
    line_count = lines["line_count"]

    line_score = min(line_count / 12.0, 1.0)
    component_score = min(components / 18.0, 1.0)
    density_score = max(0.0, 1.0 - abs(density - 0.11) / 0.16)
    non_axis_score = min(lines["non_axis_line_ratio"] / 0.35, 1.0)
    short_line_score = lines["short_line_ratio"]
    size_score = min(area / (image_area * 0.04), 1.0)

    score = (
        0.27 * line_score
        + 0.18 * component_score
        + 0.18 * density_score
        + 0.17 * non_axis_score
        + 0.12 * short_line_score
        + 0.08 * size_score
    )

    features = {
        "width": float(bw),
        "height": float(bh),
        "area_ratio": area / image_area,
        "aspect": aspect,
        "ink_density": density,
        "component_count": components,
        **lines,
    }
    return Candidate((x1, y1, x2, y2), score, features)


def iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / max(area_a + area_b - inter, 1)


def contains(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> float:
    ox1, oy1, ox2, oy2 = outer
    ix1, iy1, ix2, iy2 = inner
    x1, y1 = max(ox1, ix1), max(oy1, iy1)
    x2, y2 = min(ox2, ix2), min(oy2, iy2)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    inner_area = max((ix2 - ix1) * (iy2 - iy1), 1)
    return inter / inner_area


def nms(candidates: list[Candidate], max_candidates: int) -> list[Candidate]:
    ordered = sorted(candidates, key=lambda c: c.score, reverse=True)
    kept: list[Candidate] = []
    for cand in ordered:
        duplicate = False
        for existing in kept:
            cand_area = (cand.bbox[2] - cand.bbox[0]) * (cand.bbox[3] - cand.bbox[1])
            exist_area = (existing.bbox[2] - existing.bbox[0]) * (
                existing.bbox[3] - existing.bbox[1]
            )
            if iou(cand.bbox, existing.bbox) > 0.30:
                duplicate = True
                break
            if contains(existing.bbox, cand.bbox) > 0.90 and exist_area < cand_area * 2.5:
                duplicate = True
                break
            if contains(cand.bbox, existing.bbox) > 0.90 and cand_area > exist_area * 2.5:
                duplicate = True
                break
        if not duplicate:
            kept.append(cand)
        if len(kept) >= max_candidates:
            break
    return sorted(kept, key=lambda c: (c.bbox[1], c.bbox[0]))


def find_candidates(
    rgb: np.ndarray, min_score: float, max_candidates: int
) -> list[Candidate]:
    mask = ink_mask(rgb)
    height, width = mask.shape
    candidates: list[Candidate] = []

    for kernel_size, iterations in ((5, 1), (9, 1), (13, 1)):
        kernel = np.ones((kernel_size, kernel_size), np.uint8)
        grouped = cv2.dilate(mask, kernel, iterations=iterations)
        count, _, stats, _ = cv2.connectedComponentsWithStats(grouped, connectivity=8)
        for idx in range(1, count):
            x = int(stats[idx, cv2.CC_STAT_LEFT])
            y = int(stats[idx, cv2.CC_STAT_TOP])
            w = int(stats[idx, cv2.CC_STAT_WIDTH])
            h = int(stats[idx, cv2.CC_STAT_HEIGHT])

            if x <= 2 or y <= 2 or x + w >= width - 2 or y + h >= height - 2:
                pass

            cand = score_box(rgb, mask, (x, y, x + w, y + h))
            if cand and cand.score >= min_score:
                candidates.append(cand)

    return nms(candidates, max_candidates=max_candidates)


def save_crop(rgb: np.ndarray, candidate: Candidate, path: Path) -> None:
    x1, y1, x2, y2 = candidate.bbox
    Image.fromarray(rgb[y1:y2, x1:x2]).save(path)


def make_contact_sheet(records: list[dict], output_path: Path) -> None:
    thumbs: list[tuple[str, Image.Image]] = []
    for sheet_index, record in enumerate(records, start=1):
        path = Path(record["crop_path"])
        if not path.exists():
            continue
        image = Image.open(path).convert("RGB")
        image.thumbnail((220, 170))
        label = f'#{sheet_index} p{record.get("page") or 0} s={record["score"]:.2f}'
        thumbs.append((label, image.copy()))

    if not thumbs:
        return

    cols = 4
    cell_w, cell_h = 250, 210
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "white")
    draw = ImageDraw.Draw(sheet)
    for idx, (label, image) in enumerate(thumbs):
        x = (idx % cols) * cell_w + 12
        y = (idx // cols) * cell_h + 28
        draw.text((x, y - 20), label, fill=(0, 0, 0))
        sheet.paste(image, (x, y))
    sheet.save(output_path)


def save_decimer_segment(segment: np.ndarray, path: Path) -> None:
    if segment.ndim == 2:
        Image.fromarray(segment).save(path)
        return
    if segment.shape[2] == 4:
        Image.fromarray(segment).save(path)
        return
    Image.fromarray(cv2.cvtColor(segment, cv2.COLOR_BGR2RGB)).save(path)


def process_pdf_decimer(args: argparse.Namespace, pdf: Path) -> list[dict]:
    try:
        from decimer_segmentation import segment_chemical_structures_from_file
    except ImportError as exc:
        raise RuntimeError(
            "DECIMER-Segmentation is not installed in this Python environment."
        ) from exc

    pdf = pdf.expanduser().resolve()
    if not pdf.exists():
        raise FileNotFoundError(pdf)

    pdf_slug = slugify(pdf.stem)
    pdf_out = Path(args.out).resolve() / pdf_slug
    crops_dir = pdf_out / "crops"
    if args.clean:
        shutil.rmtree(crops_dir, ignore_errors=True)
    crops_dir.mkdir(parents=True, exist_ok=True)

    segments = segment_chemical_structures_from_file(
        str(pdf), expand=True, poppler_path=None
    )
    records: list[dict] = []
    for idx, segment in enumerate(segments, start=1):
        crop_id = f"{pdf_slug}_decimer_c{idx:03d}"
        crop_path = crops_dir / f"{crop_id}.png"
        save_decimer_segment(segment, crop_path)
        h, w = segment.shape[:2]
        records.append(
            {
                "id": crop_id,
                "pdf": str(pdf),
                "page": None,
                "source_kind": "decimer",
                "source_image": str(pdf),
                "crop_path": str(crop_path),
                "bbox_xyxy": None,
                "score": 1.0,
                "features": {"width": float(w), "height": float(h)},
            }
        )

    manifest = pdf_out / "manifest.jsonl"
    with manifest.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    make_contact_sheet(records, pdf_out / "contact_sheet.png")
    return records


def source_images(pdf: Path, tmp_dir: Path, render_pages: bool, dpi: int) -> list[tuple[str, Path]]:
    images: list[tuple[str, Path]] = []
    for path in extract_pdf_images(pdf, tmp_dir / "embedded"):
        images.append(("embedded", path))

    if render_pages or not images:
        for path in render_pdf_pages(pdf, tmp_dir / "rendered", dpi=dpi):
            images.append(("rendered", path))

    return images


def process_pdf(args: argparse.Namespace, pdf: Path) -> list[dict]:
    pdf = pdf.expanduser().resolve()
    if not pdf.exists():
        raise FileNotFoundError(pdf)

    pdf_slug = slugify(pdf.stem)
    pdf_out = Path(args.out).resolve() / pdf_slug
    crops_dir = pdf_out / "crops"
    figures_dir = pdf_out / "figures"
    if args.clean:
        shutil.rmtree(crops_dir, ignore_errors=True)
        shutil.rmtree(figures_dir, ignore_errors=True)
    crops_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="chem-structure-extract-") as tmp:
        tmp_dir = Path(tmp)
        (tmp_dir / "embedded").mkdir()
        (tmp_dir / "rendered").mkdir()

        for source_kind, image_path in source_images(
            pdf, tmp_dir, render_pages=args.render_pages, dpi=args.dpi
        ):
            page = parse_page_from_name(image_path)
            rgb = load_rgb(image_path)
            candidates = find_candidates(
                rgb,
                min_score=args.min_score,
                max_candidates=args.max_candidates_per_source,
            )

            figure_name = f"{pdf_slug}_{source_kind}_{image_path.stem}.png"
            figure_out = figures_dir / figure_name
            if args.keep_figures:
                shutil.copyfile(image_path, figure_out)

            for idx, candidate in enumerate(candidates, start=1):
                crop_id = f"{pdf_slug}_p{page or 0:03d}_{source_kind}_{image_path.stem}_c{idx:02d}"
                crop_path = crops_dir / f"{crop_id}.png"
                save_crop(rgb, candidate, crop_path)
                record = {
                    "id": crop_id,
                    "pdf": str(pdf),
                    "page": page,
                    "source_kind": source_kind,
                    "source_image": str(figure_out if args.keep_figures else image_path),
                    "crop_path": str(crop_path),
                    "bbox_xyxy": list(candidate.bbox),
                    "score": round(candidate.score, 4),
                    "features": {
                        key: round(value, 4) for key, value in candidate.features.items()
                    },
                }
                records.append(record)

    manifest = pdf_out / "manifest.jsonl"
    with manifest.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    make_contact_sheet(records, pdf_out / "contact_sheet.png")
    return records


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract likely chemical-structure image crops from PDF figures."
    )
    parser.add_argument("pdfs", nargs="+", help="Input PDF files")
    parser.add_argument(
        "--out",
        default="output/chemical_structure_candidates",
        help="Output directory",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.85,
        help="Candidate threshold; lower values increase recall and false positives.",
    )
    parser.add_argument(
        "--engine",
        choices=("auto", "decimer", "heuristic"),
        default="heuristic",
        help="heuristic is the default; decimer uses DECIMER-Segmentation; auto tries decimer when installed.",
    )
    parser.add_argument(
        "--max-candidates-per-source",
        type=int,
        default=16,
        help="Maximum crops emitted for each embedded figure or rendered page.",
    )
    parser.add_argument(
        "--render-pages",
        action="store_true",
        help="Also render full pages and search them. Useful for scanned/vector PDFs.",
    )
    parser.add_argument("--dpi", type=int, default=300, help="DPI for page rendering")
    parser.add_argument(
        "--keep-figures",
        action="store_true",
        help="Copy source figure/page images into the output directory.",
    )
    parser.add_argument(
        "--no-clean",
        dest="clean",
        action="store_false",
        help="Do not remove stale crops/figures for the current PDF before running.",
    )
    parser.set_defaults(clean=True)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    total = 0
    for pdf_arg in args.pdfs:
        if args.engine in {"auto", "decimer"}:
            try:
                records = process_pdf_decimer(args, Path(pdf_arg))
            except RuntimeError as exc:
                if args.engine == "decimer":
                    raise
                print(f"{pdf_arg}: DECIMER unavailable ({exc}); using heuristic engine")
                records = process_pdf(args, Path(pdf_arg))
        else:
            records = process_pdf(args, Path(pdf_arg))
        total += len(records)
        print(f"{pdf_arg}: {len(records)} candidates")
    print(f"total: {total} candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Tools: PDF Structure Extraction

> Pre-existing tools for converting scientific-paper PDFs into chemical
> structure images and SMILES strings. Used by the `chem.pdf` MCP as the
> back-end for the "PDF → recompute" pipeline.

## Files

| File | Purpose |
|---|---|
| [`extract_chemical_structure_candidates.py`](extract_chemical_structure_candidates.py) | Crop candidate structure images out of a PDF (PyMuPDF + heuristics) |
| [`annotate_pdf_smiles.py`](annotate_pdf_smiles.py) | Run DECIMER on candidates, validate via RDKit, write SMILES annotations back to the PDF |

## Standalone usage

```bash
# Extract candidate images
python tools/pdf-structure-extract/extract_chemical_structure_candidates.py \
    paper.pdf --output-dir ./candidates

# Annotate the PDF with SMILES
python tools/pdf-structure-extract/annotate_pdf_smiles.py \
    paper.pdf --candidates-dir ./candidates --output paper-annotated.pdf
```

## Dependencies

```bash
pip install -e ".[pdf]"
```

This pulls `pymupdf`, `opencv-python`, `pillow`, `decimer`,
`decimer-segmentation`. These are *not* installed by the default chemaster
environment; they're behind the `pdf` extra in `pyproject.toml`.

A separate conda env (`chem-ocr`) with system-level OCR deps may also be
needed for production use:

```bash
conda create -n chem-ocr python=3.10 -y
conda activate chem-ocr
conda install -c conda-forge pymupdf opencv pillow -y
pip install decimer decimer-segmentation
```

## Integration into the agent

`chemaster/mcp/pdf/server.py` is the MCP wrapper. Currently a placeholder;
fleshed out under Phase 5 of the V2 roadmap.

## History

These scripts predate the V2 architecture refactor (the original
ChemMaster repository was a PDF structure-extraction tool that was then
expanded into the agent platform). Migration from `scripts/` to here
happened in P2-9 (V2 housekeeping batch).

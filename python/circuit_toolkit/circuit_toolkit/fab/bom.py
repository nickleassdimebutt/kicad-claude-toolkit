"""BOM generator from a Board (no schematic needed)."""
from __future__ import annotations
import csv
import os
from pathlib import Path
from typing import Dict, List, Tuple

from circuit_toolkit.core.board import Board


def write_bom(board: Board, output_dir: str | Path) -> Tuple[Path, Path]:
    """Write two BOM files:
        bom.csv         — flat per-component list (Reference, Value, Footprint, LCSC, Side)
        bom_jlcpcb.csv  — grouped JLCPCB upload format (Designator, Qty, Comment, Footprint, LCSC)

    Returns (flat_path, jlcpcb_path).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Filter: skip mounting holes (no LCSC, not assembled)
    components = [c for c in board.components if not c.ref.startswith("H")]

    flat_path = output_dir / "bom.csv"
    with open(flat_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Reference", "Value", "Footprint", "LCSC", "Description"])
        for c in sorted(components, key=lambda c: c.ref):
            w.writerow([c.ref, c.value, c.footprint, c.lcsc or "", c.description])

    # Group by (value, footprint, lcsc) for JLC format
    groups: Dict[Tuple[str, str, str], List[str]] = {}
    for c in components:
        key = (c.value, c.footprint, c.lcsc or "")
        groups.setdefault(key, []).append(c.ref)

    jlcpcb_path = output_dir / "bom_jlcpcb.csv"
    with open(jlcpcb_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Qty", "Comment", "Footprint", "LCSC"])
        for (val, fp, lcsc), refs in sorted(groups.items()):
            w.writerow([",".join(sorted(refs)), len(refs), val, fp, lcsc])

    return flat_path, jlcpcb_path

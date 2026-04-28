"""Hierarchical schematic — overview SVG + one detail SVG per block.

Per the IPC convention: each subcircuit lives on its own sheet so a
reviewer can read the design top-down. The overview shows the full
flat schematic; each detail sheet shows only the components tagged
with one ``block_id`` (set automatically by ``block_scope`` in the
block functions).

External nets — ones that connect a block's components to anything
outside that block — appear in the detail SVG with their full name
intact, so the reader can trace continuity across sheets without
manually relabelling.
"""
from __future__ import annotations
import re
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Set

from circuit_toolkit.core.board import Board
from circuit_toolkit.core.net import Net, Pad
from circuit_toolkit.builders.schematic import build_schematic


def _safe_filename(s: str) -> str:
    """Make a block_id safe for use as a filename component."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s)


def _filter_to_block(board: Board, block_id: str) -> Board:
    """Return a new Board containing only components tagged with `block_id`,
    plus all nets that touch them. Net pads belonging to *other* blocks are
    pruned so the renderer doesn't emit dangling pad references."""
    keep_refs: Set[str] = {c.ref for c in board.components if c.block_id == block_id}
    if not keep_refs:
        raise ValueError(f"no components tagged block_id={block_id!r}")

    sub = Board(name=f"{board.name}__{block_id}",
                size=board.size,
                thickness_mm=board.thickness_mm,
                layer_count=board.layer_count)

    # Components: shallow copy so we don't mutate the original
    sub.components = [deepcopy(c) for c in board.components if c.ref in keep_refs]

    # Nets: keep any net that has at least one pad on a kept component;
    # within the kept nets, prune pads to only those on kept components.
    for name, net in board.nets.items():
        kept_pads = [p for p in net.pads if p.component_ref in keep_refs]
        if kept_pads:
            sub.nets[name] = Net(name=name,
                                 pads=[Pad(component_ref=p.component_ref,
                                           pad_number=p.pad_number)
                                       for p in kept_pads],
                                 net_class=net.net_class)
    return sub


def list_blocks(board: Board) -> List[str]:
    """Return unique block_ids present on the board, in first-seen order."""
    seen: List[str] = []
    for c in board.components:
        if c.block_id and c.block_id not in seen:
            seen.append(c.block_id)
    return seen


def build_hierarchical_schematic(board: Board,
                                 output_dir: str | Path,
                                 overview_name: str = "schematic_overview.svg",
                                 detail_prefix: str = "schematic_block_",
                                 netlistsvg_cmd: Optional[str] = None,
                                 node_dir: Optional[str] = None) -> Dict[str, Path]:
    """Generate the overview + per-block detail SVGs.

    Args:
        board: full Board to document.
        output_dir: directory to write SVGs (created if missing).
        overview_name: filename for the full flat schematic (the "overview").
        detail_prefix: filename prefix for per-block detail sheets.
        netlistsvg_cmd, node_dir: forwarded to ``build_schematic``.

    Returns ``{label: Path}`` — keys are ``"overview"`` and each block_id;
    values are the SVG file paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    out: Dict[str, Path] = {}

    overview = output_dir / overview_name
    build_schematic(board, overview,
                    netlistsvg_cmd=netlistsvg_cmd, node_dir=node_dir)
    out["overview"] = overview

    for bid in list_blocks(board):
        sub = _filter_to_block(board, bid)
        path = output_dir / f"{detail_prefix}{_safe_filename(bid)}.svg"
        try:
            build_schematic(sub, path,
                            netlistsvg_cmd=netlistsvg_cmd, node_dir=node_dir)
            out[bid] = path
        except Exception as e:
            # Mounting-hole-only blocks have no electrical connectivity;
            # netlistsvg will refuse to render an empty module. Skip rather
            # than blowing up the whole hierarchy.
            print(f"  [hierarchical] {bid}: skipped ({e.__class__.__name__})")
    return out

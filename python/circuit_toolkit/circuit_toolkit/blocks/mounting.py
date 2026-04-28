"""Mounting hole blocks."""
from __future__ import annotations

from circuit_toolkit.core.board import Board
from circuit_toolkit.core.component import Component


def m2_mounting_hole(board: Board, ref: str) -> Component:
    """M2 NPTH (no plated through-hole) mounting hole, 2.2mm drill, no annular ring."""
    h = Component(
        ref=ref,
        value="MountingHole_M2",
        footprint="MountingHole:MountingHole_2.2mm_M2",
        lcsc=None, lcsc_basic=False,
        pin_map={},
        description="M2 mounting hole, 2.2mm NPTH",
    )
    board.add(h)
    return h


def m3_mounting_hole(board: Board, ref: str) -> Component:
    """M3 NPTH mounting hole, 3.2mm drill."""
    h = Component(
        ref=ref,
        value="MountingHole_M3",
        footprint="MountingHole:MountingHole_3.2mm_M3",
        lcsc=None, lcsc_basic=False,
        pin_map={},
        description="M3 mounting hole, 3.2mm NPTH",
    )
    board.add(h)
    return h

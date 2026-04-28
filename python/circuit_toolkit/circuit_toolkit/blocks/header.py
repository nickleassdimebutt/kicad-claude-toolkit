"""Pin header blocks."""
from __future__ import annotations
from typing import List, Optional

from circuit_toolkit.core.board import Board
from circuit_toolkit.core.component import Component
from circuit_toolkit.core.net import Net
from circuit_toolkit.blocks.scope import block_scope


HEADER_FOOTPRINTS = {
    (1, 2): "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
    (1, 3): "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
    (1, 4): "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
    (1, 5): "Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical",
    (1, 6): "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical",
    (1, 8): "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical",
}


def pin_header(board: Board, ref: str, pins: int,
               nets: List[Net | None],
               label: str = "",
               rows: int = 1) -> Component:
    """Add a 2.54mm-pitch through-hole pin header.

    Args:
        ref: header reference (e.g. "J2")
        pins: number of pins per row
        nets: list of Net objects to connect to each pin (1-indexed). Use None for no-connect.
        label: descriptive label (used as 'Value' field, e.g. "3V3_OUT", "I2C")
        rows: 1 or 2

    Returns the header Component.
    """
    with block_scope(board, "header"):
        if len(nets) != pins:
            raise ValueError(f"Expected {pins} nets, got {len(nets)}")

        fp = HEADER_FOOTPRINTS.get((rows, pins))
        if fp is None:
            raise ValueError(f"No footprint for {rows}×{pins} header")

        h = Component(
            ref=ref,
            value=label or f"Header_{rows}x{pins}",
            footprint=fp,
            lcsc="C124378" if (rows, pins) == (1, 2) else None,
            lcsc_basic=False,
            pin_map={str(i): str(i) for i in range(1, pins * rows + 1)},
            description=f"Pin header {rows}×{pins} 2.54mm",
        )
        board.add(h)
        for i, net in enumerate(nets, start=1):
            if net is not None:
                board.connect(net, h, str(i))
        return h

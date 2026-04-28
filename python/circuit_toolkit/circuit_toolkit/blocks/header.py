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


# JST PH-series 2-pin battery connector — extremely common for single-cell Li-ion.
def jst_ph_battery(board: Board, ref: str = "J2",
                   battery_pos: Optional["Net"] = None,
                   gnd: Optional["Net"] = None) -> Component:
    """JST PH 2.0 mm 2-pin vertical socket — pin 1 = +, pin 2 = GND."""
    with block_scope(board, "battery_connector"):
        if battery_pos is None: battery_pos = board.net("BAT")
        if gnd is None:         gnd = board.net("GND")
        c = Component(
            ref=ref,
            value="JST_PH_2P",
            footprint="Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical",
            lcsc="C145867", lcsc_basic=False,
            pin_map={"1": "1", "2": "2"},
            description="JST PH 2-pin vertical battery connector",
        )
        board.add(c)
        board.connect(battery_pos, c, "1")
        board.connect(gnd,         c, "2")
        return c

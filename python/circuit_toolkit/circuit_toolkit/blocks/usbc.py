"""USB-C connector blocks."""
from __future__ import annotations
from typing import Tuple

from circuit_toolkit.core.board import Board
from circuit_toolkit.core.component import Component
from circuit_toolkit.core.net import Net
from circuit_toolkit.blocks.scope import block_scope


# HRO TYPE-C-31-M-12 (12-pin USB-C receptacle, common JLC stock)
HRO_TYPE_C_31_M_12_PIN_MAP = {
    # Logical name → pad number
    "GND_A1":  "A1",
    "VBUS_A4": "A4",
    "CC1":     "A5",
    "DP_A6":   "A6",
    "DN_A7":   "A7",
    "SBU1":    "A8",
    "VBUS_A9": "A9",
    "GND_A12": "A12",

    "GND_B1":  "B1",
    "VBUS_B4": "B4",
    "CC2":     "B5",
    "DP_B6":   "B6",
    "DN_B7":   "B7",
    "SBU2":    "B8",
    "VBUS_B9": "B9",
    "GND_B12": "B12",

    # Shield PTH pins — pad numbering differs across KiCad library versions:
    # KiCad 10 numbers all four shield holes "SH", KiCad 9 uses "S1". The
    # pipe alias makes the toolkit accept either; whichever exists on the
    # loaded footprint wins.
    "SHIELD": "SH|S1",
}


def usbc_power(board: Board, ref: str = "J1",
               cc_pulldowns: str = "5.1k",
               cc_resistor_ref_prefix: str = "R") -> Tuple[Net, Net, Net, Net]:
    """USB-C power-only receptacle with CC pulldowns for 5V sink role.

    Adds:
      - 1× HRO TYPE-C-31-M-12 footprint
      - 2× 5.1kΩ resistors (CC1→GND, CC2→GND) for USB-PD sink advertise

    Returns (vbus, gnd, cc1, cc2) nets.
    """
    with block_scope(board, "usbc_power"):
        j = Component(
            ref=ref,
            value="HRO TYPE-C-31-M-12",
            footprint="Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
            lcsc="C165948",
            lcsc_basic=False,
            pin_map=HRO_TYPE_C_31_M_12_PIN_MAP,
            description="USB-C receptacle, 12-pin, USB 2.0 + PD",
        )
        board.add(j)

        vbus = board.net("VBUS")
        gnd  = board.net("GND")
        cc1  = board.net("CC1")
        cc2  = board.net("CC2")

        # Power pins
        for pad in ("A4", "A9", "B4", "B9"):
            vbus.add(ref, pad)
        for pad in ("A1", "A12", "B1", "B12"):
            gnd.add(ref, pad)
        # Shield pins to GND — KiCad 10 names them "SH", KiCad 9 names them
        # "S1"; the pipe alias is resolved by build_pcb against whichever
        # pads the loaded footprint actually exposes.
        gnd.add(ref, "SH|S1")
        # Data lines & SBU pins → GND for power-only mode (D+/D−/SBU not used)
        for pad in ("A6", "A7", "A8", "B6", "B7", "B8"):
            gnd.add(ref, pad)

        # CC pins
        cc1.add(ref, "A5")
        cc2.add(ref, "B5")

        # CC pulldown resistors (5.1k = 5V/3A advertise; 1.5k = 9V; 10k = 15V; 5.1k+5.1k = 5V/3A)
        used = {c.ref for c in board.components if c.ref.startswith(cc_resistor_ref_prefix)}
        next_idx = 1
        for net in (cc1, cc2):
            while f"{cc_resistor_ref_prefix}{next_idx}" in used:
                next_idx += 1
            rref = f"{cc_resistor_ref_prefix}{next_idx}"
            used.add(rref)
            next_idx += 1

            r = Component(
                ref=rref,
                value=cc_pulldowns,
                footprint="Resistor_SMD:R_0402_1005Metric",
                lcsc="C25905" if cc_pulldowns == "5.1k" else None,
                lcsc_basic=cc_pulldowns == "5.1k",
                pin_map={"1": "1", "2": "2"},
                description=f"Resistor {cc_pulldowns} 0402",
            )
            board.add(r)
            net.add(rref, "1")
            gnd.add(rref, "2")

        return vbus, gnd, cc1, cc2

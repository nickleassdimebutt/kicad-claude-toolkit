"""LDO regulator blocks."""
from __future__ import annotations
from typing import List, Optional

from circuit_toolkit.core.board import Board
from circuit_toolkit.core.component import Component
from circuit_toolkit.core.net import Net
from circuit_toolkit.blocks.decoupling import add_cap
from circuit_toolkit.blocks.scope import block_scope


AMS1117_LCSC = {
    3.3: ("C6186",  True),    # AMS1117-3.3, basic part
    5.0: ("C6187",  True),    # AMS1117-5.0
    1.8: ("C475492", False),  # AMS1117-1.8
    2.5: ("C6321",  False),
}


def ams1117_ldo(board: Board, ref: str,
                vin: Net, gnd: Net,
                output_voltage: float = 3.3,
                in_caps: Optional[List[str]] = None,
                out_caps: Optional[List[str]] = None,
                vout_net_name: Optional[str] = None,
                cap_ref_prefix: str = "C") -> Net:
    """AMS1117-style LDO with input + output bypass caps.

    Args:
        ref: regulator reference designator (e.g. "U1")
        vin: input net (typically VBUS or 5V)
        gnd: ground net
        output_voltage: 3.3, 5.0, 1.8, 2.5
        in_caps: list of 'value/package' specs for input caps (e.g. ["10uF/0805"])
        out_caps: list for output caps (e.g. ["10uF/0805", "100nF/0402"])
        vout_net_name: name for output net (default: "+{voltage}V")

    Returns the output net.
    """
    with block_scope(board, "ldo"):
        if in_caps is None:
            in_caps = ["10uF/0805"]
        if out_caps is None:
            out_caps = ["10uF/0805", "100nF/0402"]

        if output_voltage not in AMS1117_LCSC:
            raise ValueError(f"No AMS1117 variant for {output_voltage}V")
        lcsc, basic = AMS1117_LCSC[output_voltage]

        # Net naming: +3V3, +5V, +1V8, etc.
        if vout_net_name is None:
            if output_voltage == int(output_voltage):
                vout_net_name = f"+{int(output_voltage)}V"
            else:
                vout_net_name = f"+{str(output_voltage).replace('.', 'V')}"
        vout = board.net(vout_net_name)

        # AMS1117 SOT-223: pin1=GND, pin2=VOUT (also tab), pin3=VIN
        u = Component(
            ref=ref,
            value=f"AMS1117-{output_voltage}",
            footprint="Package_TO_SOT_SMD:SOT-223-3_TabPin2",
            lcsc=lcsc, lcsc_basic=basic,
            pin_map={"GND": "1", "VOUT": "2", "VIN": "3", "TAB": "2"},
            description=f"AMS1117 {output_voltage}V LDO regulator",
        )
        board.add(u)
        board.connect(gnd,  u, "GND")
        board.connect(vout, u, "VOUT")
        board.connect(vin,  u, "VIN")

        # Find next available cap ref
        used = {c.ref for c in board.components if c.ref.startswith(cap_ref_prefix)}
        next_idx = 1

        def _next_ref():
            nonlocal next_idx
            while f"{cap_ref_prefix}{next_idx}" in used:
                next_idx += 1
            r = f"{cap_ref_prefix}{next_idx}"
            used.add(r)
            next_idx += 1
            return r

        for spec in in_caps:
            add_cap(board, _next_ref(), spec, vin, gnd)
        for spec in out_caps:
            add_cap(board, _next_ref(), spec, vout, gnd)

        return vout

"""Decoupling cap helper — adds an SMD capacitor between two nets."""
from __future__ import annotations
from typing import Optional, Tuple

from circuit_toolkit.core.board import Board
from circuit_toolkit.core.component import Component
from circuit_toolkit.core.net import Net


# Standard SMD cap LCSC numbers (JLC basic parts where possible)
CAP_LCSC = {
    ("100nF", "0402"): ("C1525", True),
    ("100nF", "0805"): ("C49678", True),
    ("1uF",   "0402"): ("C52923", True),
    ("1uF",   "0805"): ("C28323", True),
    ("10uF",  "0805"): ("C15850", True),    # 10V rated
    ("10uF",  "1206"): ("C13585", True),
    ("22uF",  "0805"): ("C45783", True),
}

FOOTPRINT_BY_PACKAGE = {
    "0402": "Capacitor_SMD:C_0402_1005Metric",
    "0603": "Capacitor_SMD:C_0603_1608Metric",
    "0805": "Capacitor_SMD:C_0805_2012Metric",
    "1206": "Capacitor_SMD:C_1206_3216Metric",
}


def _parse_value_pkg(spec: str) -> Tuple[str, str]:
    """Parse '10uF/0805' or '100nF/0402' → ('10uF', '0805')."""
    if "/" not in spec:
        raise ValueError(f"Cap spec must be 'value/package', got {spec!r}")
    value, pkg = spec.split("/", 1)
    return value.strip(), pkg.strip()


def add_cap(board: Board, ref: str, spec: str,
            net_a: Net, net_b: Net, pad_a: int = 1, pad_b: int = 2) -> Component:
    """Add a single SMD capacitor between two nets.

    spec: 'value/package' e.g. '10uF/0805' or '100nF/0402'
    net_a connects to pad 1 by default; net_b to pad 2.
    """
    value, pkg = _parse_value_pkg(spec)
    fp = FOOTPRINT_BY_PACKAGE.get(pkg)
    if fp is None:
        raise ValueError(f"Unknown cap package {pkg!r}")
    lcsc_info = CAP_LCSC.get((value, pkg))
    lcsc, basic = lcsc_info if lcsc_info else (None, False)

    cap = Component(
        ref=ref, value=value, footprint=fp,
        lcsc=lcsc, lcsc_basic=basic,
        pin_map={"1": "1", "2": "2"},
        description=f"Capacitor {value} {pkg}",
    )
    board.add(cap)
    board.connect(net_a, cap, str(pad_a))
    board.connect(net_b, cap, str(pad_b))
    return cap


def decoupling(board: Board, vcc: Net, gnd: Net,
               specs: list[str], ref_prefix: str = "C") -> list[Component]:
    """Add decoupling caps between vcc and gnd.

    `specs` is a list of 'value/package' strings, one per cap.
    Refs are auto-numbered using the next available index in ref_prefix.
    """
    used = {c.ref for c in board.components if c.ref.startswith(ref_prefix)}
    next_idx = 1
    caps = []
    for spec in specs:
        while f"{ref_prefix}{next_idx}" in used:
            next_idx += 1
        ref = f"{ref_prefix}{next_idx}"
        used.add(ref)
        caps.append(add_cap(board, ref, spec, vcc, gnd))
        next_idx += 1
    return caps

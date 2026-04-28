"""Component — wraps a footprint reference with metadata for BOM, ERC, and PCB build."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class Component:
    """A single physical component on the board.

    `footprint` is a KiCad library reference: "Library:FootprintName".
    `pin_map` maps logical pin names ("VIN", "GND") to pad numbers ("3", "1").
    `lcsc` is the LCSC part number for JLCPCB BOM/PCBA.
    `block_id` is the optional sub-circuit name this component belongs to —
    used by the hierarchical schematic builder to partition the board into
    per-block detail sheets. Set automatically by ``block_scope`` (see
    ``circuit_toolkit.blocks.scope``); leave unset for top-level glue parts.
    """
    ref: str                        # "U1", "R1", "C1", ...
    value: str                      # "AMS1117-3.3", "5.1k", "10uF"
    footprint: str                  # "Package_TO_SOT_SMD:SOT-223-3_TabPin2"
    lcsc: Optional[str] = None      # "C6186"
    lcsc_basic: bool = False        # JLC basic part flag
    pin_map: Dict[str, str] = field(default_factory=dict)
    description: str = ""
    do_not_populate: bool = False
    block_id: Optional[str] = None  # sub-circuit tag for hierarchical schematics

    def pin(self, name: str) -> str:
        """Resolve a logical pin name to its pad number."""
        if name in self.pin_map:
            return self.pin_map[name]
        # Allow numeric pin lookup directly
        if name.isdigit() or (name and name[0].isdigit()):
            return name
        raise KeyError(
            f"Component {self.ref} ({self.value}) has no pin {name!r}. "
            f"Known pins: {sorted(self.pin_map.keys())}"
        )

    def __repr__(self) -> str:
        return f"Component({self.ref}, {self.value}, {self.footprint})"

"""Net class — wraps a logical electrical connection.

Topology-only. Owns no position/layer info.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from circuit_toolkit.core.component import Component


@dataclass
class Pad:
    """A reference to a single pad on a component (component_ref, pad_number)."""
    component_ref: str
    pad_number: str

    def __repr__(self) -> str:
        return f"{self.component_ref}.{self.pad_number}"


@dataclass
class Net:
    """A named electrical net.

    Holds the list of (component_ref, pad_number) pairs that share this net.
    The Board owns the master list of nets; Components hold references back to nets.
    """
    name: str
    pads: List[Pad] = field(default_factory=list)
    # Net class for design rules: e.g. "power", "signal", "high_speed"
    net_class: str = "default"

    def add(self, component_ref: str, pad_number: str | int) -> None:
        self.pads.append(Pad(component_ref=component_ref, pad_number=str(pad_number)))

    def __repr__(self) -> str:
        return f"Net({self.name!r}, {len(self.pads)} pads)"

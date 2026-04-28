"""Board — top-level container for a circuit + its physical footprints + nets."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

from circuit_toolkit.core.component import Component
from circuit_toolkit.core.net import Net


@dataclass
class Board:
    """A board is a collection of components + nets + size + metadata.

    Topology-only at this level. Physical positions live in a separate `layout`
    dict that is passed to builders.
    """
    name: str
    size: Tuple[float, float] = (50.0, 50.0)   # mm (width, height)
    thickness_mm: float = 1.6
    layer_count: int = 2

    components: List[Component] = field(default_factory=list)
    nets: Dict[str, Net] = field(default_factory=dict)

    def add(self, component: Component) -> Component:
        """Add a component to the board. Returns the component for chaining."""
        if any(c.ref == component.ref for c in self.components):
            raise ValueError(f"Duplicate reference designator: {component.ref}")
        self.components.append(component)
        return component

    def net(self, name: str) -> Net:
        """Get or create a net by name."""
        if name not in self.nets:
            self.nets[name] = Net(name=name)
        return self.nets[name]

    def connect(self, net: Net | str, component: Component, pin: str) -> None:
        """Connect a component pin to a net.

        Accepts either a Net object or a net name (will create if missing).
        Pin can be a logical name (resolved via pin_map) or a pad number.
        """
        if isinstance(net, str):
            net = self.net(net)
        pad_num = component.pin(pin)
        net.add(component.ref, pad_num)

    def find_ref(self, ref: str) -> Optional[Component]:
        for c in self.components:
            if c.ref == ref:
                return c
        return None

    def smd_components(self) -> List[Component]:
        """Components that need pick-and-place (excludes mounting holes, NPTH-only)."""
        return [c for c in self.components if not c.ref.startswith("H")]

    def __repr__(self) -> str:
        return (
            f"Board({self.name!r}, size={self.size}, "
            f"{len(self.components)} components, {len(self.nets)} nets)"
        )

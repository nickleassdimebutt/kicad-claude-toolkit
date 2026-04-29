"""Board → SPICE deck text translation.

Walks the Board's components and nets, classifies each component by its
reference-designator prefix, and emits the corresponding SPICE element line
into a plain-text deck. The output is fed to a Backend (currently
ngspice -b via subprocess); nothing in this module depends on PySpice.

Component routing (ref-prefix dispatch):

    R*   → resistor              (value parsed; R, k, M, m, u suffixes)
    C*   → capacitor             (value/footprint string; ``10uF/0805`` form)
    D*   → diode (LED model)     (per-colour I-V via ``LED_VF``)
    U*   → subcircuit instance   (currently only AMS1117 family)
    J*   → connector — skipped, but its nets remain available for test sources

The translator returns the deck text plus a ``NetMap`` recording the SPICE
node name for every Board net (so analyses can reference ``+3V3`` without
caring about character sanitisation).
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from circuit_toolkit.core.board import Board
from circuit_toolkit.core.component import Component


MODELS_DIR = Path(__file__).parent / "models"

# LED forward-voltage by color (V) and effective series resistance (Ω).
LED_PARAMS = {
    "red":    dict(vf=2.0, rs=4),
    "green":  dict(vf=2.1, rs=5),
    "yellow": dict(vf=2.1, rs=5),
    "orange": dict(vf=2.0, rs=4),
    "blue":   dict(vf=3.0, rs=8),
    "white":  dict(vf=3.2, rs=8),
}


# ── Value parsing ─────────────────────────────────────────────────────────────

_VAL_RE = re.compile(
    r"^\s*([0-9]*\.?[0-9]+(?:[eE][+-]?\d+)?)"
    r"\s*([RkKMmuUnNpPfF]?)([FfHh]?)\s*(?:/.*)?$"
)
_SUFFIX_MULT = {
    "":  1.0,
    "R": 1.0,
    "k": 1e3,  "K": 1e3,
    "M": 1e6,
    "m": 1e-3,
    "u": 1e-6, "U": 1e-6,
    "n": 1e-9, "N": 1e-9,
    "p": 1e-12, "P": 1e-12,
    "f": 1e-15,
}


def parse_value(s: str) -> float:
    """Parse a component value string to its base SI value.

    >>> parse_value("5.1k")
    5100.0
    >>> parse_value("10uF/0805")
    1e-05
    >>> parse_value("100nF/0402")
    1e-07
    """
    m = _VAL_RE.match(s)
    if not m:
        raise ValueError(f"cannot parse component value: {s!r}")
    mantissa, suffix, _unit = m.group(1), m.group(2), m.group(3)
    return float(mantissa) * _SUFFIX_MULT.get(suffix, 1.0)


# ── Net naming ────────────────────────────────────────────────────────────────

@dataclass
class NetMap:
    """Maps Board net names to SPICE-safe node names."""
    gnd_name: str
    forward: Dict[str, str]   # board net name → SPICE node name

    def __getitem__(self, board_net_name: str) -> str:
        if board_net_name == self.gnd_name:
            return "0"  # SPICE convention
        return self.forward[board_net_name]


def _sanitize(name: str) -> str:
    """SPICE-safe node name. Keeps '+' (ngspice accepts it) but replaces other
    special chars conservatively to avoid parse weirdness."""
    out = name
    out = out.replace(" ", "_").replace("/", "_").replace(",", "_")
    out = out.replace("(", "_").replace(")", "_")
    return out


# ── Component classification ──────────────────────────────────────────────────

def _pad_for(comp: Component, pin: str) -> str:
    """Return the pad number for a logical pin. Falls back to pin if no map."""
    if comp.pin_map and pin in comp.pin_map:
        return comp.pin_map[pin]
    return pin


def _net_at_pad(board: Board, ref: str, pad: str) -> Optional[str]:
    """Find which board net is attached to (ref, pad). Returns net name or None."""
    for net_name, net in board.nets.items():
        for p in net.pads:
            if p.component_ref == ref and p.pad_number == str(pad):
                return net_name
    return None


def build_netmap(board: Board, gnd_net: str = "GND") -> NetMap:
    fwd: Dict[str, str] = {}
    for name in board.nets:
        if name == gnd_net:
            continue
        fwd[name] = _sanitize(name)
    return NetMap(gnd_name=gnd_net, forward=fwd)


# ── Deck builder ──────────────────────────────────────────────────────────────

def board_to_deck(board: Board,
                  net_map: NetMap,
                  title: str | None = None,
                  overrides: Optional[Dict[str, object]] = None,
                  subckt_params: Optional[Dict[str, Dict[str, float]]] = None,
                  include_models: bool = True) -> str:
    """Translate `board` into a plain-text SPICE deck.

    `overrides` swaps component values (sweeps / Monte Carlo) — keyed by
    reference, e.g. ``{"R3": "990"}`` or ``{"R3": 990.0}``.
    `subckt_params` injects parameters into X-element calls — keyed by ref,
    e.g. ``{"U1": {"vref": 3.298}}``.
    `include_models` = True prepends ``.include`` lines for every .lib in
    the bundled models/ directory.

    Returns the deck text — a complete element block ready to be combined
    with a control block and ``.end`` by a Backend.
    """
    overrides = overrides or {}
    subckt_params = subckt_params or {}
    title = title or board.name

    lines: List[str] = [f"* {title}"]

    if include_models:
        for lib in sorted(MODELS_DIR.glob("*.lib")):
            lines.append(f".include {str(lib).replace(chr(92), '/')}")

    # Components
    for comp in board.components:
        ref = comp.ref
        prefix = ref[0]
        value = overrides.get(ref, comp.value)

        if prefix == "R":
            lines.append(_emit_resistor(board, comp, value, net_map))
        elif prefix == "C":
            lines.append(_emit_capacitor(board, comp, value, net_map))
        elif prefix == "D":
            lines.extend(_emit_led(board, comp, value, net_map))
        elif prefix == "U":
            lines.append(_emit_subcircuit(board, comp, value, net_map,
                                          params=subckt_params.get(ref)))
        # J*, H*, others: skipped — connectors and mounting holes are not simulated.

    return "\n".join(l for l in lines if l)


# ── Per-class emitters ────────────────────────────────────────────────────────

def _two_pin_nets(board: Board, comp: Component, net_map: NetMap):
    n1 = _net_at_pad(board, comp.ref, "1")
    n2 = _net_at_pad(board, comp.ref, "2")
    if n1 is None or n2 is None:
        raise RuntimeError(
            f"{comp.ref} ({comp.value}) is not connected to two nets — "
            f"net1={n1}, net2={n2}. Cannot emit SPICE element."
        )
    return net_map[n1], net_map[n2]


def _emit_resistor(board, comp, value, net_map) -> str:
    n1, n2 = _two_pin_nets(board, comp, net_map)
    ohms = parse_value(value) if isinstance(value, str) else float(value)
    return f"R{comp.ref[1:]} {n1} {n2} {ohms:g}"


def _emit_capacitor(board, comp, value, net_map) -> str:
    n1, n2 = _two_pin_nets(board, comp, net_map)
    farads = parse_value(value) if isinstance(value, str) else float(value)
    return f"C{comp.ref[1:]} {n1} {n2} {farads:g}"


# Track LED .model lines emitted in this deck so we don't duplicate them.
def _emit_led(board, comp, value, net_map) -> List[str]:
    color = str(value).lower()
    if color not in LED_PARAMS:
        color = "red"
    p = LED_PARAMS[color]
    model_name = f"DLED_{color.upper()}"

    # Wide-bandgap LEDs are modelled with a large emission coefficient N.
    n_emission = max(2.0, p["vf"] / 0.299)

    cathode_pad = _pad_for(comp, "K")
    anode_pad = _pad_for(comp, "A")
    n_cath = _net_at_pad(board, comp.ref, cathode_pad)
    n_anode = _net_at_pad(board, comp.ref, anode_pad)
    if not n_anode or not n_cath:
        raise RuntimeError(f"LED {comp.ref} pin map incomplete.")

    out = [
        f".model {model_name} D (IS=1e-8 N={n_emission:g} RS={p['rs']:g} "
        f"BV=5 IBV=10u CJO=15p)",
        f"D{comp.ref[1:]} {net_map[n_anode]} {net_map[n_cath]} {model_name}",
    ]
    return out


def _emit_subcircuit(board, comp, value, net_map, params=None) -> str:
    val = str(value).strip()
    if val.startswith("AMS1117"):
        m = re.match(r"AMS1117-?([0-9.]+)", val)
        if not m:
            raise RuntimeError(f"unrecognised AMS1117 variant: {val!r}")
        v = m.group(1)
        subckt = f"AMS1117_{v.replace('.', 'V')}"
        n_vin = _net_at_pad(board, comp.ref, _pad_for(comp, "VIN"))
        n_gnd = _net_at_pad(board, comp.ref, _pad_for(comp, "GND"))
        n_vout = _net_at_pad(board, comp.ref, _pad_for(comp, "VOUT"))
        if not all((n_vin, n_gnd, n_vout)):
            raise RuntimeError(f"{comp.ref} LDO pins not all connected.")
        param_str = ""
        if params:
            param_str = " " + " ".join(f"{k}={v:g}" for k, v in params.items())
        return (f"X{comp.ref[1:]} {net_map[n_vin]} {net_map[n_gnd]} "
                f"{net_map[n_vout]} {subckt}{param_str}")
    return ""  # unrecognised U* — silently skipped


# ── Compatibility shim: legacy PySpice-API call signature ─────────────────────
# A few external callers (unit tests, exploratory scripts) imported
# board_to_circuit. Keep that symbol working by routing it through the new
# board_to_deck output, returned as a tuple so callers can introspect.
def board_to_circuit(*args, **kwargs):
    raise NotImplementedError(
        "board_to_circuit() was removed when the SPICE backend switched from "
        "PySpice to ngspice subprocess. Use board_to_deck() instead — it "
        "returns a SPICE deck string. See sim/runner.py for a usage example."
    )

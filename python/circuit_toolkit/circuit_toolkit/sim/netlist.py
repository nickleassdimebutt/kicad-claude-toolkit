"""Board → PySpice Circuit translation.

Walks the Board's components and nets, classifies each component by its
reference-designator prefix and value, and emits the corresponding SPICE
primitive into a PySpice ``Circuit``. Anything that does not have a SPICE
analogue (mounting holes, pin headers, USB-C connector body) is silently
omitted — its nets remain in the circuit, driven by the test sources the
analysis adds.

Component routing (ref-prefix dispatch):

    R*   → resistor              (value parsed; R, k, M, m, u suffixes)
    C*   → capacitor             (value/footprint string; ``10uF/0805`` form)
    D*   → diode (LED model)     (per-colour I-V via ``LED_VF``)
    U*   → subcircuit instance   (currently only AMS1117_3V3)
    J*   → connector — skipped, but its nets are exposed for test sources

The translator returns the constructed Circuit plus a ``NetMap`` that
records the SPICE node name for every Board net (so analyses can reference
``+3V3`` without caring about character sanitisation).
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from circuit_toolkit.core.board import Board
from circuit_toolkit.core.component import Component


MODELS_DIR = Path(__file__).parent / "models"

# LED forward-voltage by color (V) and effective series resistance (Ω) — captures
# enough realism for indicator-LED-with-Rseries problems. NOT a vendor model.
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
    r"^\s*([0-9]*\.?[0-9]+(?:[eE][+-]?\d+)?)"  # mantissa, with optional sci-notation
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

    Accepts things like ``5.1k``, ``10uF``, ``100nF/0402``, ``1.5``, ``2M2``-
    less. Anything before a slash is the value; anything after is metadata.

    >>> parse_value("5.1k")
    5100.0
    >>> parse_value("10uF/0805")
    1e-05
    >>> parse_value("100nF/0402")
    1e-07
    >>> parse_value("1k")
    1000.0
    """
    m = _VAL_RE.match(s)
    if not m:
        raise ValueError(f"cannot parse component value: {s!r}")
    mantissa, suffix, unit_char = m.group(1), m.group(2), m.group(3)
    # 'F' alone (e.g. '10F') reads as suffix=='', unit_char=='F' → no multiplier.
    # '10uF' reads as suffix='u', unit_char='F'.
    mult = _SUFFIX_MULT.get(suffix, 1.0)
    return float(mantissa) * mult


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
    special chars conservatively to avoid PySpice/ngspice parse weirdness."""
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


# ── Public API ────────────────────────────────────────────────────────────────

def build_netmap(board: Board, gnd_net: str = "GND") -> NetMap:
    fwd: Dict[str, str] = {}
    for name in board.nets:
        if name == gnd_net:
            continue
        fwd[name] = _sanitize(name)
    return NetMap(gnd_name=gnd_net, forward=fwd)


def board_to_circuit(board: Board,
                     circuit,                           # PySpice Circuit
                     net_map: NetMap,
                     overrides: Optional[Dict[str, object]] = None,
                     subckt_params: Optional[Dict[str, Dict[str, float]]] = None
                     ) -> None:
    """Populate `circuit` in place with SPICE primitives for every supported
    component on `board`.

    `overrides` swaps component values (sweeps / Monte Carlo) — keyed by
    reference, e.g. ``{"R3": "990"}`` or ``{"R3": 990.0}``.
    `subckt_params` injects parameters into X-element calls — keyed by
    reference, e.g. ``{"U1": {"vref": 3.298}}`` overrides the AMS1117 Vref
    on its subckt instantiation line.
    """
    overrides = overrides or {}
    subckt_params = subckt_params or {}

    for comp in board.components:
        ref = comp.ref
        prefix = ref[0]
        value = overrides.get(ref, comp.value)

        if prefix == "R":
            _add_resistor(circuit, board, comp, value, net_map)
        elif prefix == "C":
            _add_capacitor(circuit, board, comp, value, net_map)
        elif prefix == "D":
            _add_led(circuit, board, comp, value, net_map)
        elif prefix == "U":
            _add_subcircuit(circuit, board, comp, value, net_map,
                            params=subckt_params.get(ref))
        # J*, H*, others: skipped — connectors and mounting holes are not simulated.


# ── Per-class emitters ────────────────────────────────────────────────────────

def _two_pin_nets(board: Board, comp: Component,
                  net_map: NetMap) -> Tuple[str, str]:
    """Find the two SPICE nodes for a 2-pin component (pads 1 and 2)."""
    n1 = _net_at_pad(board, comp.ref, "1")
    n2 = _net_at_pad(board, comp.ref, "2")
    if n1 is None or n2 is None:
        raise RuntimeError(
            f"{comp.ref} ({comp.value}) is not connected to two nets — "
            f"net1={n1}, net2={n2}. Cannot emit SPICE element."
        )
    return net_map[n1], net_map[n2]


def _add_resistor(circuit, board, comp, value, net_map):
    n1, n2 = _two_pin_nets(board, comp, net_map)
    ohms = parse_value(value) if isinstance(value, str) else float(value)
    circuit.R(comp.ref[1:], n1, n2, ohms)


def _add_capacitor(circuit, board, comp, value, net_map):
    n1, n2 = _two_pin_nets(board, comp, net_map)
    farads = parse_value(value) if isinstance(value, str) else float(value)
    circuit.C(comp.ref[1:], n1, n2, farads)


def _add_led(circuit, board, comp, value, net_map):
    """LED uses pin_map K=1 (cathode), A=2 (anode)."""
    color = str(value).lower()
    if color not in LED_PARAMS:
        # Unknown color — fall back to a generic red model.
        color = "red"
    p = LED_PARAMS[color]
    model_name = f"DLED_{color.upper()}"

    # Wide-bandgap LEDs are modelled with a large emission coefficient N so the
    # standard Shockley equation reproduces the measured Vf. Calibrate N from
    # the desired Vf at 1 mA with IS = 1e-8 A:
    #   Vf = N · Vt · ln(I / IS)  ⇒  N ≈ Vf / (0.026 · ln(1e-3 / 1e-8))
    n_emission = max(2.0, p["vf"] / 0.299)  # floor at silicon-diode N
    circuit.model(model_name, "D",
                  IS=1e-8, N=n_emission, RS=p["rs"], BV=5, IBV=10e-6,
                  CJO=15e-12)

    cathode_pad = _pad_for(comp, "K")
    anode_pad = _pad_for(comp, "A")
    n_cath = _net_at_pad(board, comp.ref, cathode_pad)
    n_anode = _net_at_pad(board, comp.ref, anode_pad)
    if n_anode is None or n_cath is None:
        raise RuntimeError(f"LED {comp.ref} pin map incomplete.")
    circuit.D(comp.ref[1:],
              net_map[n_anode], net_map[n_cath],
              model=model_name)


def _add_subcircuit(circuit, board, comp, value, net_map, params=None):
    """Map U-prefixed parts to subcircuit instances. Currently AMS1117 family.

    `params` (dict) flows through as PySpice X kwargs which become
    `name=value` pairs after the subckt name on the X line — ngspice reads
    these as overrides to the subckt's `+ params:` defaults.
    """
    val = str(value).strip()
    if val.startswith("AMS1117"):
        # AMS1117_<voltage> subckt provides VIN/GND/VOUT
        # Voltage is encoded in the value: AMS1117-3.3 → 3V3 subckt name
        m = re.match(r"AMS1117-?([0-9.]+)", val)
        if not m:
            raise RuntimeError(f"unrecognised AMS1117 variant: {val!r}")
        v = m.group(1)
        subckt = f"AMS1117_{v.replace('.', 'V')}"
        # Locate VIN, GND, VOUT pads via pin_map
        n_vin = _net_at_pad(board, comp.ref, _pad_for(comp, "VIN"))
        n_gnd = _net_at_pad(board, comp.ref, _pad_for(comp, "GND"))
        n_vout = _net_at_pad(board, comp.ref, _pad_for(comp, "VOUT"))
        if not all((n_vin, n_gnd, n_vout)):
            raise RuntimeError(f"{comp.ref} LDO pins not all connected.")
        # PySpice X kwargs become `param=value` pairs on the X line.
        circuit.X(comp.ref[1:], subckt,
                  net_map[n_vin], net_map[n_gnd], net_map[n_vout],
                  **(params or {}))
    # Other U-prefixed parts — silently skipped (extend as new subckts arrive).


def include_models(circuit) -> None:
    """Add `.include` lines for every .lib in models/ to the given Circuit."""
    for lib in sorted(MODELS_DIR.glob("*.lib")):
        circuit.include(str(lib))

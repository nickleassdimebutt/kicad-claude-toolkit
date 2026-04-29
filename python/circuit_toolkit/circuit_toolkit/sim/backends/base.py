"""Backend interface — what every SPICE simulator implementation must look like.

The runner builds a SPICE deck (element block) plus a list of control commands
(``op``, ``tran 10us 10ms``, ``dc Vsrc 0 5 .1``) and asks a Backend to run it.
The Backend takes care of: wrapping in ``.control``/``.endc``, invoking the
underlying simulator, parsing its output, and returning a uniform ``SimResult``.

Adding a new simulator (Qucs-S, XYCE, ADS, …) means writing one new module
that implements ``Backend.run``. The runner and analyses code stays identical.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol

import numpy as np


@dataclass
class SimResult:
    """Uniform result object returned by every Backend.

    - ``sweep`` is the independent axis for transient (time, seconds) or DC
      (sweep variable, volts/amps). ``None`` for operating-point.
    - ``traces`` maps node/variable name (lower-case, ``v(<net>)`` form for
      voltages, ``i(<element>)`` for currents) to a 1-D array of values aligned
      with ``sweep``. Op-point traces are length-1 arrays.
    - ``raw`` keeps the raw simulator output for debugging when the parser
      misses something — never the canonical interface, just an escape hatch.
    """
    sweep: Optional[np.ndarray] = None
    traces: Dict[str, np.ndarray] = field(default_factory=dict)
    raw: str = ""

    def get(self, name: str) -> np.ndarray:
        """Look up a trace, accepting both ``"+3V3"`` and ``"v(+3v3)"`` styles."""
        n = name.lower()
        # Direct hit
        if n in self.traces:
            return self.traces[n]
        # Try with v() wrapper
        if f"v({n})" in self.traces:
            return self.traces[f"v({n})"]
        # Try without v() wrapper
        if n.startswith("v(") and n.endswith(")"):
            inner = n[2:-1]
            if inner in self.traces:
                return self.traces[inner]
        raise KeyError(
            f"trace {name!r} not in result; available: {sorted(self.traces.keys())}"
        )

    def op_value(self, name: str) -> float:
        """Convenience for operating-point single-value lookup."""
        arr = self.get(name)
        if len(arr) == 0:
            raise ValueError(f"trace {name!r} is empty")
        return float(arr[0])


class Backend(Protocol):
    """SPICE simulator interface.

    Implementations: ``circuit_toolkit.sim.backends.ngspice.NgSpiceBackend``.
    Future: ``QucsBackend``, ``XYCEBackend``, ``ADSBackend`` for harmonic-balance
    workflows.
    """

    def run(self, deck: str, control: List[str],
            temperature_c: float = 27.0) -> SimResult:
        """Run a deck + control commands and return parsed results.

        Args:
            deck: the element/model/include block — everything *before* the
                  ``.control`` section. Includes title line, R/C/L/D/V/I/X
                  elements, ``.model`` definitions, and ``.include`` of
                  external libraries.
            control: list of ngspice-syntax control commands such as
                     ``["op"]``, ``["tran 10us 10ms"]``, or
                     ``["dc Vvbus 4.5 5.5 0.05"]``. The backend wraps these
                     in a ``.control`` / ``.endc`` block plus output capture.
            temperature_c: simulation temperature in degrees Celsius
                           (becomes ``.options TEMP=…`` for ngspice).

        Returns ``SimResult``.

        Raises ``BackendError`` if the simulator fails to start, the deck is
        malformed, or the analysis errors out.
        """
        ...


class BackendError(RuntimeError):
    """Raised when the simulator process fails or the deck is rejected."""
    pass

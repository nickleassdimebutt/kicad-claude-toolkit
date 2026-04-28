"""SPICE pre-flight analyses for circuit_toolkit boards.

Six standard analyses, each emitting a PNG plot to ``output_dir``:

    1. simulate_transient        startup ramp on VBUS, observe V_OUT settle
    2. simulate_load_step        I_load step, observe V_OUT droop & recovery
    3. simulate_line_regulation  DC sweep on V_BUS, observe V_OUT vs V_in
    4. simulate_load_regulation  DC sweep on I_load, observe V_OUT vs I
    5. simulate_temperature      sweep T, observe V_OUT vs ambient
    6. simulate_monte_carlo      randomise R / C tolerances, V_OUT histogram

Each function takes a Board and a target output directory; defaults are
sensible for a 5 V → 3.3 V LDO board such as usbc-3v3 but every parameter is
overridable. ``simulate_all(board, output_dir)`` runs all six in sequence.

The honest caveat (from the v2 plan): for an LDO this simple, SPICE results
are predictable from the datasheet. The value here is establishing the
pattern for future complex circuits (and catching gross wiring mistakes
before fab), not catching subtle bugs in usbc-3v3 itself.
"""
from __future__ import annotations
import math
import random
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import u_V, u_A, u_mA, u_Ohm, u_kOhm, u_uF, u_nF, u_ms, u_us, u_s

from circuit_toolkit.core.board import Board
from circuit_toolkit.sim.netlist import (
    NetMap, board_to_circuit, build_netmap, include_models, parse_value,
)
from circuit_toolkit.sim.theme import (
    apply_theme, style_axes, GOLD, GOLD_DEEP, PURPLE, PURPLE_LIGHT,
    PURPLE_FAINT, INK_MUTED,
)


# ── Defaults that match a 5 V → 3.3 V LDO board ───────────────────────────────
DEFAULT_VBUS = 5.0          # V
DEFAULT_OUT_NET = "+3V3"    # net name (sanitisation handled by NetMap)
DEFAULT_LOAD_MA = 100.0     # mA
DEFAULT_TEMP_C = 27.0       # ngspice nominal


# ── Bare operating-point helper (used by property-based tests) ────────────────

def simulate_op(board: Board,
                vbus: float = DEFAULT_VBUS,
                load_ma: float = DEFAULT_LOAD_MA,
                temperature_c: float = DEFAULT_TEMP_C,
                out_net: str = DEFAULT_OUT_NET,
                vbus_net: str = "VBUS",
                overrides: Optional[Dict[str, object]] = None,
                subckt_params: Optional[Dict[str, Dict[str, float]]] = None
                ) -> Dict[str, float]:
    """Run a single SPICE operating-point sim and return ``{node: voltage}``.

    No plotting, no file I/O — the unit primitive that the property-test
    framework calls hundreds of times across a parameter sweep.

    Note: net names follow the sanitised SPICE form (lower-case, '+' kept).
    Use the original board net names when looking up results — `NetMap`
    handles the lookup transparently.
    """
    ctx = _new_context(board, ("dc", float(vbus)), load_ma,
                       out_net=out_net, vbus_net=vbus_net,
                       overrides=overrides, subckt_params=subckt_params)
    sim = ctx.circuit.simulator(temperature=temperature_c,
                                nominal_temperature=temperature_c)
    op = sim.operating_point()
    out: Dict[str, float] = {}
    for node in op.nodes.values():
        # node.name is the lower-cased SPICE node name
        out[str(node.name)] = float(node[0])
    # Provide a friendly alias so callers can ask for the original
    # board-level net name regardless of SPICE's case mangling.
    spice_out = ctx.out_node.lower()
    if spice_out in out:
        out[out_net] = out[spice_out]
    return out


# ── Internal: build a primed Circuit (board + sources + load) ─────────────────

@dataclass
class _SimContext:
    circuit: Circuit
    net_map: NetMap
    out_node: str
    vbus_node: str


def _new_context(board: Board,
                 vbus_source: str | tuple,
                 load_ma: float,
                 out_net: str = DEFAULT_OUT_NET,
                 vbus_net: str = "VBUS",
                 overrides: Optional[Dict[str, object]] = None,
                 subckt_params: Optional[Dict[str, Dict[str, float]]] = None,
                 ) -> _SimContext:
    """Build a complete Circuit: components, models, VBUS source, output load.

    `vbus_source` is either:
        ('dc', volts)
        ('pwl', [(t0, v0), (t1, v1), ...])
    `load_ma` is the constant DC load on the output rail in milliamps.
    `subckt_params` flows through to the Board → Circuit translator so the
    LDO's vref / vdrop / etc. can be jittered for Monte Carlo.
    """
    circ = Circuit(board.name)
    include_models(circ)
    net_map = build_netmap(board)

    # Components first — emits R, C, D, X(subckt) elements based on board contents.
    board_to_circuit(board, circ, net_map, overrides=overrides,
                     subckt_params=subckt_params)

    vbus_spice = net_map[vbus_net]
    out_spice = net_map[out_net]

    # VBUS test source.
    kind = vbus_source[0]
    if kind == "dc":
        circ.V("vbus", vbus_spice, circ.gnd, vbus_source[1])
    elif kind == "pwl":
        # PySpice >=1.5 has PieceWiseLinearVoltageSource; pass plain (s, V) tuples.
        circ.PieceWiseLinearVoltageSource(
            "vbus", vbus_spice, circ.gnd, values=vbus_source[1])
    else:
        raise ValueError(f"unknown vbus_source kind {kind!r}")

    # Load on the output rail (constant current sink: positive Iload draws from out_spice → gnd).
    if load_ma > 0:
        circ.I("load", out_spice, circ.gnd, load_ma * 1e-3)

    return _SimContext(circuit=circ, net_map=net_map,
                       out_node=out_spice, vbus_node=vbus_spice)


# ── Plot helper ───────────────────────────────────────────────────────────────

def _save(fig, output_dir: Path, name: str) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f"{name}.png"
    fig.savefig(out)
    return out


# ── 1. Transient (startup) ────────────────────────────────────────────────────

def simulate_transient(board: Board,
                       output_dir: str | Path,
                       vbus: float = DEFAULT_VBUS,
                       vbus_ramp_ms: float = 1.0,
                       sim_duration_ms: float = 10.0,
                       load_ma: float = DEFAULT_LOAD_MA,
                       out_net: str = DEFAULT_OUT_NET,
                       vbus_net: str = "VBUS") -> Path:
    """Ramp VBUS 0 → `vbus` over `vbus_ramp_ms` ms, watch the output settle.

    Plot: VBUS and V_OUT vs time.
    """
    apply_theme()
    import matplotlib.pyplot as plt

    pwl = [(0.0, 0.0), (vbus_ramp_ms * 1e-3, float(vbus)),
           (sim_duration_ms * 1e-3, float(vbus))]
    ctx = _new_context(board, ("pwl", pwl), load_ma, out_net=out_net, vbus_net=vbus_net)

    sim = ctx.circuit.simulator(temperature=DEFAULT_TEMP_C,
                                nominal_temperature=DEFAULT_TEMP_C)
    analysis = sim.transient(step_time=10e-6, end_time=sim_duration_ms * 1e-3)

    t_ms = analysis.time * 1000.0
    v_in = analysis[ctx.vbus_node]
    v_out = analysis[ctx.out_node]

    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    ax.plot(t_ms, v_in,  label="V_BUS",  color=PURPLE)
    ax.plot(t_ms, v_out, label="V_OUT (+3V3)", color=GOLD_DEEP, linewidth=2.0)
    ax.axhline(3.3, color=PURPLE_LIGHT, linestyle=":", linewidth=0.9,
               label="V_REF = 3.30 V")
    style_axes(ax,
               title=f"Transient startup — V_BUS ramp {vbus_ramp_ms:g} ms, "
                     f"I_load = {load_ma:g} mA",
               xlabel="time  (ms)", ylabel="voltage  (V)",
               witty_caption="Electrons reach steady state. Designers, eventually.")
    ax.legend(loc="lower right")
    fig.tight_layout()
    return _save(fig, output_dir, "transient")


# ── 2. Load step ──────────────────────────────────────────────────────────────

def simulate_load_step(board: Board,
                       output_dir: str | Path,
                       vbus: float = DEFAULT_VBUS,
                       i_min_ma: float = 10.0,
                       i_max_ma: float = 100.0,
                       step_at_ms: float = 2.0,
                       rise_us: float = 5.0,
                       sim_duration_ms: float = 6.0,
                       out_net: str = DEFAULT_OUT_NET,
                       vbus_net: str = "VBUS") -> Path:
    """Step the load from `i_min_ma` to `i_max_ma` at `step_at_ms`. Plot V_OUT.

    Captures the LDO's transient response (droop + recovery).
    """
    apply_theme()
    import matplotlib.pyplot as plt

    # Build the static circuit (no static load — we'll add a PULSE current source).
    ctx = _new_context(board, ("dc", float(vbus)), load_ma=0.0,
                       out_net=out_net, vbus_net=vbus_net)
    # PULSE current source: low → high → low. Use a single step (no return).
    # Iload = i_min when t<step_at, then i_max for the rest.
    delay_s = step_at_ms * 1e-3
    rise_s = rise_us * 1e-6
    width_s = sim_duration_ms * 1e-3  # stays high to end of sim
    period_s = 2 * sim_duration_ms * 1e-3  # > end → no second pulse
    ctx.circuit.PulseCurrentSource(
        "load", ctx.out_node, ctx.circuit.gnd,
        initial_value=i_min_ma * 1e-3, pulsed_value=i_max_ma * 1e-3,
        delay_time=delay_s, rise_time=rise_s, fall_time=rise_s,
        pulse_width=width_s, period=period_s,
    )

    sim = ctx.circuit.simulator(temperature=DEFAULT_TEMP_C,
                                nominal_temperature=DEFAULT_TEMP_C)
    analysis = sim.transient(step_time=1e-6, end_time=sim_duration_ms * 1e-3)

    t_ms = analysis.time * 1000.0
    v_out = analysis[ctx.out_node]

    fig, (ax_top, ax_bot) = plt.subplots(2, 1, figsize=(8.5, 5.5),
                                         sharex=True, height_ratios=[1, 2])
    # Top axis: load profile (analytic) — drawn for clarity, not measured.
    iload_profile = [i_min_ma if t < step_at_ms else i_max_ma for t in t_ms]
    ax_top.plot(t_ms, iload_profile, color=PURPLE, drawstyle="steps-post")
    style_axes(ax_top, title="I_load profile", ylabel="I_load  (mA)")
    ax_top.set_ylim(0, max(i_max_ma * 1.15, 50))

    # Bottom axis: V_OUT response.
    ax_bot.plot(t_ms, v_out, color=GOLD_DEEP, linewidth=1.6)
    ax_bot.axhline(3.3, color=PURPLE_LIGHT, linestyle=":", linewidth=0.9,
                   label="V_REF")
    style_axes(ax_bot,
               title=f"V_OUT response — load step {i_min_ma:g} → {i_max_ma:g} mA",
               xlabel="time  (ms)", ylabel="V_OUT  (V)",
               witty_caption="A short pulse of disrespect, recovered with grace.")
    ax_bot.legend(loc="lower right")
    fig.tight_layout()
    return _save(fig, output_dir, "load_step")


# ── 3. Line regulation (DC sweep on V_BUS) ────────────────────────────────────

def simulate_line_regulation(board: Board,
                             output_dir: str | Path,
                             vbus_min: float = 4.0,
                             vbus_max: float = 5.5,
                             vbus_step: float = 0.05,
                             load_ma: float = DEFAULT_LOAD_MA,
                             out_net: str = DEFAULT_OUT_NET,
                             vbus_net: str = "VBUS") -> Path:
    """DC sweep V_BUS from `vbus_min` → `vbus_max`. Plot V_OUT vs V_BUS.

    Shows the dropout knee and the regulation slope (≈ line regulation %).
    """
    apply_theme()
    import matplotlib.pyplot as plt

    ctx = _new_context(board, ("dc", float(vbus_min)), load_ma,
                       out_net=out_net, vbus_net=vbus_net)
    sim = ctx.circuit.simulator(temperature=DEFAULT_TEMP_C,
                                nominal_temperature=DEFAULT_TEMP_C)
    # DC sweep: ngspice .DC element start stop step
    analysis = sim.dc(Vvbus=slice(vbus_min, vbus_max + 1e-9, vbus_step))

    v_in = analysis.sweep
    v_out = analysis[ctx.out_node]

    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    ax.plot(v_in, v_out, color=GOLD_DEEP, linewidth=1.8, label="V_OUT")
    ax.plot(v_in, v_in,  color=PURPLE_LIGHT, linewidth=0.9,
            linestyle="--", label="V_BUS (1:1 reference)")
    ax.axhline(3.3, color=PURPLE, linestyle=":", linewidth=0.9, label="V_REF = 3.30 V")
    # Annotate the dropout knee
    knee_v = 3.3 + 1.1
    ax.axvline(knee_v, color=INK_MUTED, linestyle=":", linewidth=0.7)
    ax.text(knee_v + 0.02, 1.0, f"dropout knee ≈ {knee_v:.2f} V", color=INK_MUTED,
            fontsize=8, rotation=90, va="bottom")

    style_axes(ax,
               title=f"Line regulation — I_load = {load_ma:g} mA",
               xlabel="V_BUS  (V)", ylabel="V_OUT  (V)",
               witty_caption="Vout, mostly indifferent to the supply rail.")
    ax.legend(loc="lower right")
    fig.tight_layout()
    return _save(fig, output_dir, "line_reg")


# ── 4. Load regulation (DC sweep on I_load) ───────────────────────────────────

def simulate_load_regulation(board: Board,
                             output_dir: str | Path,
                             vbus: float = DEFAULT_VBUS,
                             i_max_ma: float = 800.0,
                             n_points: int = 80,
                             out_net: str = DEFAULT_OUT_NET,
                             vbus_net: str = "VBUS") -> Path:
    """Sweep load current 0 → `i_max_ma` at fixed V_BUS. Plot V_OUT vs I_load.

    Implemented as N transient sims at varying constant load (PySpice's DC
    sweep on a current source is awkward; this scales linearly enough).
    """
    apply_theme()
    import matplotlib.pyplot as plt

    loads = [i_max_ma * (k / max(1, n_points - 1)) for k in range(n_points)]
    vouts: List[float] = []
    for il in loads:
        ctx = _new_context(board, ("dc", float(vbus)), il,
                           out_net=out_net, vbus_net=vbus_net)
        sim = ctx.circuit.simulator(temperature=DEFAULT_TEMP_C,
                                    nominal_temperature=DEFAULT_TEMP_C)
        op = sim.operating_point()
        vouts.append(float(op[ctx.out_node][0]))

    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    ax.plot(loads, vouts, color=GOLD_DEEP, linewidth=1.8)
    ax.axhline(3.3, color=PURPLE, linestyle=":", linewidth=0.9, label="V_REF = 3.30 V")
    style_axes(ax,
               title=f"Load regulation — V_BUS = {vbus:g} V",
               xlabel="I_load  (mA)", ylabel="V_OUT  (V)",
               witty_caption="The price of current is, alas, paid in millivolts.")
    ax.legend(loc="lower left")
    fig.tight_layout()
    return _save(fig, output_dir, "load_reg")


# ── 5. Temperature sweep ──────────────────────────────────────────────────────

def simulate_temperature_sweep(board: Board,
                               output_dir: str | Path,
                               t_min_c: float = -40.0,
                               t_max_c: float = 85.0,
                               t_step_c: float = 5.0,
                               vbus: float = DEFAULT_VBUS,
                               load_ma: float = DEFAULT_LOAD_MA,
                               out_net: str = DEFAULT_OUT_NET,
                               vbus_net: str = "VBUS") -> Path:
    """Operating point at each temperature. Plot V_OUT vs T."""
    apply_theme()
    import matplotlib.pyplot as plt

    temps: List[float] = []
    t = t_min_c
    while t <= t_max_c + 1e-9:
        temps.append(round(t, 3))
        t += t_step_c

    vouts: List[float] = []
    for temp_c in temps:
        ctx = _new_context(board, ("dc", float(vbus)), load_ma,
                           out_net=out_net, vbus_net=vbus_net)
        sim = ctx.circuit.simulator(temperature=temp_c, nominal_temperature=temp_c)
        op = sim.operating_point()
        vouts.append(float(op[ctx.out_node][0]))

    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    ax.plot(temps, vouts, color=GOLD_DEEP, linewidth=1.8, marker="o", markersize=3)
    ax.axhline(3.3, color=PURPLE, linestyle=":", linewidth=0.9, label="V_REF nominal")
    # Compute drift in mV across the full range
    drift_mv = (max(vouts) - min(vouts)) * 1000.0
    style_axes(ax,
               title=f"Temperature drift — V_BUS = {vbus:g} V, I_load = {load_ma:g} mA",
               xlabel="ambient temperature  (°C)", ylabel="V_OUT  (V)",
               witty_caption=f"Total drift across {t_min_c:g}…{t_max_c:g} °C: "
                             f"{drift_mv:.1f} mV.")
    ax.legend(loc="lower right")
    fig.tight_layout()
    return _save(fig, output_dir, "temp_sweep")


# ── 6. Monte Carlo (component tolerance) ──────────────────────────────────────

def _gauss_jitter(nominal: float, tol: float, rng: random.Random) -> float:
    """3σ ≈ tolerance: draw from N(nominal, (nominal·tol/3)²) and clamp to ±tol."""
    sigma = abs(nominal) * tol / 3.0
    val = rng.gauss(nominal, sigma)
    lo = nominal * (1 - tol)
    hi = nominal * (1 + tol)
    return max(lo, min(hi, val))


def simulate_monte_carlo(board: Board,
                         output_dir: str | Path,
                         n_runs: int = 100,
                         r_tol: float = 0.01,
                         c_tol: float = 0.10,
                         vref_tol: float = 0.02,
                         vbus: float = DEFAULT_VBUS,
                         load_ma: float = DEFAULT_LOAD_MA,
                         seed: int = 0xC1FCD17,
                         out_net: str = DEFAULT_OUT_NET,
                         vbus_net: str = "VBUS",
                         ldo_ref: str = "U1",
                         ldo_vref_nominal: float = 3.3) -> Path:
    """Run `n_runs` operating-point sims with gaussian jitter applied to:

    - every R nominal at ±`r_tol` (default 1 %)
    - every C nominal at ±`c_tol` (default 10 %)
    - the LDO's V_REF at ±`vref_tol` (default 2 % — AMS1117 datasheet typ.)

    R/C tolerances rarely move V_OUT for an LDO board (caps are bypass,
    most R aren't in the regulation loop) — V_REF tolerance dominates.
    Plotting all three jitters together gives an honest output spread.
    """
    apply_theme()
    import matplotlib.pyplot as plt

    rng = random.Random(seed)
    vouts: List[float] = []

    # Collect nominal values for every R and C in the board
    passives: List[Tuple[str, float, float]] = []  # (ref, nominal, tol)
    for comp in board.components:
        if comp.ref.startswith("R"):
            try:
                passives.append((comp.ref, parse_value(comp.value), r_tol))
            except ValueError:
                pass
        elif comp.ref.startswith("C"):
            try:
                passives.append((comp.ref, parse_value(comp.value), c_tol))
            except ValueError:
                pass

    has_ldo = board.find_ref(ldo_ref) is not None

    for k in range(n_runs):
        overrides: Dict[str, object] = {}
        for ref, nominal, tol in passives:
            overrides[ref] = _gauss_jitter(nominal, tol, rng)
        subckt_params: Dict[str, Dict[str, float]] = {}
        if has_ldo and vref_tol > 0:
            subckt_params[ldo_ref] = {
                "vref": _gauss_jitter(ldo_vref_nominal, vref_tol, rng),
            }
        ctx = _new_context(board, ("dc", float(vbus)), load_ma,
                           out_net=out_net, vbus_net=vbus_net,
                           overrides=overrides,
                           subckt_params=subckt_params)
        sim = ctx.circuit.simulator(temperature=DEFAULT_TEMP_C,
                                    nominal_temperature=DEFAULT_TEMP_C)
        op = sim.operating_point()
        vouts.append(float(op[ctx.out_node][0]))

    mean = statistics.fmean(vouts)
    sigma = statistics.pstdev(vouts) if len(vouts) > 1 else 0.0
    pct = (sigma / mean * 100) if mean else 0.0

    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    ax.hist(vouts, bins=min(30, max(8, n_runs // 4)),
            color=PURPLE_LIGHT, edgecolor=PURPLE, linewidth=0.6)
    ax.axvline(3.3, color=GOLD_DEEP, linestyle="-", linewidth=1.4, label="V_REF nominal")
    ax.axvline(mean, color=PURPLE, linestyle="--", linewidth=1.0,
               label=f"mean = {mean:.4f} V")
    title = (f"Monte Carlo — {n_runs} runs, R ±{r_tol*100:g} %, "
             f"C ±{c_tol*100:g} %")
    if has_ldo and vref_tol > 0:
        title += f", V_REF ±{vref_tol*100:g} %"
    style_axes(ax,
               title=title,
               xlabel="V_OUT  (V)", ylabel="count",
               witty_caption=f"σ = {sigma*1000:.2f} mV  ({pct:.3f} %).  "
                             f"Tolerances: tested, not feared.")
    ax.legend(loc="upper right")
    fig.tight_layout()
    return _save(fig, output_dir, "monte_carlo")


# ── Convenience: run all six ──────────────────────────────────────────────────

def simulate_all(board: Board,
                 output_dir: str | Path,
                 monte_carlo_runs: int = 100) -> Dict[str, Path]:
    """Run all six analyses with sensible defaults. Returns name → PNG path."""
    out: Dict[str, Path] = {}
    out["transient"]   = simulate_transient(board, output_dir)
    out["load_step"]   = simulate_load_step(board, output_dir)
    out["line_reg"]    = simulate_line_regulation(board, output_dir)
    out["load_reg"]    = simulate_load_regulation(board, output_dir)
    out["temp_sweep"]  = simulate_temperature_sweep(board, output_dir)
    out["monte_carlo"] = simulate_monte_carlo(board, output_dir,
                                              n_runs=monte_carlo_runs)
    return out

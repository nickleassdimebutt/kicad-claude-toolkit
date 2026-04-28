"""Property-based circuit testing.

A *property* is a statement that must hold across a parameter range —
"V_OUT stays in 3.3 V ± 2 % for V_BUS in [4.5, 5.5] and I_load in [0, 100] mA".
Instead of writing one test per (vbus, iload) point, you write the property
once; the framework sweeps the Cartesian product of the ranges, runs an
operating-point sim per combination, evaluates the property, and reports.

Two-axis sweeps are visualised as heatmaps (continuous: the measured
value; discrete: pass/fail mask). One-axis sweeps fall back to a line
plot. Three or more axes report a summary only — too many dimensions
to plot honestly.

Example:

    from circuit_toolkit.sim.properties import check_property

    def vout_in_spec(op):
        v = op["+3V3"]
        return 3.234 <= v <= 3.366  # 3.3 V ± 2 %

    result = check_property(
        vout_in_spec, board,
        ranges={"vbus": [4.5, 4.75, 5.0, 5.25, 5.5],
                "load_ma": [0, 25, 50, 75, 100]},
        name="V_OUT in spec",
        observe="+3V3",
    )
    print(result.summary())            # → "25/25 passed (100.0 %)"
    result.heatmap("output/sim/property_vout.png")
"""
from __future__ import annotations
import itertools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from circuit_toolkit.core.board import Board
from circuit_toolkit.sim.runner import simulate_op
from circuit_toolkit.sim.theme import (
    apply_theme, style_axes, GOLD, GOLD_DEEP, PURPLE, PURPLE_LIGHT,
    PURPLE_FAINT, INK_MUTED,
)


SpecFn = Callable[[Dict[str, float]], bool]


@dataclass
class _Case:
    params: Dict[str, float]
    passed: bool
    observed: float    # the value pulled from `op[observe]` (NaN if observe is None)
    op: Dict[str, float]


@dataclass
class PropertyResult:
    """Outcome of a property sweep."""
    name: str
    ranges: Dict[str, List[float]]
    observe: Optional[str]
    cases: List[_Case] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    def is_clean(self) -> bool:
        return self.failed == 0

    def summary(self) -> str:
        pct = (self.passed / self.total * 100.0) if self.total else 0.0
        return (f"[{self.name}] {self.passed}/{self.total} passed "
                f"({pct:.1f} %); {self.failed} failed")

    def failures(self) -> List[_Case]:
        return [c for c in self.cases if not c.passed]

    def heatmap(self, path: str | Path) -> Path:
        """Render a value/pass-fail heatmap. Picks a sensible plot for the
        number of swept axes (1, 2, or 3+). Returns the PNG path."""
        return _render_property_plot(self, path)


# ── Public entry point ────────────────────────────────────────────────────────

def check_property(spec: SpecFn,
                   board: Board,
                   ranges: Dict[str, Iterable[float]],
                   name: str = "property",
                   observe: Optional[str] = None,
                   **sim_kwargs: Any) -> PropertyResult:
    """Sweep ``ranges`` and evaluate ``spec`` at each combination.

    Args:
        spec: ``spec(op_dict) -> bool`` — receives the SPICE operating-point
              dict (net name → voltage), returns whether the property holds.
        board: the Board under test.
        ranges: dict of simulate_op kwargs to sweep (Cartesian product of
                their values is taken). Common keys: ``vbus``, ``load_ma``,
                ``temperature_c``.
        name: human-readable label for plots and summaries.
        observe: optional net name to record per-case for plotting (e.g.
                 ``"+3V3"``). If None, the heatmap shows pass/fail only.
        **sim_kwargs: extra fixed kwargs forwarded to simulate_op (e.g.
                      ``out_net="+5V"``, ``subckt_params={...}``).
    """
    materialised = {k: list(v) for k, v in ranges.items()}
    keys = list(materialised.keys())
    cases: List[_Case] = []

    for combo in itertools.product(*materialised.values()):
        params = dict(zip(keys, combo))
        op = simulate_op(board, **params, **sim_kwargs)
        passed = bool(spec(op))
        observed = float(op.get(observe, float("nan"))) if observe else float("nan")
        cases.append(_Case(params=params, passed=passed,
                           observed=observed, op=op))

    return PropertyResult(name=name, ranges=materialised,
                          observe=observe, cases=cases)


# ── Plotting (1D / 2D / 3+D) ──────────────────────────────────────────────────

def _render_property_plot(result: PropertyResult, path: str | Path) -> Path:
    apply_theme()
    import matplotlib.pyplot as plt
    import numpy as np

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n_axes = len(result.ranges)

    if n_axes == 1:
        return _plot_1d(result, out_path)
    if n_axes == 2:
        return _plot_2d(result, out_path)
    return _plot_summary_only(result, out_path)


def _plot_1d(result: PropertyResult, out_path: Path) -> Path:
    import matplotlib.pyplot as plt

    (axis_name, values), = result.ranges.items()
    xs = list(values)
    obs = [c.observed for c in result.cases]
    pass_mask = [c.passed for c in result.cases]

    fig, ax = plt.subplots(figsize=(8.5, 4.0))
    if result.observe:
        ax.plot(xs, obs, color=GOLD_DEEP, linewidth=1.6, marker="o", markersize=3,
                label=result.observe)
        # Overlay failures with a red marker
        for x, v, ok in zip(xs, obs, pass_mask):
            if not ok:
                ax.plot(x, v, marker="x", color="#B22222", markersize=8,
                        markeredgewidth=2, linestyle="None")
    else:
        # Pure pass/fail: plot a step
        ys = [1 if ok else 0 for ok in pass_mask]
        ax.step(xs, ys, color=PURPLE, where="mid")
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["FAIL", "PASS"])
    style_axes(ax,
               title=f"{result.name} — {result.summary()}",
               xlabel=axis_name,
               ylabel=(result.observe or "spec"),
               witty_caption=("Properties: assertions that mean it." if result.is_clean()
                              else "A property held until it didn't."))
    if result.observe:
        ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(out_path)
    return out_path


def _plot_2d(result: PropertyResult, out_path: Path) -> Path:
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap

    keys = list(result.ranges.keys())
    xname, yname = keys[0], keys[1]
    xs = result.ranges[xname]
    ys = result.ranges[yname]

    # Build value matrix and pass mask in (y, x) shape so imshow rows = y axis.
    val = np.full((len(ys), len(xs)), float("nan"))
    pas = np.zeros((len(ys), len(xs)), dtype=bool)
    for c in result.cases:
        ix = xs.index(c.params[xname])
        iy = ys.index(c.params[yname])
        val[iy, ix] = c.observed
        pas[iy, ix] = c.passed

    # Custom purple→gold colormap so the plot stays in the datasheet palette.
    cmap = LinearSegmentedColormap.from_list(
        "lt", [PURPLE, PURPLE_LIGHT, "#FFFFFF", GOLD, GOLD_DEEP], N=256)

    fig, ax = plt.subplots(figsize=(8.5, 5.0))
    extent = [xs[0], xs[-1], ys[0], ys[-1]]
    if result.observe:
        im = ax.imshow(val, aspect="auto", origin="lower",
                       extent=extent, cmap=cmap)
        cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label(result.observe, color=PURPLE)
    else:
        # Pass/fail mask only
        ax.imshow(pas.astype(float), aspect="auto", origin="lower",
                  extent=extent, cmap="RdYlGn", vmin=0, vmax=1)

    # Overlay X markers on failed cells
    fail_iy, fail_ix = np.where(~pas)
    for iy, ix in zip(fail_iy, fail_ix):
        ax.plot(xs[ix], ys[iy], marker="x", color="#B22222",
                markersize=10, markeredgewidth=2, linestyle="None")

    style_axes(ax,
               title=f"{result.name} — {result.summary()}",
               xlabel=xname, ylabel=yname,
               witty_caption=("Properties: assertions that mean it." if result.is_clean()
                              else f"{result.failed} failure(s) marked ×."))
    fig.tight_layout()
    fig.savefig(out_path)
    return out_path


def _plot_summary_only(result: PropertyResult, out_path: Path) -> Path:
    """3+ swept axes — too many dimensions for an honest plot. Render a
    text card instead so the file still exists for verify.sh / datasheet."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8.5, 4.0))
    ax.axis("off")
    lines = [
        result.summary(),
        "",
        "Swept axes:",
    ]
    for k, vs in result.ranges.items():
        lines.append(f"   {k}: {len(vs)} points  [{vs[0]} … {vs[-1]}]")
    if result.failed:
        lines.append("")
        lines.append(f"First {min(5, result.failed)} failures:")
        for c in result.failures()[:5]:
            params_str = ", ".join(f"{k}={v:g}" for k, v in c.params.items())
            extra = f"  ({result.observe}={c.observed:.4f})" if result.observe else ""
            lines.append(f"   {params_str}{extra}")
    ax.text(0.02, 0.95, "\n".join(lines), transform=ax.transAxes,
            ha="left", va="top", color=PURPLE, family="monospace",
            fontsize=10)
    ax.text(0.99, 0.05, "3-D+ sweep — text summary only.",
            transform=ax.transAxes, ha="right", color=INK_MUTED,
            fontsize=8, style="italic")
    fig.savefig(out_path)
    return out_path

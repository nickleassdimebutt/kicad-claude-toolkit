"""Matplotlib theming to match the datasheet PDF (purple/gold)."""
from __future__ import annotations

PURPLE       = "#4B2C82"
PURPLE_LIGHT = "#7B5BB6"
PURPLE_FAINT = "#EFEAF7"
GOLD         = "#D4AF37"
GOLD_DEEP    = "#A8851F"
INK          = "#1B1B22"
INK_MUTED    = "#5C5C68"
PAPER        = "#FFFFFF"

# Trace cycle ordered for typical LDO plots: input/output trace pair, then the rest.
TRACE_CYCLE = [PURPLE, GOLD_DEEP, PURPLE_LIGHT, GOLD, INK_MUTED, "#2A6F4D", "#8E2A52"]


def apply_theme():
    """Apply matplotlib rcParams in-place. Called at simulation entry."""
    import matplotlib as mpl
    mpl.rcParams.update({
        "figure.facecolor":  PAPER,
        "axes.facecolor":    PAPER,
        "axes.edgecolor":    INK,
        "axes.labelcolor":   INK,
        "axes.titleweight":  "bold",
        "axes.titlecolor":   PURPLE,
        "axes.titlesize":    12,
        "axes.labelsize":    10,
        "axes.linewidth":    0.8,
        "axes.grid":         True,
        "grid.color":        PURPLE_FAINT,
        "grid.linewidth":    0.6,
        "grid.linestyle":    "-",
        "xtick.color":       INK_MUTED,
        "ytick.color":       INK_MUTED,
        "xtick.labelsize":   9,
        "ytick.labelsize":   9,
        "legend.frameon":    True,
        "legend.framealpha": 0.92,
        "legend.edgecolor":  PURPLE_FAINT,
        "legend.fontsize":   9,
        "lines.linewidth":   1.5,
        "font.family":       "sans-serif",
        "font.sans-serif":   ["Inter", "Arial", "DejaVu Sans"],
        "savefig.dpi":       140,
        "savefig.bbox":      "tight",
        "axes.prop_cycle":   __import__("cycler").cycler(color=TRACE_CYCLE),
    })


def style_axes(ax, title: str | None = None,
               xlabel: str | None = None, ylabel: str | None = None,
               witty_caption: str | None = None):
    """Apply consistent annotation style to a single axes."""
    if title:
        ax.set_title(title, color=PURPLE, fontweight="bold", loc="left")
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    # Gold tick at the spine bottom — subtle accent
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(GOLD_DEEP)
    ax.spines["left"].set_color(INK_MUTED)
    if witty_caption:
        ax.text(0.99, -0.18, witty_caption, transform=ax.transAxes,
                ha="right", va="top", color=INK_MUTED, fontsize=8, style="italic")

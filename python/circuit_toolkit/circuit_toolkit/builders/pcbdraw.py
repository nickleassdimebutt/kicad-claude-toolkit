"""pcbdraw wrapper — produces stylized 2D PCB SVG/PNG renders.

Complements ``render_pcb`` (kicad-cli 3D photorealistic view): pcbdraw
produces a schematic-style flat view that's better for documentation —
copper traces, silkscreen, board outline, and component bodies (when a
matching art library is on-disk) all in vector form.

Two output paths:

    plot_board(pcb, out_dir, sides=("front", "back"))
        → out_dir/pcbdraw_front.svg, pcbdraw_back.svg

    plot_board(pcb, out_dir, sides=("front",), to_png=True)
        → out_dir/pcbdraw_front.svg + .png  (PNG via Inkscape if on PATH)

The companion ``ASSEMBLY_HIGHLIGHT`` style and the ``filter`` argument
are passed straight through; see ``pcbdraw plot --help`` for the full
parameter list. We expose only what the datasheet builder needs.

Note: when pcbdraw can't find a footprint art file it logs
"Component :<fp> has no footprint." — this is a warning, not an error;
the board outline + copper still render. To suppress, install a
matching art library (e.g. via ``pcbdraw libtemplate``) and pass it
via ``libs=``.
"""
from __future__ import annotations
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional


# pcbdraw entry point on Windows lives next to KiCad's bundled Python.
PCBDRAW_DEFAULT_WIN = (
    r"C:\Users\nicho\OneDrive\Documents\KiCad\10.0\3rdparty\Python311\Scripts\pcbdraw.exe"
)


def _resolve_pcbdraw(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    on_path = shutil.which("pcbdraw")
    if on_path:
        return on_path
    if os.path.exists(PCBDRAW_DEFAULT_WIN):
        return PCBDRAW_DEFAULT_WIN
    raise RuntimeError(
        "pcbdraw not found on PATH or at the default Windows location. "
        "Install with: <kicad-python> -m pip install pcbdraw  "
        "or pass an explicit path via pcbdraw_exe=...")


def plot_board(pcb_path: str | Path,
               output_dir: str | Path,
               sides: Iterable[str] = ("front", "back"),
               style: Optional[str] = None,
               libs: Optional[Iterable[str]] = None,
               to_png: bool = False,
               dpi: int = 300,
               drill_holes: bool = True,
               margin_mm: int = 1,
               pcbdraw_exe: Optional[str] = None,
               silent: bool = True) -> List[Path]:
    """Run ``pcbdraw plot`` once per requested side.

    Args:
        pcb_path: .kicad_pcb to render.
        output_dir: directory to write outputs (created if missing).
        sides: subset of {"front", "back"}.
        style: built-in style name ("default", "set-blue", ...) or path to JSON.
        libs: extra library directories to search for footprint art.
        to_png: also produce a PNG alongside the SVG (needs Inkscape on PATH).
        dpi: PNG resolution if to_png=True.
        drill_holes: render drills as transparent (True) or filled (False).
        margin_mm: blank margin around the board outline.
        pcbdraw_exe: override the auto-detected pcbdraw binary.
        silent: pass --silent to suppress missing-footprint warnings.

    Returns the list of generated file paths (SVG, plus PNG if requested).
    """
    pcb_path = Path(pcb_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    exe = _resolve_pcbdraw(pcbdraw_exe)
    outputs: List[Path] = []

    for side in sides:
        if side not in ("front", "back"):
            raise ValueError(f"unknown side {side!r} (expected front | back)")
        svg_path = output_dir / f"pcbdraw_{side}.svg"
        cmd = [exe, "plot", "--side", side,
               "--margin", str(margin_mm)]
        if style:
            cmd += ["--style", style]
        if libs:
            cmd += ["--libs", ",".join(libs)]
        if not drill_holes:
            cmd += ["--no-drill-holes"]
        if silent:
            cmd += ["--silent"]
        cmd += [str(pcb_path), str(svg_path)]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"pcbdraw plot failed for {side}:\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}")
        outputs.append(svg_path)

        if to_png:
            png_path = output_dir / f"pcbdraw_{side}.png"
            try:
                _svg_to_png(svg_path, png_path, dpi=dpi)
                outputs.append(png_path)
            except RuntimeError as e:
                # Non-fatal: SVG is still useful even without the PNG step.
                print(f"  [pcbdraw] PNG conversion skipped: {e}")

    return outputs


def _svg_to_png(svg_path: Path, png_path: Path, dpi: int = 300) -> None:
    """Convert SVG → PNG via Inkscape (CLI), then svglib+renderPM as fallback.

    Inkscape produces the highest-fidelity output for pcbdraw's stylesheet
    (it supports CSS, gradients, and text correctly). svglib is an OK
    fallback but loses some styling — fine for a thumbnail in a datasheet.
    """
    inkscape = shutil.which("inkscape") or shutil.which("inkscape.com")
    if inkscape:
        cmd = [inkscape, str(svg_path),
               f"--export-filename={png_path}",
               f"--export-dpi={dpi}",
               "--export-background=white",
               "--export-background-opacity=1"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0 and png_path.exists():
            return
        # fall through to svglib
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM
        drawing = svg2rlg(str(svg_path))
        renderPM.drawToFile(drawing, str(png_path), fmt="PNG", dpi=dpi)
    except Exception as e:
        raise RuntimeError(
            f"could not convert {svg_path.name} to PNG via Inkscape "
            f"(not on PATH) or svglib (failed: {e})")

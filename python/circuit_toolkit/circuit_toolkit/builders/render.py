"""PCB render — produces 3D PNG renders of the board via kicad-cli.

KiCad 10 added headless `kicad-cli pcb render` which works on Windows directly.
"""
from __future__ import annotations
import os
import subprocess
from pathlib import Path
from typing import List


KICAD_CLI_DEFAULT = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"


def render_pcb(pcb_path: str | Path,
               output_dir: str | Path,
               sides: List[str] = ("top", "bottom"),
               width: int = 2000,
               height: int = 1500,
               quality: str = "high",
               background: str = "transparent",
               kicad_cli: str | None = None) -> List[Path]:
    """Render PCB top/bottom (or other) views as PNGs.

    Args:
        pcb_path: path to .kicad_pcb
        output_dir: directory to write PNGs (created if missing)
        sides: subset of {"top","bottom","left","right","front","back"}
        width, height: pixel dimensions
        quality: "basic" | "high"
        background: "transparent" | "opaque"
        kicad_cli: full path to kicad-cli.exe (auto-detect if None)

    Returns list of generated PNG paths.
    """
    pcb_path = Path(pcb_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cli = kicad_cli or KICAD_CLI_DEFAULT
    if not os.path.exists(cli):
        raise RuntimeError(f"kicad-cli not found at {cli}")

    outputs: List[Path] = []
    for side in sides:
        out = output_dir / f"render_{side}.png"
        cmd = [
            cli, "pcb", "render",
            "--output", str(out),
            "--side", side,
            "--width", str(width),
            "--height", str(height),
            "--quality", quality,
            "--background", background,
            str(pcb_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"kicad-cli pcb render failed for {side}:\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        outputs.append(out)
    return outputs

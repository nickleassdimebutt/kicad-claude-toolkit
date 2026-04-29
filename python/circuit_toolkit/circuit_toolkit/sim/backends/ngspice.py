"""ngspice subprocess backend — invokes ``ngspice -b`` (or ``ngspice_con -b``
on Windows), captures the ASCII raw-file output, returns a uniform SimResult.

Why subprocess and not the shared library: the ngspice DLL ABI changes
between major versions (PySpice 1.5 doesn't recognise ngspice ≥ v37 and
silently drops ``.include`` directives). The CLI's batch interface and
ASCII raw-file format have been stable for over a decade, so this backend
keeps working across version bumps without code changes.

Raw-file format docs: ngspice manual §22.4 ("Rawfile Format"). We only
parse the ``Flags: real`` variant — no AC analyses (which produce complex
values) yet. Adding complex support is a small parser tweak when AC lands.
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from circuit_toolkit.sim.backends.base import Backend, BackendError, SimResult


# Auto-detect order: env var, PATH, common Windows install paths, Linux apt.
def _find_ngspice() -> str:
    explicit = os.environ.get("NGSPICE")
    if explicit and os.path.exists(explicit):
        return explicit
    for name in ("ngspice_con", "ngspice"):
        found = shutil.which(name) or shutil.which(f"{name}.exe")
        if found:
            return found
    win_candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Spice64\bin\ngspice_con.exe"),
        r"C:\Spice64\bin\ngspice_con.exe",
        r"C:\Program Files\ngspice\bin\ngspice_con.exe",
    ]
    for c in win_candidates:
        if os.path.exists(c):
            return c
    raise BackendError(
        "ngspice CLI not found. Install ngspice and ensure it is on PATH, "
        "or set the NGSPICE environment variable to its full path. On Ubuntu: "
        "`apt install ngspice`; on Windows: extract the official "
        "ngspice-XX_64.7z release somewhere and either add bin/ to PATH or "
        "drop ngspice_con.exe at one of the autodetected paths."
    )


class NgSpiceBackend:
    """Backend implementation that shells out to ``ngspice_con -b``."""

    def __init__(self, ngspice_path: Optional[str] = None,
                 keep_temp_files: bool = False):
        self._exe = ngspice_path or _find_ngspice()
        self._keep = keep_temp_files

    def run(self, deck: str, control: List[str],
            temperature_c: float = 27.0) -> SimResult:
        # Build the complete deck: <user deck>\n.options TEMP=…\n.control … .endc\n.end
        with tempfile.TemporaryDirectory(prefix="ckt_sim_") as tmpdir:
            cir_path = Path(tmpdir) / "deck.cir"
            raw_path = Path(tmpdir) / "out.raw"
            cir_text = self._compose(deck, control, raw_path, temperature_c)
            cir_path.write_text(cir_text)

            try:
                proc = subprocess.run(
                    [self._exe, "-b", str(cir_path)],
                    capture_output=True, text=True, timeout=120,
                )
            except subprocess.TimeoutExpired as e:
                raise BackendError(f"ngspice timed out after 120s: {e}")

            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            # ngspice often returns 0 even on logical errors — sniff stdout
            # for the canonical "Error:" prefix it uses for parse / runtime
            # failures so a bad deck doesn't silently produce empty traces.
            if "Error:" in stdout or "Error:" in stderr:
                err_lines = [l for l in (stdout + stderr).splitlines()
                             if "Error" in l][:5]
                raise BackendError(
                    "ngspice reported an error:\n  " + "\n  ".join(err_lines)
                    + f"\n\nDeck head:\n{cir_text[:500]}"
                )
            if proc.returncode != 0:
                raise BackendError(
                    f"ngspice exit {proc.returncode}\n--- stdout ---\n{stdout[-1000:]}"
                    f"\n--- stderr ---\n{stderr[-500:]}"
                )

            if not raw_path.exists():
                raise BackendError(
                    "ngspice ran but did not write the expected raw file. "
                    f"stdout tail:\n{stdout[-800:]}"
                )

            raw_text = raw_path.read_text()

            if self._keep:
                # Move temp files somewhere persistent for inspection.
                dst = Path(tempfile.gettempdir()) / f"ckt_sim_keep_{os.getpid()}"
                dst.mkdir(exist_ok=True)
                (dst / "deck.cir").write_text(cir_text)
                (dst / "out.raw").write_text(raw_text)
                (dst / "stdout.log").write_text(stdout)

        return _parse_ascii_raw(raw_text)

    # ── internals ─────────────────────────────────────────────────────────────

    def _compose(self, deck: str, control: List[str], raw_path: Path,
                 temperature_c: float) -> str:
        """Wrap a user deck + control commands into a complete ngspice .cir file."""
        # ngspice on Windows requires forward-slash paths inside the deck even
        # when the OS uses backslashes — backslashes inside `write` get
        # interpreted as escape sequences by the tokenizer.
        raw_path_str = str(raw_path).replace("\\", "/")
        ctrl_block = "\n".join(control)
        return (
            f"{deck.rstrip()}\n"
            f".options TEMP={temperature_c:g} TNOM={temperature_c:g}\n"
            f".control\n"
            f"set filetype=ascii\n"
            f"set wr_singlescale\n"      # one shared x-axis column for all vars
            f"set wr_vecnames\n"         # write variable names in the file
            f"{ctrl_block}\n"
            f"write {raw_path_str} all\n"     # no quotes; ngspice tokenizes them as part of the filename
            f"quit\n"
            f".endc\n"
            f".end\n"
        )


# ── ASCII raw-file parser ─────────────────────────────────────────────────────

_VAR_LINE = re.compile(r"^\s*(\d+)\s+(\S+)\s+(\S+)")


def _parse_ascii_raw(text: str) -> SimResult:
    """Parse a single-plot ngspice ASCII raw file (Flags: real).

    Format (one plot — multi-plot files have multiple Title…Values blocks
    concatenated; we keep the LAST one, which is what ``write`` emits):

        Title: …
        Date: …
        Plotname: …
        Flags: real
        No. Variables: N
        No. Points: M
        Variables:
                0       <name>          <type>
                1       <name>          <type>
                ...
        Values:
         <pt>    <x0>
                <var1@x0>
                ...
                <varN-1@x0>
         <pt+1>  <x1>
                ...
    """
    # If multiple plots exist (operating point first, then a follow-on
    # analysis), keep only the last plot's payload — the analysis result
    # the caller asked for.
    plot_starts = [m.start() for m in re.finditer(r"^Title:", text, re.M)]
    if not plot_starts:
        raise BackendError("raw file has no Title header — empty or malformed")
    text = text[plot_starts[-1]:]

    lines = text.splitlines()
    n_vars = n_points = -1
    var_names: List[str] = []
    var_section = values_section = -1

    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("No. Variables:"):
            n_vars = int(s.split(":", 1)[1])
        elif s.startswith("No. Points:"):
            n_points = int(s.split(":", 1)[1])
        elif s == "Variables:":
            var_section = i
        elif s == "Values:" or s.startswith("Values:"):
            values_section = i
            break

    if n_vars < 0 or n_points < 0 or var_section < 0 or values_section < 0:
        raise BackendError(
            f"raw header parse failed (n_vars={n_vars}, n_points={n_points}, "
            f"var_section={var_section}, values_section={values_section})"
        )

    for i in range(n_vars):
        m = _VAR_LINE.match(lines[var_section + 1 + i])
        if not m:
            raise BackendError(
                f"could not parse variable line: {lines[var_section + 1 + i]!r}"
            )
        var_names.append(m.group(2).lower())

    # Values: each point has n_vars numbers. The first number on the first
    # line of each point block is preceded by the point index; all subsequent
    # values can be on their own lines or on the same line, ngspice is loose
    # about whitespace. Easiest robust parse: concatenate everything after
    # `Values:` and pull all floats in order.
    payload = "\n".join(lines[values_section + 1:])
    flat = re.findall(r"[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?", payload)
    # Each "point" emits (1 index) + (n_vars values). Validate length.
    expected = n_points * (n_vars + 1)
    if len(flat) < expected:
        raise BackendError(
            f"raw values short: got {len(flat)} numbers, expected {expected} "
            f"(n_points={n_points}, n_vars={n_vars})"
        )

    # Drop the leading point-index from each block and reshape.
    data = np.empty((n_vars, n_points), dtype=float)
    pos = 0
    for p in range(n_points):
        # First number is the point index (often p itself), skip it.
        pos += 1
        for v in range(n_vars):
            data[v, p] = float(flat[pos])
            pos += 1

    # First variable is the independent axis (time / sweep var / temperature).
    sweep = data[0] if n_vars > 0 else None
    traces: Dict[str, np.ndarray] = {}
    for i in range(n_vars):
        traces[var_names[i]] = data[i]

    return SimResult(sweep=sweep, traces=traces, raw=text)

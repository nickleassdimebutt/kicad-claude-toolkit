"""Schematic builder — emit netlistsvg-compatible JSON from Board, render via netlistsvg.

netlistsvg expects a Yosys-style JSON with modules/cells/ports/nets. We adapt
our Board topology to that shape so we can leverage netlistsvg's automatic
schematic layout.

Requires:
    npm install -g netlistsvg
And Node.js available on PATH (or pass node_path explicitly).
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

from circuit_toolkit.core.board import Board


# Default Windows install paths for netlistsvg
DEFAULT_NETLISTSVG_CMD_WIN = r"C:\Users\nicho\AppData\Roaming\npm\netlistsvg.cmd"
DEFAULT_NODE_DIR_WIN = r"C:\Program Files\nodejs"


def _board_to_netlistsvg_json(board: Board) -> dict:
    """Translate Board to netlistsvg's expected Yosys-JSON format."""
    cells: Dict[str, dict] = {}
    nets: Dict[str, List[int]] = {}
    next_bit = 2  # 0 and 1 are reserved for constants in netlistsvg

    def _bit_for_net(name: str) -> int:
        nonlocal next_bit
        if name not in nets:
            nets[name] = [next_bit]
            next_bit += 1
        return nets[name][0]

    for comp in board.components:
        if not comp.pin_map and comp.ref.startswith("H"):
            continue   # skip mounting holes — no electrical connectivity

        # Build a connections dict: {logical_pin_name: [bit]}
        # We use the LOGICAL pin names from pin_map keys, falling back to pad numbers
        connections: Dict[str, List[int]] = {}
        # First, find which net each pad of this component is on
        pad_to_net: Dict[str, str] = {}
        for net_name, net in board.nets.items():
            for pad in net.pads:
                if pad.component_ref == comp.ref:
                    pad_to_net[pad.pad_number] = net_name

        # Map back via pin_map: logical_name → pad_num → net_name
        for logical_name, pad_num in comp.pin_map.items():
            # Skip duplicate logical names (e.g. "1" and "2" alongside named pins)
            if logical_name.isdigit() and len(comp.pin_map) > 4:
                continue
            net_name = pad_to_net.get(pad_num)
            if net_name:
                connections[logical_name] = [_bit_for_net(net_name)]

        # Choose cell "type" — netlistsvg renders generic IC boxes by default
        cell_type = comp.value if len(comp.value) <= 20 else comp.ref
        cells[comp.ref] = {
            "type": cell_type,
            "connections": connections,
            "port_directions": {p: "input" for p in connections},
        }

    # netlistsvg JSON shape
    return {
        "modules": {
            board.name: {
                "ports": {},     # top-level ports — we don't have any (everything is internal)
                "cells": cells,
                "netnames": {
                    name: {"hide_name": 0, "bits": bits, "attributes": {}}
                    for name, bits in nets.items()
                },
            }
        }
    }


def _resolve_netlistsvg_cmd(netlistsvg_cmd: str | None) -> str:
    if netlistsvg_cmd:
        return netlistsvg_cmd
    # Try PATH
    found = shutil.which("netlistsvg")
    if found:
        return found
    # Try Windows default
    if os.path.exists(DEFAULT_NETLISTSVG_CMD_WIN):
        return DEFAULT_NETLISTSVG_CMD_WIN
    raise RuntimeError(
        "netlistsvg not found. Install with: npm install -g netlistsvg"
    )


def build_schematic(board: Board, output: str | Path,
                    netlistsvg_cmd: str | None = None,
                    node_dir: str | None = None) -> Path:
    """Generate a schematic SVG from a Board.

    Args:
        board: Board to render
        output: SVG file path to write
        netlistsvg_cmd: full path to netlistsvg.cmd (auto-detect if None)
        node_dir: directory containing node.exe (added to PATH for the subprocess)

    Returns the output Path.
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    netlistsvg_cmd = _resolve_netlistsvg_cmd(netlistsvg_cmd)
    if node_dir is None:
        node_dir = DEFAULT_NODE_DIR_WIN if os.name == "nt" else None

    # Write the netlist JSON to a temp file
    netlist_json = _board_to_netlistsvg_json(board)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
        json.dump(netlist_json, tf, indent=2)
        json_path = tf.name

    env = os.environ.copy()
    if node_dir and os.path.isdir(node_dir):
        env["PATH"] = node_dir + os.pathsep + env.get("PATH", "")

    try:
        result = subprocess.run(
            [netlistsvg_cmd, json_path, "-o", str(output)],
            env=env, capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"netlistsvg failed (exit {result.returncode}):\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
    finally:
        os.unlink(json_path)

    return output

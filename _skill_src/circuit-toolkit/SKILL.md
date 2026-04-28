---
name: circuit-toolkit
description: "Python toolkit for headless circuit description and KiCad PCB generation. Use this skill when the user wants to design a new PCB from a text description, port an existing PCB to a scriptable workflow, or work with the circuit_toolkit Python package. Provides reusable @subcircuit blocks (USB-C power, LDO regulators, LEDs, headers, mounting holes), a Board/Component/Net data model, and builders that emit .kicad_pcb (via pcbnew), schematic.svg (via netlistsvg), and BOM.csv with LCSC numbers. Always consult this skill when writing circuit.py, layout.py, or build.py for a board project."
---

# circuit_toolkit (verified on KiCad 10.0.1, Windows)

A Python package for **headless circuit description and KiCad PCB generation**. Lives at `kicad-claude-toolkit/python/circuit_toolkit/`.

> Source: https://github.com/nickleassdimebutt/kicad-claude-toolkit

## The three-file design pattern

Every board project has the same structure:

```
my-board/
├── circuit.py    # topology — uses circuit_toolkit.blocks
├── layout.py     # positions + tracks + vias + zones (hand-edited or extracted)
└── build.py      # orchestrator — calls circuit_toolkit.builders
```

`circuit.py` owns **what** is connected. `layout.py` owns **where** it lives physically. `build.py` ties them together.

## Install

Must install into KiCad's bundled Python (the one that has `pcbnew`):

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" -m pip install -e `
  "C:\Users\<you>\OneDrive\Documents\GitHub\kicad-claude-toolkit\python\circuit_toolkit"
```

Required system tools:
- KiCad 10.0.1 (`kicad-cli` for DRC, `pcbnew` Python for build)
- Node.js + `netlistsvg` for schematic SVG generation: `npm install -g netlistsvg`

## API — the typical `circuit.py`

```python
from circuit_toolkit import Board
from circuit_toolkit.blocks import (
    usbc_power, ams1117_ldo, led_indicator,
    pin_header, m2_mounting_hole,
)

def build():
    board = Board("my-board", size=(48, 30))

    vbus, gnd, cc1, cc2 = usbc_power(board, ref="J1", cc_pulldowns="5.1k")

    v3v3 = ams1117_ldo(
        board, ref="U1",
        vin=vbus, gnd=gnd, output_voltage=3.3,
        in_caps=["10uF/0805", "10uF/0805"],
        out_caps=["10uF/0805", "100nF/0402"],
    )

    led_indicator(board, ref_led="D1", ref_resistor="R3",
                  vin=v3v3, gnd=gnd, color="red", current_ma=1.3)

    pin_header(board, ref="J2", pins=2, label="3V3_OUT",
               nets=[v3v3, gnd])

    for ref in ("H1", "H2", "H3", "H4"):
        m2_mounting_hole(board, ref=ref)

    return board
```

## Reusable blocks (v0.1)

| Block | Returns | Notes |
|-------|---------|-------|
| `usbc_power(board, ref, cc_pulldowns)` | (vbus, gnd, cc1, cc2) nets | HRO TYPE-C-31-M-12; 5.1k = 5V/3A advertise. Auto-adds CC pulldowns and ties data lines + shield to GND for power-only mode |
| `ams1117_ldo(board, ref, vin, gnd, output_voltage, in_caps, out_caps)` | vout net | Adds in/out bypass caps automatically. Voltages: 3.3, 5.0, 1.8, 2.5 |
| `led_indicator(board, ref_led, ref_resistor, vin, gnd, color, current_ma)` | (led, resistor) | Auto-snaps current-limit resistor to E12. Colors: red/green/yellow/blue/white |
| `pin_header(board, ref, pins, nets, label)` | header component | 2.54mm, 1×N or 2×N |
| `m2_mounting_hole(board, ref)` / `m3_mounting_hole(board, ref)` | hole component | 2.2mm/3.2mm NPTH |
| `add_cap(board, ref, "value/package", net_a, net_b)` | cap component | 0402/0603/0805/1206 |
| `decoupling(board, vcc, gnd, [specs])` | list of caps | Bulk + bypass between two rails |

Every block carries:
- KiCad library footprint reference (e.g. `Resistor_SMD:R_0402_1005Metric`)
- LCSC part number (e.g. `C25905` for 5.1k 0402)
- `lcsc_basic` flag (JLCPCB basic vs extended part)
- Pin map (logical name → pad number)

## The typical `layout.py`

```python
# Auto-generated section (overwritten by extract_layout.py):
positions = {
    "J1": (5.5, 15, 270),
    "U1": (22, 15, 270),
    # ...
}

# Hand-edited routing — survives auto-regeneration of `positions`:
ref_text_overrides = {"R2": (9.0, 22.8)}

pad_zone_full = [("J1", "B7"), ("J1", "A8")]  # zone fill override

tracks = [
    # (net, x1, y1, x2, y2, width_mm, layer)
    ("VBUS", 9.545, 12.55, 11.8, 12.55, 0.3, "F.Cu"),
    # ...
]

vias = [
    # (net, x, y, drill_mm, size_mm)
    ("CC1", 10.87, 13.75, 0.4, 0.8),
    # ...
]

zones = [
    {"net": "GND", "layer": "F.Cu",
     "polygon": [(1, 1), (47, 1), (47, 29), (1, 29)],
     "min_thickness": 0.25, "pad_connection": "thermal"},
]

outline = {"shape": "rect", "x": 0.0, "y": 0.0, "w": 48.0, "h": 30.0}
```

## The typical `build.py`

```python
import circuit, layout
from circuit_toolkit.builders import build_pcb, build_schematic
from circuit_toolkit.fab import write_bom

def main():
    board = circuit.build()
    build_pcb(board, positions=layout.positions,
              output="my-board.kicad_pcb",
              tracks=layout.tracks, vias=layout.vias, zones=layout.zones,
              pad_zone_full=layout.pad_zone_full,
              ref_text_overrides=layout.ref_text_overrides,
              outline=layout.outline)
    build_schematic(board, "output/docs/schematic.svg")
    write_bom(board, "output/fab/bom")
```

## The round-trip pattern (the key UX win)

You write `circuit.py` once. `layout.py` starts as auto-generated default positions. Then you:

1. Run `python build.py` → produces initial `.kicad_pcb`
2. Open `.kicad_pcb` in **KiCad GUI** — drag components to new positions, save
3. Run `python -m circuit_toolkit.builders.extract_layout my-board.kicad_pcb layout.py`
4. The `positions = {...}` block in `layout.py` is updated to match what you placed; `tracks`, `vias`, `zones` are **preserved** (only the auto-generated section is replaced)
5. Commit `layout.py`

This means **KiCad GUI is your placement editor**, but `layout.py` remains the source of truth. The board is fully regenerable from text.

## Architecture layers (for tool-agnosticism)

| Layer | Tool affinity | Code location |
|-------|---------------|---------------|
| `blocks/` | **Tool-agnostic** (pure topology) | `@subcircuit` functions returning nets |
| `core/` | KiCad footprint vocabulary | Component/Net/Board classes — uses `Library:Footprint` strings |
| `builders/pcb.py` | KiCad-specific (pcbnew) | Uses `pcbnew.LoadBoard()`, `PCB_TRACK`, `ZONE_FILLER` |
| `builders/schematic.py` | netlistsvg-specific | Translates Board → Yosys-JSON → netlistsvg subprocess |
| `fab/` | KiCad/JLCPCB-specific | KiBot integration, BOM CSV format |

If you ever swap PCB CAD tools, `blocks/` is unchanged; you only rewrite `builders/`.

## Adding a new block

```python
# blocks/my_new_block.py
from circuit_toolkit.core.board import Board
from circuit_toolkit.core.component import Component
from circuit_toolkit.core.net import Net

def my_new_block(board: Board, ref: str, vin: Net, gnd: Net) -> Net:
    """Describe what this subcircuit does. Always return its primary output net."""
    u = Component(
        ref=ref,
        value="MY_PART",
        footprint="Library:FootprintName",
        lcsc="C12345",        # JLCPCB part #
        lcsc_basic=True,      # avoid extended-part fee where possible
        pin_map={"VIN": "1", "GND": "2", "VOUT": "3"},
        description="My new IC",
    )
    board.add(u)
    board.connect(vin, u, "VIN")
    board.connect(gnd, u, "GND")

    vout = board.net(f"OUT_{ref}")
    board.connect(vout, u, "VOUT")
    return vout
```

Then add it to `blocks/__init__.py`:
```python
from circuit_toolkit.blocks.my_new_block import my_new_block
```

## Common gotchas

| Issue | Fix |
|-------|-----|
| `Could not find pad 'X' on J1` | Probe actual pad numbers with `for p in fp.Pads(): print(p.GetNumber())` — KiCad library uses unconventional names like `"SH"` for all 4 USB-C shield pads |
| `pip install` says "no pcbnew" | You used system Python — must use KiCad's: `"C:\Program Files\KiCad\10.0\bin\python.exe" -m pip install -e ...` |
| Silk-overlap warnings on rebuild | Cosmetic only (0 errors). Project file (.kicad_pro) controls severity; warnings don't block fab |
| netlistsvg not found | `npm install -g netlistsvg`; ensure `node` is on PATH (or pass `node_dir` to `build_schematic`) |
| Position drift after GUI edit | Run `extract_layout.py` to round-trip; preserves your manual `tracks`/`vias`/`zones` |

## Reference design

`usbc-3v3` — USB-C → 3.3V 800mA LDO board.
- `circuit.py` — 25 lines using all 5 standard blocks
- `layout.py` — 95 lines (positions + 27 tracks + 4 vias + 1 GND zone)
- DRC: 0 errors
- BOM: 8 unique parts, all with LCSC numbers, all JLC basic where possible
- See `designs/usbc-3v3/` (separate repo)

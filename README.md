# kicad-claude-toolkit

AI-assisted PCB design workflow for KiCad 10. Two parts:

1. **17 Claude skills** (`*.skill` files at repo root) — domain knowledge for AI agents
2. **`circuit_toolkit` Python package** (in `python/circuit_toolkit/`) — executable counterpart of the skills, for headless circuit description and KiCad PCB generation

## Skills

Each `.skill` file is a packaged AI skill. Drop them into Claude Code or any compatible client. Highlights:

- `kicad-expert` — pcbnew Python API, S-expression file format, kicad-cli, KiBot, dense-connector routing methodology
- `circuit-toolkit` — how to use the Python package (this repo's `python/` subdirectory)
- `pcb-workflow` — orchestrator that decides which other skills to load
- 14 more covering schematic hygiene, design patterns, BOM, mechanical, power/thermal, bringup, etc.

## Python package — `circuit_toolkit`

Headless circuit description and KiCad PCB generation. Three-file pattern per design:

```
my-board/
├── circuit.py    # topology — uses circuit_toolkit.blocks
├── layout.py     # positions + tracks + vias + zones
└── build.py      # orchestrator
```

A typical `circuit.py`:

```python
from circuit_toolkit import Board
from circuit_toolkit.blocks import usbc_power, ams1117_ldo, led_indicator, pin_header, m2_mounting_hole

board = Board("my-board", size=(48, 30))
vbus, gnd, cc1, cc2 = usbc_power(board, ref="J1", cc_pulldowns="5.1k")
v3v3 = ams1117_ldo(board, ref="U1", vin=vbus, gnd=gnd, output_voltage=3.3,
                   in_caps=["10uF/0805", "10uF/0805"],
                   out_caps=["10uF/0805", "100nF/0402"])
led_indicator(board, ref_led="D1", ref_resistor="R3",
              vin=v3v3, gnd=gnd, color="red", current_ma=1.3)
pin_header(board, ref="J2", pins=2, label="3V3_OUT", nets=[v3v3, gnd])
for ref in ("H1", "H2", "H3", "H4"):
    m2_mounting_hole(board, ref=ref)
```

`build.py` runs that, applies positions from `layout.py`, and emits:
- `.kicad_pcb` (DRC-clean)
- `output/docs/schematic.svg` (via netlistsvg)
- `output/fab/bom/bom_jlcpcb.csv` (with LCSC numbers)

Optional modes (compose freely):
- `python build.py --datasheet` — adds 3D PCB renders (`kicad-cli pcb render`) and a Linear-Tech-styled datasheet PDF (ReportLab, purple/gold, 7+ sections, optional SPICE plots embedded)
- `python build.py --sim` — runs six SPICE pre-flight analyses (transient, load step, line/load reg, temperature sweep, Monte Carlo) via PySpice + ngspice; emits one PNG per analysis under `output/sim/`

Run KiBot/kicad-cli for gerbers, drill, CPL.

### Install

Must install into KiCad's bundled Python (the only one with `pcbnew`):

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" -m pip install -e `
  ".\python\circuit_toolkit"
```

For the v2 datasheet / sim modes, add the optional extras:

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" -m pip install -e `
  ".\python\circuit_toolkit[docs,sim]"
```

System tools:
- KiCad 10.0.1 (Windows verified)
- Node.js + `npm install -g netlistsvg`
- (optional, for `--sim`) ngspice — `winget install ngspice` on Windows

## Reference design

`usbc-3v3` — USB-C → 3.3V 800mA LDO board. Lives in its own repo. ~25-line `circuit.py` produces a DRC-clean board with full BOM, schematic SVG, and JLCPCB-ready fab outputs.

## Layout

```
kicad-claude-toolkit/
├── *.skill                       # 17 packaged AI skills
├── _skill_src/                   # editable skill sources (zipped into .skill files)
├── python/
│   └── circuit_toolkit/          # the Python package (pip-installable)
│       ├── pyproject.toml
│       ├── README.md
│       └── circuit_toolkit/
│           ├── core/             # Board, Component, Net
│           ├── blocks/           # @subcircuit functions
│           ├── builders/         # PCB, schematic, extract_layout, render, datasheet
│           ├── sim/              # PySpice pre-flight (transient, sweeps, Monte Carlo)
│           └── fab/              # BOM
├── bridge/                       # KiCad IPC API bridge (older)
├── CLAUDE.md
└── README.md
```

## License

MIT.

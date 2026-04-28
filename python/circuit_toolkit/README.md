# circuit_toolkit

Headless circuit description and KiCad PCB generation. Single Python source produces:
- DRC-clean `.kicad_pcb`
- Schematic SVG (via netlistsvg)
- BOM CSV with LCSC numbers
- KiBot-driven fab outputs

## Architecture

Three-file pattern per design:

```
your-board/
├── circuit.py    # topology — uses circuit_toolkit.blocks
├── layout.py     # positions + route hints
└── build.py      # orchestrator — calls circuit_toolkit.builders
```

`circuit.py` is tool-agnostic topology. `layout.py` is hand-edited or extracted from KiCad GUI via `extract_layout.py`. `build.py` ties them together.

## Install

Must install into KiCad's bundled Python (the one with `pcbnew`):

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" -m pip install -e `
  "C:\Users\<you>\OneDrive\Documents\GitHub\kicad-claude-toolkit\python\circuit_toolkit"
```

Also requires:
- Node.js + `netlistsvg` (`npm install -g netlistsvg`) for schematic generation
- KiCad 10.0.1 (Windows)

## Usage

```python
# circuit.py
from circuit_toolkit import Board
from circuit_toolkit.blocks import usbc_power, ams1117_ldo

def build():
    board = Board("my-board", size=(50, 30))
    vbus, gnd, cc1, cc2 = usbc_power(board, ref="J1", cc_pulldowns="5.1k")
    v3v3 = ams1117_ldo(board, ref="U1", vin=vbus, gnd=gnd)
    return board
```

See `designs/usbc-3v3/` for a complete example.

## Layers

| Layer | Tool affinity | Purpose |
|-------|---------------|---------|
| `blocks/` | Tool-agnostic | Reusable @subcircuit functions |
| `core/` | KiCad footprint vocabulary | Component, Net, Board classes |
| `builders/` | KiCad-specific | pcbnew + netlistsvg integration |
| `fab/` | KiCad-specific | KiBot + BOM packaging |

If you ever switch tools, only `builders/` and `fab/` need rewriting.

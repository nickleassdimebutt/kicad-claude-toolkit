"""PCB builder — reads Board + layout dict, writes .kicad_pcb via pcbnew.

Adapted from the proven usbc-3v3 build_board.py pattern.
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import pcbnew

from circuit_toolkit.core.board import Board


# Default KiCad footprint library location — checked in order, first hit wins.
# Windows install paths first (most common dev environment), then Linux apt
# defaults (CI runners, Ubuntu/Debian users). Override via the ``fp_base=``
# kwarg to ``build_pcb()``.
import os
import sys

_FP_CANDIDATES = [
    os.environ.get("KICAD_FOOTPRINT_DIR"),
    r"C:\Program Files\KiCad\10.0\share\kicad\footprints",
    r"C:\Program Files\KiCad\9.0\share\kicad\footprints",
    r"C:\Program Files\KiCad\8.0\share\kicad\footprints",
    "/usr/share/kicad/footprints",
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints",
]
DEFAULT_FP_BASE = next(
    (Path(p) for p in _FP_CANDIDATES if p and Path(p).is_dir()),
    Path(_FP_CANDIDATES[1]),  # Windows v10 fallback if nothing exists yet
)

LAYER_MAP = {
    "F.Cu":      pcbnew.F_Cu,
    "B.Cu":      pcbnew.B_Cu,
    "F.SilkS":   pcbnew.F_SilkS,
    "B.SilkS":   pcbnew.B_SilkS,
    "F.Mask":    pcbnew.F_Mask,
    "B.Mask":    pcbnew.B_Mask,
    "F.Paste":   pcbnew.F_Paste,
    "B.Paste":   pcbnew.B_Paste,
    "Edge.Cuts": pcbnew.Edge_Cuts,
}


def _mm(v: float):
    return pcbnew.FromMM(v)


def _vec(x: float, y: float):
    return pcbnew.VECTOR2I(_mm(x), _mm(y))


def _layer(name: str) -> int:
    if name not in LAYER_MAP:
        raise ValueError(f"Unknown layer {name!r}; known: {sorted(LAYER_MAP)}")
    return LAYER_MAP[name]


def _ensure_net(board, name: str):
    n = board.FindNet(name)
    if n is None:
        board.Add(pcbnew.NETINFO_ITEM(board, name))
        board.BuildConnectivity()
        n = board.FindNet(name)
    return n


def _find_kicad_io_plugin():
    """Get the KiCad-S-expr IO plugin in a way that works across KiCad 8/9/10.

    KiCad 10 renamed ``PluginFind`` → ``FindPlugin``; older versions (and at
    least one Ubuntu PPA build of v9) still expose the old name. Try both."""
    mgr = pcbnew.PCB_IO_MGR
    fmt = pcbnew.PCB_IO_MGR.KICAD_SEXP
    if hasattr(mgr, "FindPlugin"):
        return mgr.FindPlugin(fmt)
    if hasattr(mgr, "PluginFind"):
        return mgr.PluginFind(fmt)
    raise RuntimeError(
        "Cannot find a KiCad IO plugin: pcbnew.PCB_IO_MGR has neither "
        "FindPlugin (v10) nor PluginFind (v8/v9). Update KiCad."
    )


def _load_footprint(footprint_ref: str, fp_base: Path):
    """Load a KiCad footprint by 'Library:Name' reference."""
    if ":" not in footprint_ref:
        raise ValueError(f"Footprint ref must be 'Library:Name', got {footprint_ref!r}")
    lib, name = footprint_ref.split(":", 1)
    io = _find_kicad_io_plugin()
    fp = io.FootprintLoad(str(fp_base / f"{lib}.pretty"), name)
    if fp is None:
        raise RuntimeError(f"Footprint not found: {footprint_ref}")
    return fp


def _draw_outline_rect(board, x: float, y: float, w: float, h: float, line_width: float = 0.05):
    corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    for (x1, y1), (x2, y2) in zip(corners, corners[1:]):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetStart(_vec(x1, y1))
        seg.SetEnd(_vec(x2, y2))
        seg.SetWidth(_mm(line_width))
        board.Add(seg)


def _add_track(board, net, x1, y1, x2, y2, width: float, layer: str = "F.Cu"):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(_vec(x1, y1))
    t.SetEnd(_vec(x2, y2))
    t.SetWidth(_mm(width))
    t.SetLayer(_layer(layer))
    t.SetNet(net)
    board.Add(t)


def _add_via(board, net, x, y, drill: float = 0.4, size: float = 0.8):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(_vec(x, y))
    v.SetDrill(_mm(drill))
    v.SetWidth(_mm(size))
    v.SetNet(net)
    board.Add(v)


def _add_zone(board, net, layer: str, polygon: List[Tuple[float, float]],
              min_thickness: float = 0.25,
              pad_connection: str = "thermal"):
    zone = pcbnew.ZONE(board)
    zone.SetLayer(_layer(layer))
    zone.SetNet(net)
    pts = zone.Outline()
    pts.NewOutline()
    for x, y in polygon:
        pts.Append(_mm(x), _mm(y))
    zone.SetMinThickness(_mm(min_thickness))
    pad_conn_map = {
        "thermal": pcbnew.ZONE_CONNECTION_THERMAL,
        "full":    pcbnew.ZONE_CONNECTION_FULL,
        "none":    pcbnew.ZONE_CONNECTION_NONE,
    }
    zone.SetPadConnection(pad_conn_map[pad_connection])
    board.Add(zone)
    return zone


def _stub_pcb(path: Path) -> None:
    """Reset .kicad_pcb to a clean stub to prevent segfault from corrupt prior save."""
    path.write_text('(kicad_pcb (version 20260206) (generator "circuit_toolkit"))\n')


def _silence_cosmetic_drc(board) -> None:
    """Set cosmetic silk-related DRC checks to 'ignore' severity.

    Silkscreen overlap with copper or other silk is unavoidable on tightly-packed
    boards and is a fab/visual-only concern (the assembly house ignores it).
    Errors and unconnected-pad checks remain at error severity.
    """
    ds = board.GetDesignSettings()
    sev = ds.m_DRCSeverities
    # KiCad 10 DRC error codes (from drc_engine.h):
    #   DRCE_SILK_CLEARANCE = silk-over-silk overlap → ignore
    #   DRCE_SILK_OVER_COPPER = silk overlapping copper → ignore
    silk_codes = []
    for name in ("DRCE_SILK_CLEARANCE", "DRCE_SILK_EDGE_CLEARANCE",
                 "DRCE_OVERLAPPING_SILK", "DRCE_SILK_OVER_COPPER"):
        code = getattr(pcbnew, name, None)
        if code is not None:
            silk_codes.append(code)
    for code in silk_codes:
        try:
            sev[code] = pcbnew.SEVERITY_IGNORE
        except Exception:
            pass


def build_pcb(board: Board,
              positions: Dict[str, Tuple[float, float, float]],
              output: str | Path,
              tracks: Optional[List[Tuple]] = None,
              vias: Optional[List[Tuple]] = None,
              zones: Optional[List[Dict[str, Any]]] = None,
              pad_zone_full: Optional[List[Tuple[str, str]]] = None,
              ref_text_overrides: Optional[Dict[str, Tuple[float, float]]] = None,
              outline: Optional[Dict[str, Any]] = None,
              fp_base: Optional[Path] = None,
              reset_stub: bool = True) -> pcbnew.BOARD:
    """Generate a .kicad_pcb from a Board (topology) + layout dicts.

    Args:
        board: Board with components and nets
        positions: {ref: (x_mm, y_mm, rotation_deg)}
        output: path to .kicad_pcb to write
        tracks: list of (net_name, x1, y1, x2, y2, width_mm, layer_str)
        vias: list of (net_name, x, y, drill_mm, size_mm)
        zones: list of dicts {net, layer, polygon, min_thickness, pad_connection}
        pad_zone_full: list of (component_ref, pad_number) → SetLocalZoneConnection(FULL)
        ref_text_overrides: {ref: (x, y)} to override reference text position
        outline: dict {shape: 'rect', x, y, w, h} for board edge
        fp_base: KiCad footprint library root (defaults to KiCad 10 install)
        reset_stub: write stub file before LoadBoard (avoids segfault)

    Returns the loaded pcbnew.BOARD object after save.
    """
    output = Path(output)
    fp_base = fp_base or DEFAULT_FP_BASE
    tracks = tracks or []
    vias = vias or []
    zones = zones or []
    pad_zone_full = pad_zone_full or []
    ref_text_overrides = ref_text_overrides or {}

    if reset_stub:
        _stub_pcb(output)

    pcb = pcbnew.LoadBoard(str(output))
    _silence_cosmetic_drc(pcb)

    # Wipe any prior content (idempotent re-runs)
    for t in list(pcb.GetTracks()):  pcb.Remove(t)
    for f in list(pcb.GetFootprints()): pcb.Remove(f)
    for d in list(pcb.GetDrawings()): pcb.Remove(d)
    for z in list(pcb.Zones()): pcb.Remove(z)

    # ── Nets ──────────────────────────────────────────────────────────────
    net_objs = {name: _ensure_net(pcb, name) for name in board.nets}

    # ── Footprints ────────────────────────────────────────────────────────
    fp_by_ref: Dict[str, Any] = {}
    for comp in board.components:
        if comp.ref not in positions:
            raise KeyError(f"No position for {comp.ref} in layout")
        x, y, rot = positions[comp.ref]
        fp = _load_footprint(comp.footprint, fp_base)
        fp.SetReference(comp.ref)
        fp.SetValue(comp.value)
        fp.SetPosition(_vec(x, y))
        if rot:
            fp.SetOrientationDegrees(rot)
        if comp.ref in ref_text_overrides:
            rx, ry = ref_text_overrides[comp.ref]
            # Reference text position is local to footprint; here we set absolute by offset
            # The override is interpreted as absolute board-frame position
            fp.Reference().SetPosition(_vec(rx, ry))
        # Set LCSC field if present (and hide so it doesn't clutter silkscreen)
        if comp.lcsc:
            try:
                fp.SetField("LCSC", comp.lcsc)
                # SetField adds as visible by default — hide
                for field in fp.GetFields():
                    if field.GetName() == "LCSC":
                        field.SetVisible(False)
                        break
            except Exception:
                pass  # KiCad version difference; ignore silently
        pcb.Add(fp)
        fp_by_ref[comp.ref] = fp

    pcb.BuildConnectivity()

    # ── Net assignments on pads ──────────────────────────────────────────
    for net_name, net in board.nets.items():
        netinfo = net_objs[net_name]
        for pad_ref in net.pads:
            fp = fp_by_ref.get(pad_ref.component_ref)
            if fp is None or not pad_ref.pad_number:
                continue
            # A footprint may have multiple pads sharing one number (e.g. the
            # SOT-223 tab is also pad 2; the USB-C shield uses 4 thru-holes
            # all named "SH" in KiCad 10 but "S1" in KiCad 9). Pad numbers
            # may also be specified as a pipe-separated alias list to bridge
            # cross-version library naming — the first alternate that
            # matches *any* pad on the footprint wins, and every pad with
            # that number gets the net.
            alternates = pad_ref.pad_number.split("|") if "|" in pad_ref.pad_number \
                else [pad_ref.pad_number]
            assigned = False
            for alt in alternates:
                for p in fp.Pads():
                    if p.GetNumber() == alt:
                        p.SetNet(netinfo)
                        assigned = True
                if assigned:
                    break  # don't fall through to next alias once one resolves
            if not assigned:
                available = sorted({str(p.GetNumber()) for p in fp.Pads()})
                raise RuntimeError(
                    f"Could not find pad {pad_ref.pad_number!r} on "
                    f"{pad_ref.component_ref}; available pads: {available}"
                )

    # ── Pad zone-connection overrides ─────────────────────────────────────
    for ref, pad_num in pad_zone_full:
        fp = fp_by_ref.get(ref)
        if fp is None:
            continue
        for p in fp.Pads():
            if p.GetNumber() == pad_num:
                p.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)

    pcb.BuildConnectivity()

    # ── Tracks ────────────────────────────────────────────────────────────
    for entry in tracks:
        net_name, x1, y1, x2, y2, width, layer = entry
        _add_track(pcb, net_objs[net_name], x1, y1, x2, y2, width, layer)

    # ── Vias ──────────────────────────────────────────────────────────────
    for entry in vias:
        net_name, x, y, drill, size = entry
        _add_via(pcb, net_objs[net_name], x, y, drill, size)

    # ── Zones ─────────────────────────────────────────────────────────────
    for z in zones:
        _add_zone(pcb,
                  net_objs[z["net"]],
                  z["layer"],
                  z["polygon"],
                  min_thickness=z.get("min_thickness", 0.25),
                  pad_connection=z.get("pad_connection", "thermal"))

    if zones:
        filler = pcbnew.ZONE_FILLER(pcb)
        filler.Fill(pcb.Zones())

    # ── Outline ───────────────────────────────────────────────────────────
    if outline:
        if outline.get("shape") == "rect":
            _draw_outline_rect(pcb, outline["x"], outline["y"],
                               outline["w"], outline["h"],
                               outline.get("line_width", 0.05))
        else:
            raise ValueError(f"Unsupported outline shape: {outline.get('shape')!r}")
    else:
        # Default: bounding box from board.size
        _draw_outline_rect(pcb, 0, 0, board.size[0], board.size[1])

    pcb.Save(str(output))
    return pcb

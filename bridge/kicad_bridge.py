"""
kicad_bridge.py - KiCad 10 IPC API Bridge
Connects Claude Code to KiCad 10 via the official kicad-python IPC API.

SETUP: pip install kicad-python
ENABLE: KiCad Preferences -> Plugins -> Enable IPC API

USAGE:
    python bridge/kicad_bridge.py --ping
    python bridge/kicad_bridge.py --info
    python bridge/kicad_bridge.py --list-footprints
    python bridge/kicad_bridge.py --list-nets
    python bridge/kicad_bridge.py --move U1 50.0 30.0
    python bridge/kicad_bridge.py --run-script my_script.py
"""

import sys
import os
import argparse
import tempfile
import traceback


def get_socket_path():
    if "KICAD_API_SOCKET" in os.environ:
        return os.environ["KICAD_API_SOCKET"]
    if sys.platform == "win32":
        temp = tempfile.gettempdir()
        pipe_path = os.path.join(temp, "kicad", "api.sock")
        return f"ipc://{pipe_path}"
    return "ipc:///tmp/kicad/api.sock"


def connect():
    try:
        import kipy
    except ImportError:
        print("ERROR: kicad-python not installed.")
        print("  Run: pip install kicad-python")
        sys.exit(1)

    socket_path = get_socket_path()
    try:
        client = kipy.KiCad(
            socket_path=socket_path,
            client_name="claude-kicad-bridge",
            timeout_ms=5000,
        )
        return client
    except Exception as e:
        print(f"ERROR: Could not connect to KiCad IPC API.")
        print(f"  Socket: {socket_path}")
        print(f"  Detail: {e}")
        print()
        print("  Check:")
        print("    1. KiCad 10 is open")
        print("    2. IPC API enabled: Preferences -> Plugins -> Enable IPC API")
        sys.exit(1)


def cmd_ping():
    try:
        client = connect()
        version = client.get_version()
        print(f"Connected to KiCad {version.major}.{version.minor}.{version.patch}")
        return True
    except SystemExit:
        return False
    except Exception as e:
        print(f"Ping failed: {e}")
        return False


def cmd_info():
    client = connect()
    try:
        board = client.get_board()
        filename = board.get_filename()
        print(f"Board: {filename or '(unsaved)'}")
        try:
            bbox = board.get_board_bbox()
            w = (bbox.max.x - bbox.min.x) / 1e6
            h = (bbox.max.y - bbox.min.y) / 1e6
            print(f"Size:  {w:.2f} x {h:.2f} mm")
        except Exception:
            print("Size:  (no board outline found)")
        footprints = list(board.get_footprints())
        print(f"Parts: {len(footprints)} footprints")
        try:
            nets = list(board.get_nets())
            print(f"Nets:  {len(nets)}")
        except Exception:
            pass
    except Exception as e:
        print(f"ERROR reading board: {e}")
        print("  Make sure a PCB file is open in the PCB Editor.")


def cmd_list_footprints():
    client = connect()
    try:
        board = client.get_board()
        footprints = list(board.get_footprints())
        if not footprints:
            print("No footprints on board.")
            return
        print(f"{'Ref':<10} {'Value':<20} {'X (mm)':<10} {'Y (mm)':<10} Layer")
        print("-" * 65)
        for fp in sorted(footprints, key=lambda f: f.reference):
            pos = fp.position
            x_mm = pos.x / 1e6
            y_mm = pos.y / 1e6
            layer = "Front" if fp.layer == 0 else "Back"
            print(f"{fp.reference:<10} {fp.value:<20} {x_mm:<10.3f} {y_mm:<10.3f} {layer}")
    except Exception as e:
        print(f"ERROR: {e}")
        traceback.print_exc()


def cmd_list_nets():
    client = connect()
    try:
        board = client.get_board()
        nets = list(board.get_nets())
        print(f"{'Net':<5} Name")
        print("-" * 40)
        for net in sorted(nets, key=lambda n: n.number):
            print(f"{net.number:<5} {net.name}")
    except Exception as e:
        print(f"ERROR: {e}")


def cmd_move_footprint(reference, x_mm, y_mm):
    client = connect()
    try:
        board = client.get_board()
        footprints = list(board.get_footprints())
        target = next((fp for fp in footprints if fp.reference == reference), None)
        if not target:
            print(f"ERROR: '{reference}' not found.")
            return
        from kipy.common_types import Vector2
        target.position = Vector2(x=int(x_mm * 1e6), y=int(y_mm * 1e6))
        board.update_footprint(target)
        print(f"Moved {reference} to ({x_mm:.3f}, {y_mm:.3f}) mm")
    except Exception as e:
        print(f"ERROR: {e}")
        traceback.print_exc()


def cmd_run_script(script_path):
    client = connect()
    try:
        board = client.get_board()
    except Exception as e:
        print(f"ERROR getting board: {e}")
        return
    try:
        with open(script_path) as f:
            code = f.read()
        namespace = {"client": client, "board": board, "kipy": __import__("kipy"), "print": print}
        exec(code, namespace)
    except FileNotFoundError:
        print(f"ERROR: Script not found: {script_path}")
    except Exception as e:
        print(f"ERROR: {e}")
        traceback.print_exc()


class KiCadSession:
    """Context manager for Claude-generated scripts."""
    def __init__(self):
        self.client = None
        self.board = None

    def __enter__(self):
        self.client = connect()
        self.board = self.client.get_board()
        return self

    def __exit__(self, *args):
        pass

    def mm(self, val):
        return int(val * 1e6)

    def to_mm(self, val):
        return val / 1e6

    def find_footprint(self, reference):
        for fp in self.board.get_footprints():
            if fp.reference == reference:
                return fp
        raise ValueError(f"Footprint '{reference}' not found")


def main():
    parser = argparse.ArgumentParser(description="KiCad 10 IPC Bridge")
    parser.add_argument("--ping", action="store_true")
    parser.add_argument("--info", action="store_true")
    parser.add_argument("--list-footprints", action="store_true")
    parser.add_argument("--list-nets", action="store_true")
    parser.add_argument("--move", nargs=3, metavar=("REF", "X", "Y"))
    parser.add_argument("--run-script", metavar="FILE")
    args = parser.parse_args()

    if args.ping:               cmd_ping()
    elif args.info:             cmd_info()
    elif args.list_footprints:  cmd_list_footprints()
    elif args.list_nets:        cmd_list_nets()
    elif args.move:             cmd_move_footprint(args.move[0], float(args.move[1]), float(args.move[2]))
    elif args.run_script:       cmd_run_script(args.run_script)
    else:                       parser.print_help()


if __name__ == "__main__":
    main()

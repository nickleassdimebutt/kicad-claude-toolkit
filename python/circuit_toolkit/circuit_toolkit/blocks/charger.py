"""Battery-charger blocks."""
from __future__ import annotations
from typing import Optional, Tuple

from circuit_toolkit.core.board import Board
from circuit_toolkit.core.component import Component
from circuit_toolkit.core.net import Net
from circuit_toolkit.blocks.decoupling import add_cap
from circuit_toolkit.blocks.scope import block_scope


# Charge-current → ohm mapping for TP4056 PROG pin (Iprog = 1200 / Rprog).
# Snapped to E12 values that JLCPCB stocks as basic parts.
_TP4056_PROG_R = {
    100:  "12k",     # 100 mA
    200:  "6k2",     # 200 mA — closest E12
    300:  "4k",      # 300 mA — approx
    400:  "3k",      # 400 mA
    500:  "2k4",     # 500 mA — 2.4k = 500 mA exactly
    700:  "1k7",     # 700 mA — closest
    1000: "1k2",     # 1 A — 1.2k = 1 A exactly
}


def tp4056_charger(board: Board,
                   ref: str = "U1",
                   vbus: Optional[Net] = None,
                   gnd: Optional[Net] = None,
                   battery_pos: Optional[Net] = None,
                   charge_current_ma: int = 500,
                   prog_resistor_ref: str = "R10",
                   in_cap_ref: str = "C10",
                   bat_cap_ref: str = "C11",
                   chrg_led: bool = False,
                   stdby_led: bool = False,
                   chrg_led_ref: str = "D10",
                   stdby_led_ref: str = "D11",
                   chrg_led_resistor_ref: str = "R11",
                   stdby_led_resistor_ref: str = "R12",
                   ) -> Tuple[Net, Net, Net]:
    """Single-cell Li-ion linear charger via TP4056 (SOP-8).

    Topology added:
        TP4056 (U) — 8-pin charger IC
        R_prog — programming resistor on PROG pin (sets I_charge)
        C_in   — 10 µF input bypass on VCC
        C_bat  — 10 µF battery cap on BAT pin
        D_chrg + R_chrg (optional) — red status LED, on while charging
        D_stdby + R_stdby (optional) — blue status LED, on at standby
        TEMP, CE — tied to GND for default behaviour (no NTC, always-on)

    Args:
        ref: TP4056 reference designator (e.g. "U1").
        vbus: USB / 5V input net (created as ``"VBUS"`` if None).
        gnd: ground net (created as ``"GND"`` if None).
        battery_pos: battery positive net (created as ``"BAT"`` if None).
        charge_current_ma: target Iprog — must be in the snapped set
                            {100, 200, 300, 400, 500, 700, 1000} mA.
        chrg_led / stdby_led: also add the status LEDs (recommended).

    Returns ``(vbus, gnd, battery_pos)`` — same nets that were passed
    in, or freshly created ones, so callers can chain easily.
    """
    if charge_current_ma not in _TP4056_PROG_R:
        raise ValueError(
            f"charge_current_ma {charge_current_ma} not in supported set "
            f"{sorted(_TP4056_PROG_R.keys())} — pick the closest")

    with block_scope(board, "charger"):
        if vbus is None:        vbus = board.net("VBUS")
        if gnd is None:         gnd = board.net("GND")
        if battery_pos is None: battery_pos = board.net("BAT")

        # TP4056 SOP-8 pin map (per Topcell datasheet)
        u = Component(
            ref=ref,
            value="TP4056",
            footprint="Package_SO:SOP-8_3.76x4.96mm_P1.27mm",
            lcsc="C16581", lcsc_basic=True,
            pin_map={
                "TEMP":  "1",
                "PROG":  "2",
                "GND":   "3",
                "VCC":   "4",
                "BAT":   "5",
                "STDBY": "6",
                "CHRG":  "7",
                "CE":    "8",
            },
            description="TP4056 1A Li-ion linear charger (SOP-8)",
        )
        board.add(u)
        board.connect(vbus,        u, "VCC")
        board.connect(gnd,         u, "GND")
        board.connect(battery_pos, u, "BAT")
        # Defaults: tie TEMP to GND (no NTC), CE to VCC (always enabled).
        board.connect(gnd,  u, "TEMP")
        board.connect(vbus, u, "CE")

        # Programming resistor — PROG pin to GND
        prog_value = _TP4056_PROG_R[charge_current_ma]
        rp = Component(
            ref=prog_resistor_ref,
            value=prog_value,
            footprint="Resistor_SMD:R_0402_1005Metric",
            lcsc=None, lcsc_basic=False,
            pin_map={"1": "1", "2": "2"},
            description=f"Resistor {prog_value} 0402 (TP4056 charge-current set)",
        )
        board.add(rp)
        n_prog = board.net(f"N_{ref}_PROG")
        board.connect(n_prog, u, "PROG")
        board.connect(n_prog, rp, "1")
        board.connect(gnd,    rp, "2")

        # Decoupling: 10 µF on VCC (input) and BAT (output)
        add_cap(board, in_cap_ref,  "10uF/0805", vbus,        gnd)
        add_cap(board, bat_cap_ref, "10uF/0805", battery_pos, gnd)

        # Status LEDs — open-drain pull-down to indicate state
        if chrg_led:
            n_chrg = board.net(f"N_{ref}_CHRG")
            board.connect(n_chrg, u, "CHRG")
            led = Component(
                ref=chrg_led_ref,
                value="RED",
                footprint="LED_SMD:LED_0805_2012Metric",
                lcsc="C2286", lcsc_basic=True,
                pin_map={"K": "1", "A": "2", "1": "1", "2": "2"},
                description="LED 0805 red — charging indicator",
            )
            board.add(led)
            board.connect(n_chrg, led, "K")  # cathode → CHRG (open-drain low when charging)
            n_chrg_a = board.net(f"N_{ref}_CHRG_A")
            board.connect(n_chrg_a, led, "A")
            r = Component(
                ref=chrg_led_resistor_ref,
                value="1k",
                footprint="Resistor_SMD:R_0402_1005Metric",
                lcsc="C21190", lcsc_basic=True,
                pin_map={"1": "1", "2": "2"},
                description="Resistor 1k 0402 (CHRG LED current limit)",
            )
            board.add(r)
            board.connect(vbus,     r, "1")
            board.connect(n_chrg_a, r, "2")

        if stdby_led:
            n_stdby = board.net(f"N_{ref}_STDBY")
            board.connect(n_stdby, u, "STDBY")
            led = Component(
                ref=stdby_led_ref,
                value="BLUE",
                footprint="LED_SMD:LED_0805_2012Metric",
                lcsc="C72041", lcsc_basic=True,
                pin_map={"K": "1", "A": "2", "1": "1", "2": "2"},
                description="LED 0805 blue — standby/done indicator",
            )
            board.add(led)
            board.connect(n_stdby, led, "K")
            n_stdby_a = board.net(f"N_{ref}_STDBY_A")
            board.connect(n_stdby_a, led, "A")
            r = Component(
                ref=stdby_led_resistor_ref,
                value="1k",
                footprint="Resistor_SMD:R_0402_1005Metric",
                lcsc="C21190", lcsc_basic=True,
                pin_map={"1": "1", "2": "2"},
                description="Resistor 1k 0402 (STDBY LED current limit)",
            )
            board.add(r)
            board.connect(vbus,      r, "1")
            board.connect(n_stdby_a, r, "2")

        return vbus, gnd, battery_pos

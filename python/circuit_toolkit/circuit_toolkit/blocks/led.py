"""LED indicator block."""
from __future__ import annotations

from circuit_toolkit.core.board import Board
from circuit_toolkit.core.component import Component
from circuit_toolkit.core.net import Net
from circuit_toolkit.blocks.scope import block_scope


# Approximate forward voltages by color for current calculation
LED_VF = {
    "red":    2.0,
    "green":  2.1,
    "yellow": 2.1,
    "orange": 2.0,
    "blue":   3.0,
    "white":  3.2,
}

# 0805 LEDs at JLC
LED_LCSC = {
    "red":    ("C2286",  True),
    "green":  ("C72043", True),
    "yellow": ("C72038", True),
    "blue":   ("C72041", True),
    "white":  ("C2290",  True),
    "orange": ("C72042", False),
}


def _nearest_resistor(value_ohms: float) -> str:
    """Snap to E12 series (common JLC stock values)."""
    e12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]
    if value_ohms <= 0:
        return "0"
    decade = 10 ** int(f"{value_ohms:e}".split("e")[1])
    norm = value_ohms / decade
    nearest = min(e12, key=lambda x: abs(x - norm))
    val = nearest * decade
    if val < 1000:
        return f"{int(val)}" if val == int(val) else f"{val:.1f}"
    return f"{val/1000:g}k"


def led_indicator(board: Board,
                  ref_led: str, ref_resistor: str,
                  vin: Net, gnd: Net,
                  color: str = "red",
                  current_ma: float = 1.5,
                  supply_voltage: float = 3.3,
                  resistor_value: str | None = None,
                  led_anode_net_name: str | None = None) -> tuple[Component, Component]:
    """LED + current-limiting resistor in series between vin and gnd.

    Topology: vin → R → (intermediate net) → LED anode, LED cathode → gnd

    Args:
        ref_led: LED reference (e.g. "D1")
        ref_resistor: resistor reference (e.g. "R3")
        vin: high-side net
        gnd: ground net
        color: red/green/yellow/blue/white/orange
        current_ma: target LED current
        supply_voltage: used to compute resistor value
        resistor_value: optional override; otherwise auto-computed and snapped to E12

    Returns (led_component, resistor_component).
    """
    with block_scope(board, "led"):
        if color not in LED_VF:
            raise ValueError(f"Unknown LED color {color!r}")

        if resistor_value is None:
            r_ohms = (supply_voltage - LED_VF[color]) / (current_ma / 1000.0)
            resistor_value = _nearest_resistor(r_ohms)

        if led_anode_net_name is None:
            led_anode_net_name = f"N_{ref_led}"
        n_anode = board.net(led_anode_net_name)

        led_lcsc, led_basic = LED_LCSC[color]
        led = Component(
            ref=ref_led,
            value=color.upper(),
            footprint="LED_SMD:LED_0805_2012Metric",
            lcsc=led_lcsc, lcsc_basic=led_basic,
            pin_map={"K": "1", "A": "2", "1": "1", "2": "2"},
            description=f"LED 0805 {color}",
        )
        board.add(led)
        board.connect(gnd,     led, "K")
        board.connect(n_anode, led, "A")

        r = Component(
            ref=ref_resistor,
            value=resistor_value,
            footprint="Resistor_SMD:R_0402_1005Metric",
            lcsc="C21190" if resistor_value == "1k" else None,  # 1kΩ basic
            lcsc_basic=(resistor_value == "1k"),
            pin_map={"1": "1", "2": "2"},
            description=f"Resistor {resistor_value} 0402",
        )
        board.add(r)
        board.connect(vin,     r, "1")
        board.connect(n_anode, r, "2")

        return led, r

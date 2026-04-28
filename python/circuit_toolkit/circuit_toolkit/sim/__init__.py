"""Headless SPICE pre-flight for circuit_toolkit boards.

Public API: ``simulate_*`` analyses + the ``simulate_all`` convenience.
Each analysis takes a Board and a target output directory, emits a PNG.
"""
from circuit_toolkit.sim.runner import (
    simulate_transient,
    simulate_load_step,
    simulate_line_regulation,
    simulate_load_regulation,
    simulate_temperature_sweep,
    simulate_monte_carlo,
    simulate_all,
)

__all__ = [
    "simulate_transient",
    "simulate_load_step",
    "simulate_line_regulation",
    "simulate_load_regulation",
    "simulate_temperature_sweep",
    "simulate_monte_carlo",
    "simulate_all",
]

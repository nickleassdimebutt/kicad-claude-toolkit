"""SPICE backend registry.

Each backend implements the ``Backend`` protocol (``backends.base.Backend``).
``default_backend()`` returns the one we ship with — currently ngspice via
subprocess. Future RF work will add ``QucsBackend`` / ``XYCEBackend`` /
``ADSBackend`` here without touching the runner.
"""
from circuit_toolkit.sim.backends.base import Backend, BackendError, SimResult
from circuit_toolkit.sim.backends.ngspice import NgSpiceBackend


def default_backend() -> Backend:
    """Return the toolkit's default backend instance (ngspice subprocess)."""
    return NgSpiceBackend()


__all__ = ["Backend", "BackendError", "SimResult",
           "NgSpiceBackend", "default_backend"]

"""Context manager that auto-tags components added inside a block call.

Block functions wrap their body in ``with block_scope(board, "usbc_power"):``
and every Component added through ``board.add(...)`` while the scope is
open gets ``block_id="usbc_power"`` set automatically. This lets the
hierarchical schematic builder partition the board into per-block detail
sheets without each block having to set ``block_id`` manually on every
Component it constructs.

Implementation: temporarily wraps Board.add to inject the tag, restores
the original method on exit. Reentrant; nested scopes set the *outermost*
block_id on a component (the leaf-block tag wins, but if a parent block
calls a child block the child's components get the parent's tag — that's
the IPC-style hierarchical containment). Components already tagged before
the scope was entered are left alone.
"""
from __future__ import annotations
from contextlib import contextmanager

from circuit_toolkit.core.board import Board
from circuit_toolkit.core.component import Component


@contextmanager
def block_scope(board: Board, name: str):
    """Auto-tag every Component added to `board` inside the with-block."""
    original_add = board.add

    def tagging_add(component: Component) -> Component:
        if component.block_id is None:
            component.block_id = name
        return original_add(component)

    board.add = tagging_add  # type: ignore[method-assign]
    try:
        yield
    finally:
        board.add = original_add  # type: ignore[method-assign]

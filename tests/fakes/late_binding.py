"""Test helper for pre-resolved ``LateBinding`` instances.

Production wiring uses ``LateBinding`` to defer a forward reference across a
producer/consumer construction cycle (see ``lib/late_binding.py``). A test
building the consumer directly has no such cycle — the fake/value already
exists — so it only needs a binding that is immediately ``set()``.
"""

from __future__ import annotations

from typing import TypeVar

from lib.late_binding import LateBinding

T = TypeVar("T")


def bound(value: T, *, name: str = "test_binding") -> LateBinding[T]:
    """Return a ``LateBinding`` already resolved to *value*."""
    binding: LateBinding[T] = LateBinding(name)
    binding.set(lambda: value)
    return binding

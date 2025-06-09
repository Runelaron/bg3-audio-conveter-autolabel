"""Utility for choosing the best available progress bar."""

from __future__ import annotations

from typing import Callable, Iterable, Iterator

from config import PROGRESS_BAR_MODE


def _basic(items: Iterable) -> Iterator[tuple[int, int, object]]:
    items = list(items)
    total = len(items)
    for idx, item in enumerate(items, 1):
        print(f"\r  {idx}/{total}", end="", flush=True)
        yield idx, total, item
    print()


def _alive_bar() -> Callable[[Iterable], Iterator[tuple[int, int, object]]]:
    import alive_progress  # type: ignore

    def alive(items: Iterable) -> Iterator[tuple[int, int, object]]:
        seq = list(items)
        total = len(seq)
        with alive_progress.alive_bar(total) as bar:
            for idx, item in enumerate(seq, 1):
                yield idx, total, item
                bar()

    return alive


def make_bar() -> Callable[[Iterable], Iterator[tuple[int, int, object]]]:
    """Select a progress-bar generator based on availability and preference.

    Returns:
        A generator that yields ``(index, total, item)`` while updating the
        chosen progress bar implementation.
    """
    if PROGRESS_BAR_MODE in {"auto", "alive"}:
        try:
            return _alive_bar()
        except ModuleNotFoundError:
            pass
    return _basic


bar = make_bar()

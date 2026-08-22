"""
search.py — incremental search & find/replace-all. OWNER: Person C.
Phase 3 target. stdlib `re` only.

Suggested contract against buffer.Buffer:
  - search(buf, pattern, start=(y, x), regex=False) -> Optional[(y, x, y, x)]
      returns the span of the next match after `start`, wrapping around.
  - replace_all(buf, pattern, repl, regex=False) -> int
      mutates buf.lines in place, returns number of replacements.
      Remember to call buf.undo_mgr.checkpoint(...) BEFORE mutating so
      replace-all is a single undo step, not one per replacement.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from .buffer import Buffer

Span = Tuple[int, int, int, int]  # start_y, start_x, end_y, end_x


def search(
    buf: Buffer, pattern: str, start: Tuple[int, int] = (0, 0), regex: bool = False
) -> Optional[Span]:
    # TODO(Person C): implement incremental forward search with wraparound.
    raise NotImplementedError


def replace_all(buf: Buffer, pattern: str, repl: str, regex: bool = False) -> int:
    # TODO(Person C): implement find/replace-all as a single undo step.
    raise NotImplementedError

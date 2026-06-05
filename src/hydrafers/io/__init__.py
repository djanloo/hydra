"""HydraFERS output-file layer (``hydrafers.io``).

Pure Python (numpy only); MUST NOT import ``pyfers`` — see CONTRACT.md §0.

Public API (CONTRACT.md §3):

* :class:`EventWriter`  — buffered binary writer for the new versioned format.
* :class:`EventReader`  — reads the new format AND the legacy Janus list ``.dat``.
* :class:`FileHeader`   — self-describing file header dataclass.

Event dicts handled by this layer have the same shape ``pyfers.get_event``
returns (CONTRACT.md §1): the writer serializes the per-mode fields and the
reader yields dicts of the identical shape. The on-disk byte layout is
documented in ``docs/FILE_FORMAT.md``.
"""

from __future__ import annotations

from .formats import FileHeader, FORMAT_VERSION, MAGIC, DEFAULT_BUFFER_BYTES
from .reader import EventReader
from .writer_binary import EventWriter

__all__ = [
    "EventWriter",
    "EventReader",
    "FileHeader",
    "FORMAT_VERSION",
    "MAGIC",
    "DEFAULT_BUFFER_BYTES",
]

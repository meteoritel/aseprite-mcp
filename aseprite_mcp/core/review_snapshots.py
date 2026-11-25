"""Session-local RGBA baselines for frame review."""

from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from secrets import token_urlsafe

from mcp.server.mcpserver.exceptions import ToolError

from .contracts import Region

MAX_REVIEW_SNAPSHOTS = 32
MAX_REVIEW_SNAPSHOT_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ReviewBaseline:
    filename: str
    frame: int
    region: Region
    layer_paths: tuple[tuple[str, ...], ...]
    composite: bytes
    cels: tuple[bytes, ...]  # Empty bytes represent a missing cel.

    @property
    def rgba_bytes(self) -> int:
        return len(self.composite) + sum(map(len, self.cels))


class ReviewSnapshots:
    def __init__(self) -> None:
        self._snapshots: OrderedDict[str, ReviewBaseline] = OrderedDict()
        self._rgba_bytes = 0

    def get(self, snapshot_id: str) -> ReviewBaseline:
        try:
            return self._snapshots[snapshot_id]
        except KeyError as exc:
            raise ToolError("Unknown or expired before_id. Review the same target again to create a new snapshot.") from exc

    @contextmanager
    def record(self, baseline: ReviewBaseline):
        size = baseline.rgba_bytes
        if size > MAX_REVIEW_SNAPSHOT_BYTES:
            yield None
            return
        snapshot_id = token_urlsafe(12)
        # Register only after the caller successfully constructs the response.
        yield snapshot_id
        while (len(self._snapshots) >= MAX_REVIEW_SNAPSHOTS
               or self._rgba_bytes + size > MAX_REVIEW_SNAPSHOT_BYTES):
            _, oldest = self._snapshots.popitem(last=False)
            self._rgba_bytes -= oldest.rgba_bytes
        self._snapshots[snapshot_id] = baseline
        self._rgba_bytes += size

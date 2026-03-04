"""DB->Relay bridge — polls SQLite, publishes changes to Relay.

The bridge detects changes via lightweight fingerprints (counts + max rowids)
and publishes to Relay subjects that SSE handlers subscribe to.

Relay protocol: any object with a `publish(subject: str, data: str)` method.
This allows testing without Stario installed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from remora_demo.web.graph.layout import ForceLayout
from remora_demo.web.graph.state import GraphState

logger = logging.getLogger("remora.graph.bridge")


class RelayProtocol(Protocol):
    """Minimal interface for the relay — just publish."""

    def publish(self, subject: str, data: str) -> None: ...


class DBBridge:
    """Polls the shared SQLite DB and publishes changes to the in-process Relay.

    Change detection uses fingerprinting: a lightweight query that returns
    counts and max rowids for each table. When the fingerprint changes,
    we determine what changed and publish to the appropriate Relay subject.
    """

    def __init__(
        self,
        state: GraphState,
        layout: ForceLayout,
        relay: RelayProtocol,
        poll_interval: float = 0.3,
    ) -> None:
        self.state = state
        self.layout = layout
        self.relay = relay
        self.poll_interval = poll_interval
        self._last_fp: dict[str, str] = {}

    async def run(self) -> None:
        """Main polling loop. Runs until cancelled."""
        logger.info("DBBridge started, polling every %.1fs", self.poll_interval)
        while True:
            try:
                await self._poll_once()
            except Exception:
                logger.debug("Bridge poll error", exc_info=True)
            await asyncio.sleep(self.poll_interval)

    async def _poll_once(self) -> list[str]:
        """Check each table's fingerprint and publish changes.

        Returns list of published subjects (for testing).
        """
        fp = await asyncio.to_thread(self._read_fingerprints)

        changed_subjects: list[str] = []

        # Topology change: nodes or edges added/removed
        if fp.get("nodes") != self._last_fp.get("nodes") or fp.get("edges") != self._last_fp.get("edges"):
            # Re-read snapshot and update layout
            snapshot = await asyncio.to_thread(self.state.read_snapshot)
            self.layout.set_graph(
                [
                    {
                        "id": n.get("remora_id", n.get("id", "")),
                        "node_type": n.get("node_type", "function"),
                    }
                    for n in snapshot.nodes
                ],
                snapshot.edges,
            )
            self.layout.step(50)  # Incremental settle
            changed_subjects.append("graph.topology")

        # Status change
        if fp.get("node_status") != self._last_fp.get("node_status"):
            changed_subjects.append("graph.status")

        # Cursor change
        if fp.get("cursor") != self._last_fp.get("cursor"):
            changed_subjects.append("graph.cursor")

        # New events
        if fp.get("events") != self._last_fp.get("events"):
            changed_subjects.append("graph.events")

        self._last_fp = fp

        for subject in changed_subjects:
            self.relay.publish(subject, "changed")

        return changed_subjects

    def _read_fingerprints(self) -> dict[str, str]:
        """Read lightweight fingerprints from the DB."""
        conn = self.state._get_conn()
        cursor = conn.cursor()
        fp: dict[str, str] = {}

        try:
            cursor.execute("SELECT count(*), max(rowid) FROM nodes")
            row = cursor.fetchone()
            fp["nodes"] = f"{row[0]}:{row[1]}"

            # Separate fingerprint for status changes
            cursor.execute(
                "SELECT group_concat(status) FROM (SELECT status FROM nodes WHERE status != 'orphaned' ORDER BY id)"
            )
            fp["node_status"] = str(cursor.fetchone()[0])

            cursor.execute("SELECT count(*), max(rowid) FROM edges")
            row = cursor.fetchone()
            fp["edges"] = f"{row[0]}:{row[1]}"

            cursor.execute("SELECT timestamp FROM cursor_focus WHERE id = 1")
            row = cursor.fetchone()
            fp["cursor"] = str(row[0]) if row else "0"

            cursor.execute("SELECT max(rowid) FROM events")
            fp["events"] = str(cursor.fetchone()[0])
        except Exception:
            pass  # Table may not exist yet

        return fp

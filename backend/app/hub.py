"""Fan-out of messages to WebSocket clients. Publishing never waits on a client."""
from __future__ import annotations

import asyncio
from collections.abc import Iterable

CLIENT_BACKLOG = 2000  # messages a client may fall behind before it is cut loose


class Hub:
    def __init__(self) -> None:
        self.clients: set[asyncio.Queue] = set()

    def join(self, snapshot: dict) -> asyncio.Queue:
        """A new client's queue, with the snapshot as its first message."""
        queue: asyncio.Queue = asyncio.Queue(CLIENT_BACKLOG)
        queue.put_nowait(snapshot)
        self.clients.add(queue)
        return queue

    def leave(self, queue: asyncio.Queue) -> None:
        self.clients.discard(queue)

    def publish(self, messages: Iterable[dict]) -> None:
        for message in messages:
            for queue in list(self.clients):
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    # A stalled client: drop it. None tells its sender to close; it reconnects to a fresh snapshot.
                    self.clients.discard(queue)
                    while not queue.empty():
                        queue.get_nowait()
                    queue.put_nowait(None)

"""Redis Streams transport for durable job IDs. The ledger owns delivery state."""

import os
import time
from uuid import uuid4


STREAM = "trinetra:soc:events"
GROUP = "trinetra-soc"


class Streams:
    def __init__(self, client):
        self.client = client
        self.consumer = uuid4().hex
        self.ready = False

    def ensure_group(self):
        if not self.ready:
            try:
                self.client.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
            except Exception as error:
                if not str(error).startswith("BUSYGROUP"):
                    raise
            self.ready = True

    def publish(self, ledger, now):
        self.ensure_group()
        with ledger.tx() as db:
            rows = db.execute("SELECT id FROM soc_jobs WHERE published_at IS NULL AND status='pending' "
                              "AND available_at<=? ORDER BY available_at,id LIMIT 16", (now,)).fetchall()
        for row in rows:
            self.client.xadd(STREAM, {"job_id": row["id"], "schema_version": "1"}, maxlen=4096)
            with ledger.tx(write=True) as db:
                db.execute("UPDATE soc_jobs SET published_at=? WHERE id=? AND published_at IS NULL",
                           (time.time(), row["id"]))

    def receive(self):
        self.ensure_group()
        reclaimed = self.client.xautoclaim(STREAM, GROUP, self.consumer, 90_000, count=1)[1]
        if reclaimed:
            return reclaimed[0]
        streams = self.client.xreadgroup(GROUP, self.consumer, {STREAM: ">"}, count=1)
        return streams[0][1][0] if streams else None

    def acknowledge(self, entry):
        self.client.xack(STREAM, GROUP, entry)

    def close(self):
        self.client.close()


def open_streams():
    url = os.getenv("TRINETRA_SOC_REDIS_URL")
    if not url:
        return None
    from redis import Redis

    return Streams(Redis.from_url(url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1))

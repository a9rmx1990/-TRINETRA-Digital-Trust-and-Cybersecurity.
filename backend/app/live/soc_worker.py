"""Consume committed SOC jobs independently of caller requests."""

import asyncio
import logging
import time

from starlette.concurrency import run_in_threadpool

from .soc_mcp import McpClient, McpSession
from .soc_stream import open_streams
from .soc_workflow import Workflow


log = logging.getLogger(__name__)


def apply_agent_action(db, pid, proposal_id, review=None):
    client = McpClient(McpSession(db, db.case(pid), "action", proposal_id, review=review))
    return client.read("apply_action", proposal_id=proposal_id)


async def run_investigation(db, pid, *, job=None):
    case = await run_in_threadpool(db.case, pid)
    if job and job["case_version"] != case["version"]:
        await run_in_threadpool(db.jobs.complete, job)
        return None
    assessment = await Workflow(db, case, job=job).run()
    if job:
        await run_in_threadpool(db.jobs.complete, job, assessment)
    else:
        await run_in_threadpool(db.save_triage, pid, assessment, case["version"])
    return assessment


async def consume(db, streams=None):
    await run_in_threadpool(db.monitor.tick, time.time())
    proposal = await run_in_threadpool(db.actions.queued)
    if proposal:
        await run_in_threadpool(apply_agent_action, db, proposal["case_id"], proposal["id"])
    message = None
    if streams:
        try:
            await run_in_threadpool(streams.publish, db, time.time())
            message = await run_in_threadpool(streams.receive)
        except Exception as error:
            log.warning("SOC stream unavailable (%s), reading durable outbox", type(error).__name__)
            streams.ready = False

    job = None
    if message:
        entry, envelope = message
        if envelope.get("schema_version") == "1":
            job_id = envelope.get("job_id")
            if job_id:
                job = await run_in_threadpool(db.jobs.claim, time.time(), job_id)
    if job is None:
        job = await run_in_threadpool(db.jobs.claim, time.time())
    if job:
        try:
            await run_investigation(db, job["case_id"], job=job)
        except Exception as error:
            await run_in_threadpool(db.jobs.fail, job, time.time(), type(error).__name__)
            raise
    if message:
        await run_in_threadpool(streams.acknowledge, message[0])
    return job is not None or proposal is not None


async def run(db):
    try:
        streams = open_streams()
    except ImportError:
        log.warning("Redis client is unavailable, reading durable outbox")
        streams = None
    try:
        while True:
            try:
                if not await consume(db, streams):
                    await asyncio.sleep(1)
            except Exception:
                log.exception("SOC job execution failed")
                await asyncio.sleep(1)
    finally:
        if streams:
            await run_in_threadpool(streams.close)


if __name__ == "__main__":
    from .ledger import open_ledger

    ledger = open_ledger()
    ledger.jobs.backfill()
    asyncio.run(run(ledger))

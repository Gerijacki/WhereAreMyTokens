"""`wamt agent`: tail local Claude Code transcripts and push them to a WhereAreMyTokens server.

Only slimmed, redacted records leave the machine (see parser.slim_record): no file contents,
no model output, no tool results - just usage, tool names/targets and prompt text.
Offsets are kept in a local state file so restarts resume where they stopped; the server
deduplicates, so re-sending after a failure is safe.

New records are written to a local spool before the offset moves, and each spool file is deleted once the server
has it. While the server is unreachable the backlog stays on disk, so it survives Claude Code deleting old
transcripts and the agent restarting.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from wamt.collector.parser import slim_record

log = logging.getLogger("wamt.agent")
MAX_RECORDS_PER_REQUEST = 2000
PROMPT_OMITTED = "[prompt omitted by agent]"


class Agent:
    def __init__(self, server: str, token: str, root: Path, state_file: Path, send_prompts: bool = True):
        self.url = server.rstrip("/") + "/api/ingest"
        self.token = token
        self.root = root
        self.state_file = state_file
        self.send_prompts = send_prompts
        self.spool = state_file.parent / "spool"
        self._seq = 0  # keeps spool names unique where the clock is coarse
        self.offsets: dict[str, int] = {}
        if state_file.exists():
            self.offsets = json.loads(state_file.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.offsets), encoding="utf-8")
        tmp.replace(self.state_file)

    def _post(self, files: list[dict]) -> None:
        req = urllib.request.Request(
            self.url, data=json.dumps({"files": files}).encode(), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()

    def _read_new(self, file: Path) -> tuple[list[dict], int]:
        key = str(file.relative_to(self.root)).replace("\\", "/")
        offset = self.offsets.get(key, 0)
        size = file.stat().st_size
        if size < offset:
            offset = 0  # file rewritten
        if size == offset:
            return [], offset
        with file.open("rb") as fh:
            fh.seek(offset)
            data = fh.read()
        end = data.rfind(b"\n")
        if end == -1:
            return [], offset
        records = []
        for raw in data[: end + 1].splitlines():
            try:
                rec = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            slim = slim_record(rec) if isinstance(rec, dict) else None
            if slim is None:
                continue
            if not self.send_prompts:
                for block in (slim.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "text" and not block["text"].startswith("<"):
                        block["text"] = PROMPT_OMITTED
            records.append(slim)
        return records, offset + end + 1

    def _enqueue(self, key: str, records: list[dict]) -> None:
        self.spool.mkdir(parents=True, exist_ok=True)
        for i in range(0, len(records), MAX_RECORDS_PER_REQUEST):
            self._seq += 1
            name = f"{time.time_ns():020d}-{self._seq:06d}"
            tmp = self.spool / f"{name}.tmp"
            tmp.write_text(json.dumps({"path": key, "records": records[i:i + MAX_RECORDS_PER_REQUEST]}),
                           encoding="utf-8")
            tmp.replace(self.spool / f"{name}.json")

    def pending(self) -> list[Path]:
        """Spool files not yet accepted by the server, oldest first."""
        return sorted(self.spool.glob("*.json")) if self.spool.is_dir() else []

    def _flush(self) -> int:
        sent = 0
        for item in self.pending():
            batch = json.loads(item.read_text(encoding="utf-8"))
            self._post([batch])
            item.unlink()
            sent += len(batch["records"])
        return sent

    def sync_once(self) -> int:
        """Queue everything new, even when offline, then send the queue. Returns the number of records sent."""
        for file in sorted(self.root.rglob("*.jsonl")):
            key = str(file.relative_to(self.root)).replace("\\", "/")
            records, new_offset = self._read_new(file)
            if records:
                self._enqueue(key, records)
            if new_offset != self.offsets.get(key, 0):
                self.offsets[key] = new_offset
                self._save()
        return self._flush()

    def run(self, interval: float = 10.0, once: bool = False) -> None:
        backoff = interval
        while True:
            try:
                n = self.sync_once()
                if n:
                    log.info("Sent %d records to %s", n, self.url)
                backoff = interval
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    raise SystemExit("Server rejected the device token (revoked or wrong). Create a new one with "
                                     "`wamt device add <name>` on the server.") from e
                log.warning("Server error %s; retrying in %.0fs", e.code, backoff)
                backoff = min(backoff * 2, 300)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                log.warning("Cannot reach server (%s); %d batches queued, retrying in %.0fs",
                            e, len(self.pending()), backoff)
                backoff = min(backoff * 2, 300)
            if once:
                return
            time.sleep(backoff)

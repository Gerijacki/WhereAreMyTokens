"""Remote ingestion: `wamt agent` pushes slimmed transcript records with a device token."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from wamt import devices
from wamt.collector.ingest import Batch, write_batch
from wamt.collector.parser import parse_record
from wamt.db import Device, get_db

router = APIRouter(prefix="/api")
DB = Annotated[Session, Depends(get_db)]
MAX_RECORDS = 5000


def require_device(db: DB, authorization: Annotated[str | None, Header()] = None) -> Device:
    device = devices.verify(db, devices.bearer(authorization))
    if device is None:
        raise HTTPException(401, "Invalid or revoked device token", headers={"WWW-Authenticate": "Bearer"})
    return device


class FileBatch(BaseModel):
    path: str = Field(description="Path relative to ~/.claude/projects, e.g. '<project-dir>/<session>.jsonl'")
    records: list[dict]


class IngestRequest(BaseModel):
    files: list[FileBatch]


@router.post("/ingest")
def ingest(body: IngestRequest, db: DB, device: Annotated[Device, Depends(require_device)]):
    total = sum(len(f.records) for f in body.files)
    if total > MAX_RECORDS:
        raise HTTPException(413, f"At most {MAX_RECORDS} records per request")
    accepted = 0
    for f in body.files:
        parts = f.path.replace("\\", "/").split("/")
        if len(parts) < 2 or ".." in parts:
            raise HTTPException(422, f"Invalid path: {f.path}")
        batch = Batch()
        for record in f.records:
            batch.add(parse_record(record))
            accepted += 1
        write_batch(db, batch, parts[0], device.name)
    device.last_seen_at = datetime.now(UTC)
    db.commit()
    return {"accepted": accepted, "device": device.name}

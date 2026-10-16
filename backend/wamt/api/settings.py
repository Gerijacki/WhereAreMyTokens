"""Settings endpoints: display preferences and the devices that push data with `wamt agent`."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from wamt import devices, preferences
from wamt.db import Device, get_db
from wamt.pricing import load_plans

router = APIRouter(prefix="/api")
DB = Annotated[Session, Depends(get_db)]


def _settings_out(db: Session) -> dict:
    return {
        **preferences.effective(db),
        "locked": sorted(preferences.locked()),
        "currencies": list(preferences.CURRENCIES),
        "plans": [{"id": p.id, "name": p.name, "prices": p.prices} for p in load_plans()],
    }


@router.get("/settings")
def get_settings_(db: DB):
    return _settings_out(db)


@router.patch("/settings")
def update_settings(changes: dict, db: DB):
    try:
        preferences.update(db, changes)
    except preferences.LockedError as e:
        raise HTTPException(409, str(e)) from e
    except preferences.PreferenceError as e:
        raise HTTPException(422, str(e)) from e
    return _settings_out(db)


# --------------------------------------------------------------------------- devices

def _device_out(d: Device) -> dict:
    return {"name": d.name, "created_at": d.created_at, "last_seen_at": d.last_seen_at, "revoked": d.revoked}


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=128, pattern=r"^[\w.-]+$")


@router.get("/devices")
def list_devices(db: DB):
    return [_device_out(d) for d in db.scalars(select(Device).order_by(Device.name))]


@router.post("/devices", status_code=201)
def add_device(body: DeviceIn, db: DB):
    """Create a device. Its token is in this response only: just its hash is stored."""
    try:
        token = devices.create(db, body.name)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    device = db.scalar(select(Device).where(Device.name == body.name))
    return {**_device_out(device), "token": token}


@router.delete("/devices/{name}")
def revoke_device(name: str, db: DB):
    if not devices.revoke(db, name):
        raise HTTPException(404, "Device not found")
    return {"name": name, "revoked": True}

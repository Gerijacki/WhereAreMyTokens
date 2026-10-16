"""Plan value and budget endpoints."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from wamt.analytics.spend import PERIODS, all_budgets, budget_status, plan_value
from wamt.db import Budget, Project, get_db

router = APIRouter(prefix="/api")
DB = Annotated[Session, Depends(get_db)]


@router.get("/plan")
def plan(db: DB, months: int = Query(6, ge=1, le=24)):
    """API-equivalent cost per month and over the last 30 days, compared with each subscription plan."""
    return plan_value(db, months)


class BudgetIn(BaseModel):
    period: str = Field(pattern="^(day|week|month)$")
    limit_usd: float = Field(gt=0, le=1_000_000)
    project_id: int | None = None


@router.get("/budgets")
def budgets(db: DB):
    return {"periods": list(PERIODS), "items": all_budgets(db)}


@router.post("/budgets", status_code=201)
def create_budget(body: BudgetIn, db: DB):
    if body.project_id is not None and db.get(Project, body.project_id) is None:
        raise HTTPException(422, "Unknown project")
    b = Budget(period=body.period, limit_usd=body.limit_usd, project_id=body.project_id,
               created_at=datetime.now(UTC))
    db.add(b)
    db.commit()
    return budget_status(db, b)


@router.delete("/budgets/{budget_id}")
def delete_budget(budget_id: int, db: DB):
    b = db.get(Budget, budget_id)
    if b is None:
        raise HTTPException(404, "Budget not found")
    db.delete(b)
    db.commit()
    return {"id": budget_id, "deleted": True}

"""Run enqueue and status endpoints for batch processing (Spec 0008 §4.3).

POST /runs  → enqueue a batch job, store status marker on EFS, send SQS message.
GET  /runs/{run_id}  → retrieve status from EFS marker.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["runs"])

# SQS client (inject via dependency if needed; env var used here for simplicity)
_sqs_client = None


def get_sqs_client():
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = boto3.client("sqs")
    return _sqs_client


class RunRequest(BaseModel):
    handle: str = Field(..., description="Instagram handle to process.")
    stages: str = Field(default="all", description="Comma-separated stage numbers (1-8) or 'all'.")


class RunResponse(BaseModel):
    run_id: str
    status: str
    url: str


class RunStatus(BaseModel):
    run_id: str
    status: str
    created_at: str
    updated_at: str | None = None


def _validate_handle(handle: str) -> None:
    """Ensure handle is alphanumeric + underscores."""
    if not handle or not all(c.isalnum() or c == "_" for c in handle):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid handle '{handle}': must be alphanumeric or underscore.",
        )


def _validate_stages(stages: str) -> list[int]:
    """Parse and validate stage numbers."""
    if stages.lower() == "all":
        return [1, 2, 3, 6, 7, 8, 9]

    try:
        stage_list = [int(s.strip()) for s in stages.split(",")]
        for s in stage_list:
            if not 1 <= s <= 8:
                raise ValueError
        return stage_list
    except (ValueError, AttributeError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stages '{stages}': comma-separated integers 1–8 or 'all'. {e}",
        ) from e


def _status_marker_path(handle: str, run_id: str) -> Path:
    """Path to the run status marker on EFS."""
    projects_dir = os.getenv("PROJECTS_DIR", "/app/projects")
    marker_path = Path(projects_dir) / handle / "runs" / f"{run_id}.json"
    return marker_path


def _write_status_marker(handle: str, run_id: str, status: str, metadata: dict | None = None) -> None:
    """Write status marker to EFS."""
    marker_path = _status_marker_path(handle, run_id)
    marker_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()
    marker = {
        "run_id": run_id,
        "handle": handle,
        "status": status,
        "created_at": now,
        "updated_at": now,
        **(metadata or {}),
    }

    with open(marker_path, "w") as f:
        json.dump(marker, f, indent=2)
    logger.info("Wrote status marker: %s → %s", run_id, status)


def _read_status_marker(handle: str, run_id: str) -> dict:
    """Read status marker from EFS."""
    marker_path = _status_marker_path(handle, run_id)
    if not marker_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Run {run_id} not found for handle {handle}.",
        )

    with open(marker_path) as f:
        return json.load(f)


@router.post("/runs", response_model=RunResponse)
async def enqueue_run(req: RunRequest) -> RunResponse:
    """Enqueue a new batch run.

    - Validate handle (alphanumeric + underscore).
    - Validate stages (comma-separated ints 1–8 or 'all').
    - Generate run_id = uuid4 hex (first 12 chars).
    - Write status marker to EFS.
    - Send SQS message.
    - Return {run_id, status: "queued", url: "/runs/{run_id}"}.
    """
    _validate_handle(req.handle)
    stages = _validate_stages(req.stages)

    run_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()

    # Write status marker to EFS
    try:
        _write_status_marker(
            req.handle,
            run_id,
            "queued",
            {"stages": stages, "enqueued_at": now},
        )
    except Exception as e:
        logger.exception("Failed to write status marker for run %s", run_id)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to write status marker: {e}",
        ) from e

    # Send SQS message
    queue_url = os.getenv("RUNS_QUEUE_URL")
    if not queue_url:
        raise HTTPException(
            status_code=500,
            detail="RUNS_QUEUE_URL not configured.",
        )

    try:
        sqs = get_sqs_client()
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(
                {
                    "run_id": run_id,
                    "handle": req.handle,
                    "stages": stages,
                    "enqueued_at": now,
                }
            ),
        )
        logger.info("Enqueued run %s for handle %s", run_id, req.handle)
    except Exception as e:
        logger.exception("Failed to send SQS message for run %s", run_id)
        raise HTTPException(
            status_code=503,
            detail=f"SQS unreachable: {e}",
        ) from e

    return RunResponse(
        run_id=run_id,
        status="queued",
        url=f"/runs/{run_id}",
    )


@router.get("/runs/{run_id}", response_model=RunStatus)
async def get_run_status(run_id: str, handle: str | None = None) -> RunStatus:
    """Retrieve status of a queued or completed run.

    If handle is not provided, tries to infer it from the run marker (if unique).
    Returns {run_id, status, created_at, updated_at}.
    """
    # If handle not provided, try to find it
    if not handle:
        projects_dir = os.getenv("PROJECTS_DIR", "/app/projects")
        projects_path = Path(projects_dir)

        # Search for the run_id across all handles (this is a fallback)
        found_handles = []
        if projects_path.exists():
            for handle_dir in projects_path.iterdir():
                if handle_dir.is_dir():
                    marker = handle_dir / "runs" / f"{run_id}.json"
                    if marker.exists():
                        found_handles.append(handle_dir.name)

        if len(found_handles) == 1:
            handle = found_handles[0]
        elif len(found_handles) > 1:
            raise HTTPException(
                status_code=400,
                detail=f"Ambiguous run_id {run_id}; provide ?handle=<handle>",
            )
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Run {run_id} not found. Provide ?handle=<handle> if needed.",
            )

    try:
        marker = _read_status_marker(handle, run_id)
    except HTTPException:
        raise

    return RunStatus(
        run_id=marker["run_id"],
        status=marker["status"],
        created_at=marker["created_at"],
        updated_at=marker.get("updated_at"),
    )

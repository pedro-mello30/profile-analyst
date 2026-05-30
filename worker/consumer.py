"""SQS consumer worker for async batch processing (Spec 0008 §4.4).

Long-polls the RUNS_QUEUE_URL for messages containing {run_id, handle, stages}.
Executes the profile_analyst pipeline (Stages 1-8) and updates status markers on EFS.
Handles poison messages by abandoning them to DLQ after N retries.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class SQSWorker:
    """Poll SQS, execute pipeline, update EFS status markers."""

    def __init__(self):
        """Initialize SQS client and configuration from environment."""
        self.queue_url = os.getenv("RUNS_QUEUE_URL")
        if not self.queue_url:
            raise ValueError("RUNS_QUEUE_URL environment variable not set")

        self.projects_dir = os.getenv("PROJECTS_DIR", "/app/projects")
        self.max_receive_count = 3  # Matches SQS redrive policy from Terraform

        self.sqs = boto3.client("sqs")
        logger.info("SQS Worker initialized. Queue: %s", self.queue_url)

    def _status_marker_path(self, handle: str, run_id: str) -> Path:
        """Path to run status marker on EFS."""
        marker_path = Path(self.projects_dir) / handle / "runs" / f"{run_id}.json"
        return marker_path

    def _read_marker(self, handle: str, run_id: str) -> dict:
        """Read current status marker."""
        marker_path = self._status_marker_path(handle, run_id)
        if marker_path.exists():
            with open(marker_path) as f:
                return json.load(f)
        return {}

    def _update_marker(self, handle: str, run_id: str, status: str, metadata: dict | None = None) -> None:
        """Update status marker on EFS."""
        marker_path = self._status_marker_path(handle, run_id)
        marker_path.parent.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc).isoformat()
        marker = self._read_marker(handle, run_id)
        marker.update(
            {
                "run_id": run_id,
                "handle": handle,
                "status": status,
                "updated_at": now,
                **(metadata or {}),
            }
        )

        with open(marker_path, "w") as f:
            json.dump(marker, f, indent=2)
        logger.info("Updated status marker %s → %s", run_id, status)

    def _execute_pipeline(self, handle: str, stages: list[int]) -> int:
        """Execute profile_analyst pipeline for the given handle and stages.

        Returns exit code (0 = success).
        """
        # Import here to avoid circular dependency
        from profile_analyst import main as pipeline_main

        # Build args: handle, --stage list
        stages_str = ",".join(str(s) for s in stages)
        args = ["--handle", handle, "--stage", stages_str]

        logger.info("Executing pipeline for handle=%s, stages=%s", handle, stages_str)
        try:
            # Call the CLI main function with argv-like args
            exit_code = pipeline_main(args)
            return exit_code
        except SystemExit as e:
            return e.code or 0
        except Exception as e:
            logger.exception("Pipeline execution failed: %s", e)
            return 1

    def _receive_messages(self) -> list[dict]:
        """Receive one message from SQS (long-poll, 20s)."""
        try:
            response = self.sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                MessageAttributeNames=["All"],
            )
            return response.get("Messages", [])
        except Exception as e:
            logger.exception("Failed to receive message from SQS: %s", e)
            return []

    def _delete_message(self, message: dict) -> None:
        """Delete message from queue (after successful processing)."""
        try:
            self.sqs.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=message["ReceiptHandle"],
            )
            logger.info("Deleted message %s from queue", message.get("MessageId"))
        except Exception as e:
            logger.exception("Failed to delete message: %s", e)

    def _get_receive_count(self, message: dict) -> int:
        """Extract ApproximateReceiveCount from message attributes."""
        attrs = message.get("Attributes", {})
        try:
            return int(attrs.get("ApproximateReceiveCount", 0))
        except (ValueError, TypeError):
            return 0

    def _should_abandon_to_dlq(self, receive_count: int) -> bool:
        """Check if message should be abandoned (exceeded retry limit)."""
        # SQS redrive policy (from Terraform: maxReceiveCount = 3) will move it to DLQ
        # when visibility timeout expires without deletion. We abandon after max_receive_count.
        return receive_count >= self.max_receive_count

    def process_message(self, message: dict) -> None:
        """Process a single SQS message: execute pipeline, update status, delete message.

        If processing fails and receive_count >= max, abandon message (let it go to DLQ).
        """
        msg_id = message.get("MessageId")
        receipt_handle = message.get("ReceiptHandle")
        body = json.loads(message.get("Body", "{}"))

        run_id = body.get("run_id")
        handle = body.get("handle")
        stages = body.get("stages", list(range(1, 9)))
        receive_count = self._get_receive_count(message)

        logger.info("Processing message %s: run_id=%s, handle=%s, stages=%s, receive_count=%d",
                    msg_id, run_id, handle, stages, receive_count)

        if not run_id or not handle:
            logger.error("Invalid message: missing run_id or handle. Deleting to avoid infinite loop.")
            self._delete_message(message)
            return

        # Update marker: running
        self._update_marker(handle, run_id, "running", {"started_at": datetime.now(timezone.utc).isoformat()})

        # Execute pipeline
        exit_code = self._execute_pipeline(handle, stages)

        if exit_code == 0:
            # Success
            self._update_marker(
                handle,
                run_id,
                "succeeded",
                {"completed_at": datetime.now(timezone.utc).isoformat()},
            )
            self._delete_message(message)
            logger.info("Pipeline completed successfully for run_id=%s", run_id)
        else:
            # Failure
            error_msg = f"Pipeline exited with code {exit_code}"
            self._update_marker(
                handle,
                run_id,
                "failed",
                {
                    "error": error_msg,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "receive_count": receive_count,
                },
            )

            if self._should_abandon_to_dlq(receive_count):
                # Abandon to DLQ by not deleting (visibility timeout will expire → DLQ)
                logger.warning(
                    "Message %s abandoned to DLQ: exceeded max retries (%d). "
                    "Run %s for handle %s marked as failed.",
                    msg_id,
                    self.max_receive_count,
                    run_id,
                    handle,
                )
            else:
                # Will be retried by SQS (visibility timeout expires, message reappears)
                logger.warning(
                    "Pipeline failed for run_id=%s (receive_count=%d, max=%d). Will retry.",
                    run_id,
                    receive_count,
                    self.max_receive_count,
                )

    def run(self) -> None:
        """Main worker loop: long-poll SQS, process messages indefinitely."""
        logger.info("Starting SQS worker loop...")
        while True:
            try:
                messages = self._receive_messages()
                if not messages:
                    # Long-poll timeout (20s) — no messages, loop again
                    continue

                for message in messages:
                    try:
                        self.process_message(message)
                    except Exception as e:
                        logger.exception("Unexpected error processing message: %s", e)
                        # Continue to next message rather than crashing worker

            except KeyboardInterrupt:
                logger.info("Worker interrupted. Exiting.")
                sys.exit(0)
            except Exception as e:
                logger.exception("Unexpected error in worker loop: %s", e)
                # Wait before retrying to avoid rapid failure loops
                time.sleep(5)


def main():
    """Entry point for worker process."""
    try:
        worker = SQSWorker()
        worker.run()
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)
    except Exception as e:
        logger.exception("Fatal error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()

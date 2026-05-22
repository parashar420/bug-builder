from __future__ import annotations

from typing import Any

from bug_builder.squash_client import SquashClient


class SquashExtractor:
    def __init__(self, client: SquashClient):
        self.client = client

    @staticmethod
    def _latest_execution_id(test_plan_item) -> int | None:
        executions = list(test_plan_item.executions or [])
        if not executions:
            return None

        executions.sort(key=lambda e: e.last_executed_on or "")
        latest = executions[-1]
        return latest.id if latest else None

    def extract(self, iteration_id: int) -> list[dict[str, Any]]:
        iteration = self.client.get_iteration(iteration_id)
        fallback_comment = iteration.description or ""

        failed_payloads: list[dict[str, Any]] = []
        test_plan_items = self.client.list_test_plan(iteration_id)

        for item in test_plan_items:
            if str(item.execution_status or "").upper() != "FAILURE":
                continue

            latest_execution_id = self._latest_execution_id(item)
            if latest_execution_id is None:
                continue

            execution = self.client.get_execution(latest_execution_id)
            steps = self.client.list_execution_steps(latest_execution_id)
            steps = sorted(steps, key=lambda s: s.execution_step_order if s.execution_step_order is not None else 10**9)

            normalized_steps = []
            for step in steps:
                normalized_steps.append(
                    {
                        "id": step.id,
                        "order": step.execution_step_order,
                        "executionStatus": step.execution_status,
                        "action": step.action or "",
                        "expectedResult": step.expected_result or "",
                        "comment": step.comment,
                        "lastExecutedOn": step.last_executed_on,
                        "lastExecutedBy": step.last_executed_by,
                    }
                )

            normalized_payload = {
                "id": execution.id,
                "name": execution.name,
                "executionStatus": item.execution_status or execution.execution_status,
                "lastExecutedOn": execution.last_executed_on,
                "lastExecutedBy": execution.last_executed_by,
                "comment": execution.comment if execution.comment is not None else fallback_comment,
                "prerequisite": execution.prerequisite,
                "executionStepViews": normalized_steps,
                "_meta": {
                    "iterationId": iteration.id,
                    "iterationName": iteration.name,
                    "source": "squash_api",
                },
            }
            failed_payloads.append(normalized_payload)

        return failed_payloads

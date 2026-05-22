from __future__ import annotations

from typing import Any

import httpx

from bug_builder.squash_models import ExecutionModel, ExecutionStepModel, IterationModel, TestPlanItemModel


class SquashClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        if not token:
            raise ValueError("Squash token is required")
        self.base_url = (base_url or "").rstrip("/")
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=timeout,
            verify=False,
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "SquashClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def _paginate(self, path: str, embedded_key: str, page_size: int = 200) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        data = self._get(path, params={"size": page_size})

        while True:
            embedded = data.get("_embedded", {})
            batch = embedded.get(embedded_key, [])
            if isinstance(batch, list):
                items.extend(batch)

            next_href = data.get("_links", {}).get("next", {}).get("href")
            if not next_href:
                break
            data = self._get(next_href)

        return items

    def get_iteration(self, iteration_id: int) -> IterationModel:
        payload = self._get(f"/iterations/{iteration_id}")
        return IterationModel.model_validate(payload)

    def list_test_plan(self, iteration_id: int, page_size: int = 200) -> list[TestPlanItemModel]:
        items = self._paginate(
            f"/iterations/{iteration_id}/test-plan",
            embedded_key="test-plan",
            page_size=page_size,
        )
        return [TestPlanItemModel.model_validate(item) for item in items]

    def get_execution(self, execution_id: int) -> ExecutionModel:
        payload = self._get(f"/executions/{execution_id}")
        return ExecutionModel.model_validate(payload)

    def list_execution_steps(self, execution_id: int, page_size: int = 200) -> list[ExecutionStepModel]:
        items = self._paginate(
            f"/executions/{execution_id}/execution-steps",
            embedded_key="execution-steps",
            page_size=page_size,
        )
        return [ExecutionStepModel.model_validate(item) for item in items]

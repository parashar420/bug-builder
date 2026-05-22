from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IterationModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str | None = None
    description: str | None = None


class EmbeddedExecutionModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    last_executed_on: str | None = None


class TestPlanItemModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    execution_status: str | None = None
    executions: list[EmbeddedExecutionModel] = Field(default_factory=list)


class ExecutionStepModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    execution_status: str | None = None
    action: str | None = None
    expected_result: str | None = None
    comment: str | None = None
    last_executed_by: str | None = None
    last_executed_on: str | None = None
    execution_step_order: int | None = None


class ExecutionModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str | None = None
    execution_status: str | None = None
    last_executed_by: str | None = None
    last_executed_on: str | None = None
    comment: str | None = None
    prerequisite: str | None = None
    custom_fields: list[dict[str, Any]] = Field(default_factory=list)

# Bug Builder

## Project Overview

Bug Builder is a QA productivity tool that helps teams convert failed test runs into clear, actionable bug tickets in minutes instead of hours. Today, QA engineers often lose time jumping between test tools, copying step details manually, rewriting failure notes into a ticket format, and making sure the report includes enough context for developers to reproduce the issue. This project removes that repetitive work. It gathers failure details, organizes them into a readable bug narrative, and prepares a ready-to-use YouTrack ticket link so teams can file faster with better quality. It is designed to reduce common pain points: inconsistent bug report quality across testers, missing repro context, duplicated manual effort. Bug Builder also helps standardize communication between QA and engineering by producing a predictable structure for every report, which makes debugging and prioritization easier. In practical terms, the project gives teams a faster path from “test failed” to “ticket ready,” improves confidence that important details were not missed, and lowers onboarding friction for new QA members who need a guided, repeatable bug-reporting workflow.

## What This Project Does

- Pulls failed test executions directly from Squash TM REST API.
- Converts Squash execution payloads into the internal format already used by current bug-generation logic.
- Uses CrewAI agents to create:
  - A structured markdown bug report.
  - A prefilled YouTrack issue creation URL.
- Supports two workflows:
  - Gherkin: one output per failed step.
  - Testcases: one consolidated output per failed execution.

## Current Architecture

- UI: streamlit_app.py
- API client: src/bug_builder/squash_client.py
- API extraction and normalization: src/bug_builder/squash_extractor.py
- API models: src/bug_builder/squash_models.py
- Crew and prompts:
  - src/bug_builder/crew.py
  - src/bug_builder/config/agents.yaml
  - src/bug_builder/config/tasks.yaml

Notes:
- Legacy MITM capture code remains in the repo (squash_capture.py) but is hidden from the UI.
- YouTrack integration is URL-based (no YouTrack REST API calls).

## Prerequisites

- Python >=3.10,<3.14
- Install dependencies from pyproject.toml
- Valid Athena key for CrewAI LLM calls
- Valid Squash API token (Bearer)

## Setup

1. Create or activate your virtual environment.
2. Install dependencies:

```bash
pip install -e .
```

3. Add required tokens:

- athena_token.txt (already supported)
- squash_token.txt (new, ignored by git)

You can start from examples:

- athena_token.txt.example
- squash_token.txt.example

4. Ensure config.yaml contains:

- squash.base_url (default: https://squash.internetbrands.com/api/rest/latest)
- Existing youtrack and llm blocks

## Running the App

```bash
streamlit run streamlit_app.py
```

In the UI:

1. Choose mode: Gherkin or Testcases.
2. Enter Squash iteration ID.
3. Click Extract from Squash API.
4. Review analysis results.
5. Click Create YouTrack Links to generate output URLs.

## How Mode Toggle Works

- Gherkin:
  - Processes failures at failed-step granularity.
  - Can generate multiple tickets from a single execution.
- Testcases:
  - Processes failures at execution/testcase granularity.
  - Generates one consolidated ticket per failed execution.

## Output Files

During processing, Crew tasks may create temporary files in project root:

- bug_report.md
- youtrack_url.txt

The app reads them and then manages output display in Streamlit.

## Security and Secrets

Never commit real secrets. This repository ignores:

- athena_token.txt
- squash_token.txt
- .env

Use the corresponding example files for onboarding.

## Verification Checklist

For a known iteration (example: 17706), verify:

- Failed executions are detected.
- Execution steps are loaded from /executions/{id}/execution-steps?size=200.
- Generated bug descriptions include expected failure context.
- YouTrack links open with populated title and description.

## Troubleshooting

- 401 from Squash API:
  - Confirm Authorization: Bearer <token> behavior and token validity.
- No failures found:
  - Confirm iteration ID and that failed test-plan items exist.
- Missing build/device info:
  - App falls back from execution comment to iteration description when available.

## Maintenance Notes

- API-first flow is active.
- Legacy MITM code is retained for fallback but hidden from UI.
- Keep prompt and agent quality in agents.yaml and tasks.yaml aligned with QA reporting standards.

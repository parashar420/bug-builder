# Bug Builder — Direct Squash API Integration Plan

## 1. Context and Goal

Bug Builder is an existing Streamlit + CrewAI application that currently:
- Captures Squash TM execution data via **MITM proxy** (`squash_capture.py` / mitmproxy intercepts browser traffic)
- Reads captured JSON files from `captured_squash_data/` and `captured_testcase_data/`
- Uses CrewAI agents (backed by Athena/GPT-4.1) to generate structured bug reports (Markdown)
- Generates **pre-filled YouTrack issue creation URLs** that the tester opens in their browser

**Goal of this implementation:** Replace the MITM proxy capture step with direct Squash REST API calls, making data extraction self-contained and removing the dependency on mitmproxy being active in the browser.

The MITM proxy path (`squash_capture.py`) is NOT deleted — it is kept as a legacy fallback and deprecated gradually after the API path is validated.

---

## 2. What Changes and What Stays the Same

### Unchanged — do not modify
- All CrewAI agents and their configs (`agents.yaml`, `tasks.yaml`, `crew.py`)
- `format_bug_description()` and `format_testcase_bug_description()` in `streamlit_app.py`
- `analyze_json_data()` and `analyze_testcase_files()` in `streamlit_app.py`
- `build_inputs()`, `extract_execution_comment()`, `extract_parent_ticket()` in `utils.py`
- Gherkin / Testcases mode distinction and the mode toggle in the UI
- `config.yaml` project/board/sprint structure and YouTrack URL templates
- Streamlit main layout, session state management (`session_service.py`), and header

### New files to add
| File | Purpose |
| --- | --- |
| `src/bug_builder/squash_client.py` | `httpx` sync client — Basic auth, typed GET methods, HAL pagination |
| `src/bug_builder/squash_models.py` | Pydantic v2 models for REST API response payloads |
| `src/bug_builder/squash_extractor.py` | Iteration ID → list of normalized execution dicts (same shape as MITM payloads) |
| `src/bug_builder/ui/modes/squash_api_panel.py` | Streamlit panel: iteration ID input → API extraction → feed existing analysis pipeline |
| `squash_token.txt` | Gitignored — raw Squash PAT (mirrors `athena_token.txt` pattern) |
| `squash_token.txt.example` | Committed — placeholder instructions for new developers |

### Configuration additions to `config.yaml`
Add a new top-level `squash:` key:
```yaml
squash:
  base_url: "https://squash.internetbrands.com/api/rest/latest"
  # token loaded from squash_token.txt — no username needed, Bearer auth
```

Extend `src/bug_builder/__init__.py` with a `load_squash_token()` function mirroring the existing `load_athena_token()`. No `.env` / `pydantic-settings` required.

### Deprecated (kept, not deleted)
- `squash_capture.py` — kept but labelled legacy
- MITM panel UI components in `gherkin_page.py` and `testcases_page.py` — remain accessible as fallback

---

## 3. Squash TM REST API

- **Base URL:** `https://squash.internetbrands.com/api/rest/latest`
- **Auth:** Bearer token — `Authorization: Bearer <token>` (**confirmed from live API test; Basic and bare token both return 401**)

| Purpose | Method | Path |
| --- | --- | --- |
| Verify iteration exists | GET | `/iterations/{iterationId}` |
| List test plan items (incl. embedded executions) | GET | `/iterations/{iterationId}/test-plan?size=200` |
| Execution detail (incl. `comment`, `prerequisite`) | GET | `/executions/{executionId}` |
| Steps of an execution — **always required for full step data** | GET | `/executions/{executionId}/execution-steps?size=200` |
| Issues linked to an execution | GET | `/executions/{executionId}/issues` |

> **Endpoints NOT needed:** `/iteration-test-plan-items/{itpiId}/executions` is redundant — each test plan item in the `test-plan` response already embeds an `executions[]` array with `id` and `last_executed_on`. Use that to find the latest execution ID directly.

**Pagination:** HAL `_embedded` + `page` structure. Always pass `size=200` and follow `_links.next` until exhausted. Confirmed: the `execution-steps` response uses `_embedded["execution-steps"]`.

**Failure filter:** A test plan item is failed when `execution_status == "FAILURE"`. Other statuses: SUCCESS, BLOCKED, UNTESTABLE, READY, RUNNING, SETTLED.

**Latest execution rule:** Each test plan item embeds `executions[]`. Sort by `last_executed_on` descending, pick index 0 → that is the execution ID to fetch.

---

## 4. REST API vs. MITM Payload — Field Mapping

The MITM proxy captured a **frontend view endpoint** that bundles execution detail + all steps into one response object (using camelCase). The REST API returns them via separate endpoints (using snake_case). `squash_extractor.py` must assemble REST responses into the same internal dict shape so the existing formatters in `streamlit_app.py` work unchanged.

| Internal key (used by existing formatters) | MITM camelCase field | REST API source |
| --- | --- | --- |
| `id` | `id` | `/executions/{id}` → `id` |
| `name` | `name` | `/executions/{id}` → `name` |
| `executionStatus` | `executionStatus` | test plan item → `execution_status` |
| `lastExecutedOn` | `lastExecutedOn` | execution → `last_executed_on` |
| `lastExecutedBy` | `lastExecutedBy` | execution → `last_executed_by` |
| `comment` | `comment` (raw HTML, **can be `null`**) | execution → `comment`; if null fall back to iteration → `description` |
| `executionStepViews` | `executionStepViews[]` | assembled from `/executions/{id}/execution-steps?size=200` — **never use inline `execution_steps` from the execution detail; that array omits `comment`, `last_executed_by`, `last_executed_on`, and `execution_step_order`** |
| `executionStepViews[].id` | step `id` | step `id` |
| `executionStepViews[].order` | step `order` | step `execution_step_order` (**confirmed field name**) |
| `executionStepViews[].executionStatus` | step `executionStatus` | step `execution_status` |
| `executionStepViews[].action` | step `action` (raw HTML) | step `action` |
| `executionStepViews[].expectedResult` | step `expectedResult` | step `expected_result` |
| `executionStepViews[].comment` | step `comment` (raw HTML or null) | step `comment` |
| `executionStepViews[].lastExecutedOn` | step `lastExecutedOn` | step `last_executed_on` |
| `executionStepViews[].lastExecutedBy` | step `lastExecutedBy` | step `last_executed_by` |

Additional REST API fields available but not currently consumed by formatters (carry through in dict for future use):
- `execution.prerequisite` — HTML string, the test precondition (e.g. `"<p>User has an active chat conversation..."`) — useful context for bug reports
- `execution.custom_fields[]` — includes `YouTrack_Ticket` (value if a ticket is already filed) and `Test_Device`, `Test_Environment`, `Browser`
- `iteration.description` — HTML string, often contains build/device info when `execution.comment` is null

`squash_extractor.py` outputs a list of dicts with exactly the internal keys above so `analyze_json_data()`, `format_bug_description()`, and `format_testcase_bug_description()` require zero modification.

---

## 5. YouTrack Integration — URL Generation (NOT REST API)

Bug Builder does NOT call the YouTrack REST API. It generates a **pre-filled issue creation URL** that the tester opens in their browser to review and submit.

**How it works:**
1. `config.yaml` defines per-project URL templates with encoded placeholders (`[ENCODED_TITLE]`, `[ENCODED_DESCRIPTION]`, `{parent_ticket}`, `{board_encoded}`, `{board_sprint_encoded}`)
2. The `youtrack_url_generator` CrewAI agent receives the bug report markdown and the URL template via `{url_template}`
3. The agent URL-encodes title and description (spaces → `+`, newlines → `%0A`, `|` → `%7C`, `:` → `%3A`) and substitutes them into the template
4. The resulting URL pre-populates YouTrack's new issue form; the tester clicks it to create the ticket

**Supported projects (from existing `config.yaml`):**
- `WBMDMOB` (Medscape Professional) — `year.week` sprint format
- `MEDAIS` (MedAIS) — sequential sprint format

**Parent ticket extraction:** The execution-level `comment` field (raw HTML) can contain `"Subtask of: TICKET-123"` or `"Story: TICKET-123"`. The existing `extract_parent_ticket()` in `utils.py` parses this. However, `execution.comment` **can be null** for manually executed tests where the tester did not fill in a comment. In that case `extract_parent_ticket()` returns `None` gracefully — the YouTrack URL is generated without a parent ticket, and the tester adds it manually. The `iteration.description` field is also passed through the normalized dict as a fallback source of build/device info when `execution.comment` is null.

No YouTrack credentials are needed. No REST API calls to YouTrack are planned.

---

## 6. Existing CrewAI Agents (unchanged)

| Agent | Role |
| --- | --- |
| `bug_report_specialist` | Gherkin mode — parses a single failed Gherkin scenario and produces a structured bug report |
| `testcase_bug_report_specialist` | Testcases mode — synthesizes all steps of a failed test case execution into one unified bug report |
| `youtrack_url_generator` | Both modes — encodes bug report into a pre-filled YouTrack issue creation URL using the project's `url_template` |

The agents are orchestrated sequentially in `crew.py`. Mode selection (`gherkin` vs `testcases`) determines which task runs first. The API integration feeds data into the same `build_inputs()` call that MITM currently uses — the crew is unaware of where the data came from.

---

## 7. Data Flow — New API Path

```
User enters iteration ID in squash_api_panel.py
        ↓
SquashExtractor.extract(iteration_id)
  → SquashClient.get_iteration(id)         # verify; store iteration.description as build/device fallback
  → SquashClient.list_test_plan(id)        # paginated; each item embeds executions[]
  → filter: item.execution_status == "FAILURE"
  → for each failed item:
      → pick latest execution from item.executions[] sorted by last_executed_on desc
      → SquashClient.get_execution(execId)          # full detail incl. comment, prerequisite
      → SquashClient.list_execution_steps(execId)   # REQUIRED — inline steps are abbreviated
      → assemble normalized execution dict
          comment = execution.comment ?? iteration.description  # null-coalesce
        ↓
List of normalized execution dicts
        ↓
[Gherkin mode]  analyze_json_data(dict)          → per failed executionStepView
[Testcases mode] analyze_testcase_files(bundle)  → per execution (all steps)
        ↓
format_bug_description() / format_testcase_bug_description()
        ↓
build_inputs(bug_description, project, board, sprint, parent_ticket)
        ↓
BugBuilder().crew(mode).kickoff(inputs=inputs)
  → generate_bug_report / generate_testcase_bug_report
  → generate_youtrack_url
        ↓
UI displays bug_report.md + youtrack_url.txt
```

---

## 8. Mode Behavior — API Path vs. MITM Path

| Mode | MITM (current) | API (new) |
| --- | --- | --- |
| **Gherkin** | Single latest JSON from `captured_squash_data/`; one crew run per failed `executionStepView` | All failed executions from iteration; one crew run per failed `executionStepView` across all executions |
| **Testcases** | All JSON files from both capture dirs; one crew run per execution (all steps consolidated) | All failed executions from iteration; one crew run per execution (all steps consolidated) |

---

## 9. New Source File Responsibilities

### `squash_client.py`
- Holds an `httpx.Client` with `Authorization: Bearer <token>` header set at init
- Exposes typed methods: `get_iteration()`, `list_test_plan()`, `get_execution()`, `list_execution_steps()`
- No `list_executions()` — execution IDs are read from the embedded `executions[]` in test plan items
- One internal `_paginate()` helper that follows HAL `_links.next` until exhausted; keys into `_embedded[resource_key]`

### `squash_models.py`
- Pydantic v2 `BaseModel` classes for: `Iteration`, `TestPlanItem`, `Execution`, `ExecutionStep`
- Use `model_config = ConfigDict(populate_by_name=True)` to accept REST API snake_case fields
- Field aliases map snake_case REST fields to the camelCase internal keys where needed

### `squash_extractor.py`
- Accepts iteration ID, returns `list[dict]` of normalized execution payloads
- Applies failure filter and latest-execution selection
- Calls only `SquashClient` methods — no inline HTTP calls
- Single public method: `SquashExtractor(client).extract(iteration_id) -> list[dict]`

### `squash_api_panel.py`
- Renders a text input for iteration ID and an "Extract from Squash API" button
- On click: calls `SquashExtractor`, stores result in `st.session_state`
- Calls the same `analyze_json_data()` / `analyze_testcase_files()` from `streamlit_app.py` — does NOT duplicate logic
- Handles and surfaces API errors (auth failure, iteration not found, no failures) with `st.error()`

---

## 10. Repository Layout — Additions Only

```
bug_builder/                         # existing project root
├── squash_token.txt                 # NEW — gitignored, raw PAT
├── squash_token.txt.example         # NEW — committed, placeholder
├── config.yaml                      # MODIFIED — add squash: section
└── src/bug_builder/
    ├── __init__.py                  # MODIFIED — add load_squash_token()
    ├── squash_client.py             # NEW
    ├── squash_models.py             # NEW
    ├── squash_extractor.py          # NEW
    └── ui/
        └── modes/
            ├── gherkin_page.py      # MODIFIED — add squash_api_panel alongside MITM panel
            ├── testcases_page.py    # MODIFIED — add squash_api_panel alongside MITM panel
            └── squash_api_panel.py  # NEW
```

All other files remain untouched.

---

## 11. MITM Deprecation Strategy

| Phase | Action |
| --- | --- |
| Phase 1 (this session) | API client + extractor + new UI panel added. Both MITM and API paths work in parallel. |
| Phase 2 (validation) | Run both paths against the same iteration, confirm bug report and YouTrack URL parity. |
| Phase 3 (cleanup) | Add `mitm_enabled: false` flag to `config.yaml`. Hide MITM panels when flag is false. Move `squash_capture.py` to `scripts/legacy/`. Remove `.capture_mode` state file logic. |

---

## 12. Tech Stack — Additions

The existing `pyproject.toml` already declares `crewai`, `mitmproxy`, `streamlit`, `pyyaml`.

Add:
- `httpx>=0.27.0` — Squash API client (sync)
- `pydantic>=2.0` — model validation (`crewai` already pulls a compatible version; pin carefully to avoid conflicts)

Do NOT add: `respx`, `rich`, `jinja2`, `python-dotenv`, `pydantic-settings` — none are needed.

---

## 13. Milestones

1. **Credentials & config** — `squash_token.txt.example`, `load_squash_token()` in `__init__.py`, `squash:` section in `config.yaml`. Smoke-test auth with a direct `httpx` call to `/iterations/17706`.
2. **`squash_client.py`** — Bearer auth, four GET methods (`get_iteration`, `list_test_plan`, `get_execution`, `list_execution_steps`), HAL `_paginate()` helper. Verify against live endpoints.
3. **`squash_models.py`** — Pydantic v2 models for `TestPlanItem`, `Execution`, `ExecutionStep` covering real REST API fields.
4. **`squash_extractor.py`** — Iteration → failed items → normalized execution dicts. Assert output dict keys match what `analyze_json_data()` expects (`id`, `executionStatus`, `executionStepViews`, `comment`, `lastExecutedOn`, `lastExecutedBy`, `name`).
5. **`squash_api_panel.py`** — Streamlit panel for iteration ID input, error handling, session state population, hooks into existing crew pipeline.
6. **Wire panel into existing UI** — Add `squash_api_panel` alongside MITM panels in `gherkin_page.py` and `testcases_page.py`.
7. **Integration test** — Run against iteration `17706`, confirm the expected failing test case appears and the crew produces a valid bug report + YouTrack URL.
8. **MITM deprecation label** — Mark MITM panels as "Legacy" in the UI header/caption.

---

## 14. Verification Target

First live test against iteration `17706`:
- At least one failed test plan item returned
- Normalized execution dict has all required keys and non-empty `executionStepViews`
- `format_bug_description()` / `format_testcase_bug_description()` produce the same output as when fed a MITM-captured JSON for the same execution
- Crew completes and `youtrack_url.txt` contains a valid pre-filled URL

---

## 15. Open Questions

- ~~Does `GET /executions/{executionId}` include the `comment` field?~~ **Confirmed: YES, field is present; value is `null` when tester left no comment. Fallback: use `iteration.description`.** ✓
- ~~Do REST execution step responses include raw HTML in `action` and `comment`?~~ **Confirmed: YES for `action` and `expected_result`; `comment` is raw HTML or `null`. `clean_html()` works unchanged.** ✓
- Is the Squash Bearer token scoped read-only? Read-only is sufficient — confirm the token cannot mutate data before sharing it widely.
- Should multiple iteration IDs be processable in one session? Not in scope for Phase 1; single iteration per run.
- The `execution.custom_fields` array contains a `YouTrack_Ticket` entry. Should the extractor surface this so the UI can warn the tester that a ticket may already exist? Low priority — note for Phase 2.

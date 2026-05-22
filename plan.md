# BugBuilder — Squash REST API → YouTrack URL Plan

A migration plan to **replace the mitmproxy capture layer with direct Squash TM REST API calls**, while keeping the existing CrewAI agents, prompts, Streamlit UI, and YouTrack URL templating untouched.

The data source changes. Everything downstream of `bug_description` (the formatted text the crew consumes) stays the same.

## 1. Goal

- **Input:** an iteration ID (e.g. `17706`) or an explicit execution ID, entered in the Streamlit UI or passed on the CLI. No proxied browser. No `.capture_mode`. No captured JSON files on disk.
- **Pull, don't sniff.** The app calls Squash TM's REST API to fetch test-plan items, executions, and execution steps directly.
- **Output is unchanged:** one markdown bug report + one pre-filled YouTrack `newIssue?…` URL per failure, plus the consolidated `all_youtrack_urls_*.txt` file.
- **Two modes preserved:**
  - **gherkin** — one bug per failed step in a single execution (today's `bug_report_specialist`).
  - **testcases** — one bug per failed test-plan item in an iteration, using the consolidated testcase narrative (today's `testcase_bug_report_specialist`).

## 2. What's being removed

- `squash_capture.py` (mitmproxy addon) — delete.
- `mitmproxy>=10.0.0` dependency in `pyproject.toml` — remove.
- `.capture_mode` state file and the read/write logic in `streamlit_app.py` + `squash_capture.py` — remove.
- `captured_squash_data/` and `captured_testcase_data/` folders — remove from the runtime path. Keep the existing fixture `execution_877264_20260520_003419_847125.json` under `tests/fixtures/` for unit tests only.
- `main.start_mitm_proxy`, `launch_full_stack`'s mitm subprocess, and the `ports.mitm_proxy` / `ports.mitm_web` keys in `config.yaml` — remove.
- `browser_setup.md` — archive (no longer needed for end users; keep only if useful for legacy debugging).
- `main.get_latest_captured_file` and the file-based branches in `get_execution_payloads` — remove.

## 3. What stays exactly as-is

- `src/bug_builder/crew.py` — the crew object and mode-aware task wiring.
- `src/bug_builder/config/agents.yaml` and `tasks.yaml` — all three agents (`bug_report_specialist`, `testcase_bug_report_specialist`, `youtrack_url_generator`) and their tasks.
- YouTrack URL templating in `config.yaml` (`youtrack.projects[*].url_template`, `{board_encoded}`, `{board_sprint_encoded}`, `{parent_ticket}`).
- Athena LLM wiring (`config.llm.*`, `athena_token.txt`, `.env`).
- Streamlit UI shell: `streamlit_app.py`, `ui/header.py`, `ui/services/session_service.py`, `ui/modes/gherkin_page.py`, `ui/modes/testcases_page.py` — these get new data-source calls but their layout stays.
- Helpers in `utils.py`: `clean_html`, `extract_parent_ticket`, `extract_scenario_name`, `get_board_sprint`, `build_inputs`.
- The `bug_description` *string format* consumed by the crew. We will adapt REST payloads into the same camelCase shape (`executionStepViews`, `executionStatus`, `lastExecutedOn`, `comment`, `prerequisite`, …) that today's extractors already consume, so `extract_full_scenario`, `extract_failed_tests`, `format_bug_description_for_ai`, and `extract_testcase_narrative` need **no changes**.

## 4. What's being added

### 4.1 `src/bug_builder/squash_client.py` (new)

Thin `httpx` wrapper. Sync client is enough — Streamlit is single-user and the volumes are small (tens of items per iteration).

Responsibilities:

- Read `SQUASH_BASE_URL`, `SQUASH_USERNAME`, `SQUASH_TOKEN` from `.env` (via the existing `python-dotenv` + `os.getenv`, no new settings library).
- HTTP Basic auth header from `username:token`.
- One `get_json(path, params)` helper that:
  - prefixes the base URL,
  - injects `?size=200` for list endpoints,
  - follows HAL `_links.next` until exhausted, concatenating `_embedded.<collection>` arrays,
  - raises on `>= 400` with a typed `SquashAPIError(status, url, body[:500])`,
  - retries 5xx / network errors twice with exponential backoff (1s, 2s).
- Typed methods used by the extractor:

| Method                                | Endpoint                                                |
| ------------------------------------- | ------------------------------------------------------- |
| `get_iteration(iteration_id)`         | `/iterations/{id}`                                       |
| `list_test_plan(iteration_id)`        | `/iterations/{id}/test-plan?size=200` (paged)            |
| `get_test_plan_item(itpi_id)`         | `/iteration-test-plan-items/{itpiId}` (only if needed)   |
| `list_executions(itpi_id)`            | `/iteration-test-plan-items/{itpiId}/executions`         |
| `get_execution(execution_id)`         | `/executions/{id}`                                       |
| `list_execution_steps(execution_id)`  | `/executions/{id}/execution-steps` (paged)               |
| `list_execution_issues(execution_id)` | `/executions/{id}/issues` (optional, for dedupe)         |

Base URL assumption: `https://squash.internetbrands.com/api/rest/latest` — to be confirmed against a live `curl -u user:token` smoke test before coding.

### 4.2 `src/bug_builder/squash_normaliser.py` (new)

REST responses use snake_case + HAL (`execution_status`, `last_executed_on`, `_embedded.executions[]`, `_embedded.execution_steps[]`). Existing extractors expect the camelCase/internal-API shape (`executionStatus`, `lastExecutedOn`, `executionStepViews`). The normaliser converts REST → internal so that the rest of the pipeline doesn't change:

- `normalise_execution(rest_execution, rest_steps) -> dict` returning the same key set as today's captured payload:
  `id`, `name`, `testCaseId`, `iterationId`, `executionStatus`, `executionStepViews[]`, `comment`, `prerequisite`, `lastExecutedOn`, `lastExecutedBy`, `projectId`.
- Each step normalised to `{id, order, executionStatus, action, expectedResult, comment, lastExecutedOn, lastExecutedBy}`.
- HTML fields (`comment`, `prerequisite`, `action`) are passed through unchanged — `utils.clean_html` already handles them.
- Snake_case → camelCase mapping table lives here, in one place. If Squash changes a field name later, only this file moves.

Unit-test the normaliser against the recorded fixture: the same execution viewed through the internal API (already on disk as `execution_877264_*.json`) must equal `normalise_execution(rest_execution_877264, rest_steps_877264)`. Capture those REST payloads on first contact and check them in under `tests/fixtures/rest/`.

### 4.3 `src/bug_builder/extractor.py` (new — replaces `main.get_execution_payloads`)

Two public functions, returning the same list-of-dicts shape today's `process_squash` already consumes (`{file_path, file_name, json_data, execution_id, last_executed_on, ctime}` — but `file_path` / `file_name` become `source` strings like `"squash:execution:877264"` and `ctime` becomes the `last_executed_on` parsed as epoch):

- `fetch_failed_executions_for_iteration(iteration_id) -> list[dict]`:
  1. `client.get_iteration(iteration_id)` — sanity check (404 → friendly error in UI).
  2. `client.list_test_plan(iteration_id)` — paged.
  3. Keep only items with `execution_status == "FAILURE"`.
  4. For each failed item: pick the latest execution by `last_executed_on desc`, fetch `get_execution` + `list_execution_steps`, run through `normalise_execution`, dedupe by `(execution_id, last_executed_on)`.
- `fetch_execution(execution_id) -> dict | None`:
  Single-execution entry point. Calls `get_execution` + `list_execution_steps`, normalises, returns `None` if the execution exists but `is_failed_execution_payload` is false.

`is_execution_payload` and `is_failed_execution_payload` from `main.py` move into `extractor.py` and are re-used unchanged.

### 4.4 Streamlit UI changes (`ui/modes/*.py`, `streamlit_app.py`)

Replace the file-watching panels with input forms:

- **gherkin tab:** text input "Execution ID" (or "Iteration ID — process the single most recent failed execution"). Submit button → `fetch_execution(...)` or pick first item of `fetch_failed_executions_for_iteration(...)`.
- **testcases tab:** text input "Iteration ID". Submit button → `fetch_failed_executions_for_iteration(...)`.
- Show a spinner during the REST calls. Show the iteration name / failed-count summary before kickoff.
- Keep the existing project / board / sprint / parent-ticket picker — no change.
- Drop the "📄 New file detected" / "👀 Waiting for…" affordances.

The `analyze_json_data` and `analyze_testcase_files` UI hooks keep their signatures; only their callers change.

### 4.5 CLI changes (`src/bug_builder/main.py`)

- `python main.py squash gherkin <execution_id>` — process one execution.
- `python main.py squash testcases <iteration_id>` — process all failed items in an iteration.
- `python main.py launch` only starts Streamlit; the mitm subprocess is gone.
- `cleanup_on_startup` keeps cleaning generated `bug_report_*.md` / `youtrack_url_*.txt` / `all_youtrack_urls_*.txt` but no longer touches capture folders.

## 5. Tech stack delta vs. today

Add to `pyproject.toml`:

- `httpx>=0.27`

Remove:

- `mitmproxy>=10.0.0`

Keep:

- `crewai[openai,tools]==1.9.3`, `streamlit>=1.55`, `pyyaml>=6`, `python-dotenv`.

No new framework needed. Not introducing `pydantic` v2, `pydantic-settings`, `respx`, or `jinja2` — the existing string-template approach and dict shapes are sufficient and avoid a wider refactor.

## 6. Squash REST contract we depend on

- **Base URL:** `https://squash.internetbrands.com/api/rest/latest` (to be confirmed).
- **Auth:** HTTP Basic (`Authorization: Basic <b64(username:token)>`). A Squash personal access token is preferred over a password.
- **Failure marker:** `execution_status == "FAILURE"` at item or step level. Other statuses (SUCCESS, BLOCKED, UNTESTABLE, READY, RUNNING, SETTLED) are non-failures.
- **Latest execution rule:** sort `executions[]` by `last_executed_on` desc, take index 0. Fallback if the field is missing: the last element returned by Squash.
- **Pagination:** every list endpoint returns `_embedded.<collection>` + `page` + `_links.next`. Always request `size=200` and follow `next` until absent.
- **Out of scope:** `Xsquash4Jira REST API 11.0.0` is for Jira sync. We don't call it.

## 7. Configuration

`.env` (new keys added; nothing renamed):

```
# Existing
ATHENA_BASE_URL=https://athena.webmdhelios.com/v1
ATHENA_MODEL=saas-openai-gpt-4.1
OTEL_SDK_DISABLED=true
CREWAI_TELEMETRY_OPT_OUT=true

# New
SQUASH_BASE_URL=https://squash.internetbrands.com/api/rest/latest
SQUASH_USERNAME=<tester ldap or service account>
SQUASH_TOKEN=<personal access token, never a password>
SQUASH_TIMEOUT_S=30
```

`config.yaml` changes:

- Remove `ports.mitm_proxy` (8080) and `ports.mitm_web` (8081). Keep `ports.streamlit`.
- Remove `paths.capture_dir`, `paths.testcase_capture_dir`, `paths.addon_script`.
- Add `squash.page_size: 200` and `squash.max_retries: 2` (only if we want to override the defaults; otherwise leave to code constants).
- `youtrack.*` is untouched.

`athena_token.txt` is untouched.

## 8. Data flow (after migration)

### gherkin path

1. UI / CLI submits `execution_id`.
2. `extractor.fetch_execution(execution_id)` calls Squash REST, normalises into the existing camelCase shape.
3. `is_failed_execution_payload` gate — short-circuit with a UI message if no failed steps.
4. `extract_failed_tests` → `extract_full_scenario` → `format_bug_description_for_ai` (unchanged from today).
5. `BugBuilder().crew(mode='gherkin').kickoff(inputs=...)` per failed step.
6. Bug-report + URL files written and consolidated exactly as today.

### testcase path

1. UI / CLI submits `iteration_id`.
2. `extractor.fetch_failed_executions_for_iteration(iteration_id)` returns the deduped list of failed executions (one per failed test-plan item).
3. For each: `extract_testcase_narrative(json_data, testCaseId)` (unchanged).
4. `BugBuilder().crew(mode='testcase').kickoff(inputs=...)` per testcase.
5. Outputs aggregated into `all_youtrack_urls_<iteration_id>_testcases_<ts>.txt`.

## 9. Repository layout (after migration)

```
bug_builder/
├── README.md                                 ← rewrite "Squash TM Workflow" section
├── plan.md                                   ← this document
├── plan-bugBuilder.prompt.md                 ← prior Cowork plan, archive
├── config.yaml                               ← mitm/capture keys removed
├── .env / .env.example                       ← SQUASH_* added
├── athena_token.txt                          ← unchanged
├── pyproject.toml                            ← drop mitmproxy, add httpx
├── streamlit_app.py                          ← input forms replace file watchers
├── src/bug_builder/
│   ├── __init__.py
│   ├── crew.py                               ← unchanged
│   ├── main.py                               ← squash subcommands take IDs; no mitm launch
│   ├── utils.py                              ← unchanged
│   ├── squash_client.py                      ← NEW
│   ├── squash_normaliser.py                  ← NEW
│   ├── extractor.py                          ← NEW (moves payload functions out of main.py)
│   ├── config/{agents,tasks}.yaml            ← unchanged
│   └── ui/
│       ├── header.py
│       ├── services/session_service.py
│       └── modes/{gherkin_page,testcases_page}.py  ← submit-ID forms
├── tests/
│   ├── fixtures/
│   │   ├── internal/execution_877264.json    ← preserved from today's capture
│   │   └── rest/
│   │       ├── execution_877264.json         ← live REST capture, one-time
│   │       └── execution_steps_877264.json
│   ├── test_squash_client.py                 ← network-mocked
│   ├── test_squash_normaliser.py             ← internal == normalise(rest)
│   └── test_extractor.py
└── (REMOVED) squash_capture.py, captured_squash_data/, captured_testcase_data/, .capture_mode
```

## 10. Verification

### 10.1 Smoke test before coding

`curl -u $SQUASH_USERNAME:$SQUASH_TOKEN https://squash.internetbrands.com/api/rest/latest/iterations/<known_iteration_id>` must return 200 with JSON. If it returns 401, auth scheme is not Basic — re-plan with the team.

### 10.2 Parity test against the existing fixture

The on-disk fixture `captured_squash_data/execution_877264_20260520_003419_847125.json` was captured at the internal `/backend/...` endpoint. Goal: prove that `normalise_execution(rest_execution_877264, rest_steps_877264)` produces a dict equal — modulo fields we don't use — to that fixture, for these load-bearing values:

- `id == 877264`, `testCaseId == 459452`, `executionStatus == "FAILURE"`.
- `comment` contains `Build: Medscape-Android-PoC-12.36.0-13267484`, `Device: Galaxy A32 OS 13`, `Subtask of: WBMDMOB-61138`.
- `executionStepViews[0]` has `order == 0`, `executionStatus == "FAILURE"`, `comment` containing "Full player does not open".
- `utils.extract_parent_ticket(...)` returns `"WBMDMOB-61138"`.

If that holds, the entire downstream pipeline is guaranteed to behave identically to today.

### 10.3 End-to-end test

Run `python main.py squash gherkin 877264`. Expect 1 bug report, 1 YouTrack URL, build/device/parent ticket as above. Click the URL and verify YouTrack opens with the form pre-filled.

## 11. Migration milestones

1. **Spike + auth check.** Confirm base URL, auth scheme, and field names with one manual `curl`. Capture two real REST responses (`execution`, `execution-steps`) for fixture 877264 and save under `tests/fixtures/rest/`. *blocking everything below.*
2. **`squash_client.py`** with auth + pagination + retries; one unit test per public method using mocked `httpx` (no real network in CI).
3. **`squash_normaliser.py`** with the parity test against `tests/fixtures/internal/execution_877264.json`.
4. **`extractor.py`** with `fetch_execution` and `fetch_failed_executions_for_iteration`, plus moving `is_execution_payload` / `is_failed_execution_payload` over.
5. **`main.py` refactor:** `process_squash` takes `payloads` from `extractor` instead of `get_execution_payloads`; remove `start_mitm_proxy` and the capture-folder branches; rename CLI args to take IDs.
6. **Streamlit refactor:** swap file-watch panels for ID-entry forms. Wire spinners and friendly errors for 401 / 404 / network failures.
7. **Cleanup:** delete `squash_capture.py`, the two capture folders (after backing the lone fixture up), `.capture_mode`, mitm dependency, mitm port config. Update `README.md` and `.gitignore`.
8. **Optional:** add `list_execution_issues` and skip executions that already have a linked YouTrack issue (see Open Questions).

Each milestone leaves `main` runnable; the old mitm path is removed only at step 7, after the REST path has proved itself against the parity fixture.

## 12. Open questions to confirm before coding

- **Auth scheme.** Is the Squash instance Basic-auth-friendly with PATs, or does it require a bearer token / cookie? One `curl -u` test answers this.
- **Field names.** Are list payloads paginated as `_embedded.test_plan_items` or `_embedded.itemsTestPlan`? The HAL collection names differ across Squash versions. Capture one real response before fixing the normaliser.
- **Execution → test-plan-item linkage.** Confirm that `GET /executions/{id}` returns the testcase id directly, or whether we need a separate `GET /iteration-test-plan-items/{itpiId}` call. Affects the `fetch_execution` path.
- **Already-filed dedupe.** When `--skip-already-linked` (planned flag) is set, should we trust `list_execution_issues`, or scan the execution comment for `[A-Z]+-\d+` patterns? Pick one source of truth.
- **Rate limits.** Does Squash impose any rate limits we need to respect when iterating large test plans? Decide whether to throttle in `squash_client`.
- **Attachments.** REST exposes step attachments; do we want to include their links in the bug report, or leave them out as today?
- **Mode-name canonicalisation.** Today `process_squash` accepts `'testcase'` but the CLI passes `'testcases'`, and the latter is silently routed to the gherkin branch in `main.py`. Fix as part of step 5 — pick `'testcases'` everywhere.

## 13. Not in scope

- Calling YouTrack's REST API to create issues. We continue to generate pre-filled `newIssue?…` URLs only.
- The `Xsquash4Jira REST API`. This repo targets YouTrack.
- Replacing Athena with OpenAI. Athena is mandated.
- A from-scratch new repo. This is a brownfield refactor of `bug_builder/` — the agents, prompts, URL templates, and Streamlit shell stay.

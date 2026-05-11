import os
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"
import streamlit as st
import json
import re
import time
import traceback
import hashlib
from datetime import datetime
from bug_builder import app_config, athena_token
config = app_config
from src.bug_builder.crew import BugBuilder
from src.bug_builder.ui.header import render_header
from src.bug_builder.ui.modes.gherkin_page import render_gherkin_mitm_panel
from src.bug_builder.ui.modes.testcases_page import render_testcases_mitm_panel
from src.bug_builder.ui.services.session_service import init_session_state, reset_body_state
from urllib.parse import quote_plus

st.set_page_config(
    page_title="Bug Builder - Squash TM Processor",
    page_icon="🐛",
    layout="wide"
)

init_session_state()


def persist_capture_mode(mode):
    """Persist current UI mode so mitm addon can route files accordingly."""
    mode_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".capture_mode")
    normalized = (mode or "gherkin").strip().lower()
    if normalized not in {"gherkin", "testcases"}:
        normalized = "gherkin"
    try:
        with open(mode_file, "w", encoding="utf-8") as f:
            f.write(normalized)
    except Exception as exc:
        st.warning(f"Could not persist capture mode to addon: {exc}")


def get_board_sprint(project, board_name, sequential_sprint=None):
    """Generate sprint string for selected project and board"""
    sprint_format = project['sprint_format']

    if sprint_format == 'sequential':
        # MEDAIS style — Sprint 30
        sprint_prefix = next(
            (b['sprint_prefix'] for b in project['boards'] if b['name'] == board_name),
            board_name
        )
        return f"{sprint_prefix} Sprint {sequential_sprint}"

    else:
        # WBMDMOB style — year.week
        current_week = datetime.now().isocalendar()[1]
        if current_week % 2 == 0:
            sprint_number = current_week - 1
        else:
            sprint_number = current_week
        current_year = datetime.now().year
        sprint_prefix = next(
            (b['sprint_prefix'] for b in project['boards'] if b['name'] == board_name),
            board_name
        )
        return f"{sprint_prefix} - Sprint {current_year}.{sprint_number:02d}"


def clean_html(html_text):
    """Remove HTML tags and clean up whitespace"""
    if not html_text:
        return ""
    clean_text = re.sub(r'<[^>]+>', ' ', html_text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text


def extract_execution_comment(json_data):
    """Extract and clean the root-level execution comment (build/device info)"""
    comment_html = json_data.get('comment', '')
    if not comment_html or comment_html.strip() == '':
        return "Build and device information not provided."
    clean_comment = clean_html(comment_html)
    return clean_comment if clean_comment.strip() else "Not provided"


def extract_scenario_name(action_text):
    """Extract ONLY the scenario title, not the Gherkin steps"""
    if not action_text:
        return "Unknown Scenario"

    clean_text = clean_html(action_text)

    scenario_match = re.search(r'Scenario(?:\s+Outline)?\s*\d*\s*:\s*(.+)', clean_text, re.IGNORECASE)
    if scenario_match:
        scenario_name = scenario_match.group(1).strip()

        gherkin_keywords = ['Given', 'When', 'Then', 'And', 'But']
        for keyword in gherkin_keywords:
            if keyword in scenario_name:
                scenario_name = scenario_name.split(keyword)[0].strip()
                break

        scenario_name = re.sub(r'[\[\]\(\)\*\_\~\`]', '', scenario_name)
        return scenario_name[:100] if len(scenario_name) > 100 else scenario_name

    lines = [line.strip() for line in clean_text.split() if line.strip()]
    if lines:
        first_line = ' '.join(lines[:10])
        first_line = re.sub(r'[\[\]\(\)\*\_\~\`]', '', first_line)
        return first_line[:100] + "..." if len(first_line) > 100 else first_line

    return "Unknown Scenario"


def get_latest_captured_file():
    """Get the most recently captured JSON file"""
    captured_dir = get_capture_dir('gherkin')
    if not os.path.exists(captured_dir):
        return None
    json_files = [f for f in os.listdir(captured_dir) if f.endswith('.json')]
    if not json_files:
        return None
    latest_file = max(json_files, key=lambda f: os.path.getctime(os.path.join(captured_dir, f)))
    return os.path.join(captured_dir, latest_file)


def get_capture_dir(mode):
    """Return mode-specific capture directory."""
    if mode == 'testcases':
        return config['paths'].get('testcase_capture_dir', 'captured_testcase_data')
    return config['paths']['capture_dir']


def is_execution_payload(json_data):
    """Eligible execution payload has execution status fields for executed steps."""
    if not isinstance(json_data, dict):
        return False

    if 'executionStatus' not in json_data:
        return False

    step_views = json_data.get('executionStepViews')
    if not isinstance(step_views, list):
        return False

    for step in step_views:
        if isinstance(step, dict) and 'executionStatus' in step and 'order' in step:
            return True

    return False


def is_failed_execution_payload(json_data):
    """Execution is relevant only if root or any step has FAILURE."""
    if not is_execution_payload(json_data):
        return False

    root_status = str(json_data.get('executionStatus', '')).upper()
    if root_status == 'FAILURE':
        return True

    for step in json_data.get('executionStepViews', []):
        if str(step.get('executionStatus', '')).upper() == 'FAILURE':
            return True

    return False


def _action_hash(action_text):
    normalized = clean_html(action_text or '').lower().strip()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]


def get_execution_file_bundle_for_testcases():
    """Load both capture folders and return eligible deduplicated execution payloads."""
    candidate_dirs = [
        get_capture_dir('gherkin'),
        get_capture_dir('testcases'),
    ]
    existing_dirs = [d for d in candidate_dirs if os.path.exists(d)]
    if not existing_dirs:
        return {
            'files': [],
            'skipped': [
                f"Directory not found: {candidate_dirs[0]}",
                f"Directory not found: {candidate_dirs[1]}",
            ]
        }

    deduped_by_execution = {}
    skipped = []

    for captured_dir in existing_dirs:
        json_files = [f for f in os.listdir(captured_dir) if f.endswith('.json')]
        json_files = sorted(json_files, key=lambda f: os.path.getctime(os.path.join(captured_dir, f)))

        for file_name in json_files:
            file_path = os.path.join(captured_dir, file_name)
            try:
                with open(file_path, 'r') as f:
                    payload = json.load(f)
            except Exception as exc:
                skipped.append(f"Malformed JSON skipped: {file_name} ({exc})")
                continue

            if not is_execution_payload(payload):
                skipped.append(f"Non-execution payload skipped: {file_name}")
                continue

            if not is_failed_execution_payload(payload):
                skipped.append(f"No failure found, skipped: {file_name}")
                continue

            execution_id = str(payload.get('id', 'unknown'))
            last_executed_on = str(payload.get('lastExecutedOn', 'unknown'))
            dedupe_key = (execution_id, last_executed_on)
            ctime = os.path.getctime(file_path)

            existing = deduped_by_execution.get(dedupe_key)
            if existing is None or ctime > existing['ctime']:
                deduped_by_execution[dedupe_key] = {
                    'file_path': file_path,
                    'file_name': file_name,
                    'json_data': payload,
                    'execution_id': execution_id,
                    'last_executed_on': last_executed_on,
                    'ctime': ctime,
                }

    deduped_files = sorted(
        deduped_by_execution.values(),
        key=lambda item: item['ctime']
    )

    return {'files': deduped_files, 'skipped': skipped}


def analyze_testcase_files(file_bundle):
    """Aggregate failed testcase executions (one item per execution/testcase)."""
    files = file_bundle.get('files', [])
    skipped = file_bundle.get('skipped', [])

    total_steps = 0
    passed_steps = 0
    failed_step_count = 0
    failed_tests = []
    execution_map = {}

    for file_info in files:
        json_data = file_info['json_data']
        execution_key = f"{file_info['execution_id']}|{file_info['last_executed_on']}"
        execution_map[execution_key] = json_data

        failed_steps_for_case = []

        for step in json_data.get('executionStepViews', []):
            status = str(step.get('executionStatus', '')).upper()
            total_steps += 1

            if status == 'SUCCESS':
                passed_steps += 1
                continue

            if status != 'FAILURE':
                continue

            failed_step_count += 1
            failed_steps_for_case.append({
                'step_id': step.get('id'),
                'order': step.get('order'),
                'action': step.get('action', ''),
                'comment': step.get('comment', 'No actual result provided'),
                'executed_on': step.get('lastExecutedOn'),
                'executed_by': step.get('lastExecutedBy'),
            })

        if failed_steps_for_case:
            failed_tests.append({
                'execution_id': file_info['execution_id'],
                'execution_name': json_data.get('name', 'Unknown Execution'),
                'execution_key': execution_key,
                'source_file': file_info['file_name'],
                'executed_on': json_data.get('lastExecutedOn'),
                'executed_by': json_data.get('lastExecutedBy'),
                'failed_step_count': len(failed_steps_for_case),
                'failed_steps': failed_steps_for_case,
            })

    return {
        'mode': 'testcases',
        'execution_id': 'MULTI',
        'execution_name': f"{len(files)} execution file(s)",
        'executed_by': 'Multiple',
        'executed_on': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_steps': total_steps,
        'passed_steps': passed_steps,
        'failed_steps': failed_step_count,
        'failed_case_count': len(failed_tests),
        'failed_tests': failed_tests,
        'files_processed': len(files),
        'skipped_files': skipped,
        'execution_map': execution_map,
    }


def analyze_json_data(json_data):
    """Analyze JSON data and extract test statistics"""
    if not json_data or 'executionStepViews' not in json_data:
        return None

    total_steps = len(json_data.get('executionStepViews', []))
    passed_steps = 0
    failed_steps = 0
    failed_tests = []

    for step in json_data.get('executionStepViews', []):
        status = step.get('executionStatus', '').upper()
        if status == 'SUCCESS':
            passed_steps += 1
        elif status == 'FAILURE':
            failed_steps += 1
            failed_tests.append({
                'step_id': step.get('id'),
                'order': step.get('order'),
                'action': step.get('action', ''),
                'comment': step.get('comment', 'No actual result provided'),
                'executed_on': step.get('lastExecutedOn'),
                'executed_by': step.get('lastExecutedBy')
            })

    return {
        'execution_id': json_data.get('id'),
        'execution_name': json_data.get('name'),
        'executed_by': json_data.get('lastExecutedBy'),
        'executed_on': json_data.get('lastExecutedOn'),
        'total_steps': total_steps,
        'passed_steps': passed_steps,
        'failed_steps': failed_steps,
        'failed_tests': failed_tests
    }


def format_bug_description(failed_test, execution_context, json_data):
    """Convert failed test to bug description format with build/device info"""
    clean_action = clean_html(failed_test['action'])
    build_device_info = extract_execution_comment(json_data)

    description = f"""
Test execution {execution_context['execution_id']} failed.

Test: {execution_context['execution_name']}
Executed by: {execution_context['executed_by']}
Executed on: {execution_context['executed_on']}

BUILD & DEVICE INFO:
{build_device_info}

FAILED SCENARIO:
{clean_action}

ACTUAL RESULT:
{failed_test['comment']}

STEP ORDER: {failed_test['order']}
STEP ID: {failed_test['step_id']}
"""
    return description.strip()


def format_testcase_bug_description(failed_case, json_data):
    """Create one consolidated bug description per failed testcase execution."""
    build_device_info = extract_execution_comment(json_data)
    all_steps = json_data.get('executionStepViews', [])

    all_actions_lines = []
    for step in all_steps:
        order = step.get('order', '?')
        action = clean_html(step.get('action', ''))
        all_actions_lines.append(f"{order}. {action}")

    failed_lines = []
    for step in failed_case.get('failed_steps', []):
        order = step.get('order', '?')
        action = clean_html(step.get('action', ''))
        actual = clean_html(step.get('comment', 'No actual result provided'))
        failed_lines.append(f"{order}. Action: {action} | Actual: {actual}")

    description = f"""
Testcase execution {failed_case.get('execution_id', 'unknown')} failed.

Testcase: {failed_case.get('execution_name', 'Unknown Execution')}
Executed by: {failed_case.get('executed_by', 'Unknown')}
Executed on: {failed_case.get('executed_on', 'Unknown')}

BUILD & DEVICE INFO:
{build_device_info}

ALL TESTCASE ACTIONS:
{chr(10).join(all_actions_lines)}

FAILED ACTION OUTCOMES:
{chr(10).join(failed_lines)}

ACTUAL RESULT:
Testcase did not complete successfully due to one or more failed actions.
"""
    return description.strip()


def check_for_new_mitm_file():
    """Check if there's a new MITM captured file"""
    latest_file = get_latest_captured_file()
    if latest_file and latest_file != st.session_state.last_checked_file:
        return latest_file
    return None


# ─── Main UI ──────────────────────────────────────────────────────────────────

header_context = render_header(config)
if header_context['mode_changed']:
    st.session_state.mode = header_context['selected_mode']
    reset_body_state()
    persist_capture_mode(st.session_state.mode)
    st.rerun()

st.session_state.mode = header_context['selected_mode']
persist_capture_mode(st.session_state.mode)

selected_project = header_context['selected_project']
selected_board = header_context['selected_board']
selected_sprint = header_context['selected_sprint']

active_capture_dir = get_capture_dir(st.session_state.mode)
st.caption(f"Active mode: {st.session_state.mode.upper()}")

st.divider()

# Input Sources Section
st.header("📥 Input Sources")

col1, col2 = st.columns(2)

# ─── MITM Monitoring ──────────────────────────────────────────────────────────
with col1:
    if st.session_state.mode == 'gherkin':
        render_gherkin_mitm_panel(
            check_for_new_mitm_file=check_for_new_mitm_file,
            get_capture_dir=get_capture_dir,
            is_execution_payload=is_execution_payload,
            is_failed_execution_payload=is_failed_execution_payload,
            analyze_json_data=analyze_json_data,
        )
    else:
        render_testcases_mitm_panel(
            get_execution_file_bundle_for_testcases=get_execution_file_bundle_for_testcases,
            get_capture_dir=get_capture_dir,
            analyze_testcase_files=analyze_testcase_files,
        )

# ─── Natural Language Bug Input ───────────────────────────────────────────────
with col2:
    st.subheader("📝 Describe Your Bug")

    MIN_CHARS = 50

    bug_input = st.text_area(
        label="Describe the bug in your own words",
        placeholder=(
            "Example: Build: Medscape iOS v12.35.0 Device: iPhone 16 OS 18.3.1."
            "I tapped the minimize button on the podcast player and the app crashed immediately. "
            "Expected the player to minimize to the bottom bar."
        ),
        height=180,
        key="nl_bug_input_area"
    )

    char_count = len(bug_input.strip())

    if char_count < MIN_CHARS:
        st.markdown(
            f"<small style='color: #ff4b4b;'>Characters: {char_count} / {MIN_CHARS} minimum</small>",
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            f"<small style='color: #21c354;'>Characters: {char_count} ✓</small>",
            unsafe_allow_html=True
        )

    if st.button("🎫 Create YT Ticket", type="primary"):
        if char_count < MIN_CHARS:
            st.warning(f"⚠️ Please describe the bug in at least {MIN_CHARS} characters before generating a ticket.")
        else:
            with st.spinner("🤖 Generating bug report..."):
                try:
                    bug_description = f"""
Test Execution: Manual Entry
Test Suite: Manual Bug Report
Executed By: QA Engineer
Executed On: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

BUILD & DEVICE INFO:
{bug_input.strip()}

FAILED SCENARIO:
{bug_input.strip()}

ACTUAL RESULT:
See description above.
"""

                    inputs = {
                        'bug_description': bug_description,
                        'board_sprint': get_board_sprint(selected_project, selected_board, selected_sprint),
                        'board': selected_board,
                        'url_template': selected_project['url_template'],
                        'current_year': str(datetime.now().year),
                        # Pre-encoded versions for URL template
                        'board_encoded': quote_plus(selected_board),
                        'board_sprint_encoded': quote_plus(
                            get_board_sprint(selected_project, selected_board, selected_sprint)),
                    }

                    BugBuilder().crew().kickoff(inputs=inputs)

                    youtrack_url = None
                    if os.path.exists('youtrack_url.txt'):
                        with open('youtrack_url.txt', 'r') as f:
                            youtrack_url = f.read().strip()
                        os.remove('youtrack_url.txt')

                    if os.path.exists('bug_report.md'):
                        os.remove('bug_report.md')

                    if youtrack_url:
                        st.session_state.nl_processing_result = youtrack_url
                        st.success("✅ Bug report generated!")
                        st.rerun()
                    else:
                        st.error("❌ Failed to generate YouTrack URL.")

                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")

    # Show result if available
    if st.session_state.nl_processing_result:
        st.markdown("---")
        st.markdown("**🔗 Your YouTrack Ticket:**")
        st.markdown(f"[📋 Open in YouTrack]({st.session_state.nl_processing_result})")

        # st.info("💡 Enable popups for localhost:8501 before clicking.")
        # if st.button("🌐 Open URL"):
        #     st.components.v1.html(
        #         f"<script>window.open('{st.session_state.nl_processing_result}', '_blank');</script>",
        #         height=0
        #     )
        #
        # if st.button("🔄 Create Another"):
        #     st.session_state.nl_processing_result = None
        #     st.rerun()

# ─── Analysis Results Section ─────────────────────────────────────────────────
if st.session_state.analysis_results:
    st.header("📊 Analysis Results")

    results = st.session_state.analysis_results
    source_icon = "🔍" if st.session_state.input_source == "mitm" else "✏️"
    st.info(f"{source_icon} Data source: {st.session_state.input_source.upper()}")

    if results.get('mode') == 'testcases':
        st.metric("Failed Testcases", results.get('failed_case_count', len(results['failed_tests'])))
    else:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Execution ID", results['execution_id'])
            st.metric("Executed By", results['executed_by'])
        with col2:
            execution_name = results.get('execution_name', 'Unknown')
            st.metric("Test Name", execution_name[:30] + "..." if len(execution_name) > 30 else execution_name)
            st.metric("Executed On", results['executed_on'])

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Steps", results['total_steps'])
        with col2:
            st.metric(
                "Passed",
                results['passed_steps'],
                delta=f"{(results['passed_steps'] / results['total_steps'] * 100):.1f}%",
                delta_color="normal"
            )
        with col3:
            st.metric(
                "Failed",
                results['failed_steps'],
                delta=f"-{(results['failed_steps'] / results['total_steps'] * 100):.1f}%",
                delta_color="inverse"
            )

    # ─── Action Buttons ───────────────────────────────────────────────────────
    st.header("🎯 Actions")

    col1, col2 = st.columns(2)

    with col1:
        if results['failed_tests']:
            if st.button("🚀 Create YouTrack Links", type="primary", use_container_width=True):
                print("✅ BUTTON CLICKED")
                print(f"✅ Failed tests count: {len(results['failed_tests'])}")
                st.session_state.processing_results = []

                progress_bar = st.progress(0)
                status_text = st.empty()

                for i, failed_test in enumerate(results['failed_tests']):
                    print(f"✅ LOOP ITERATION {i}")
                    if results.get('mode') == 'testcases':
                        status_text.text(f"Processing testcase {i + 1}/{len(results['failed_tests'])}...")
                    else:
                        status_text.text(f"Processing step {i + 1}/{len(results['failed_tests'])}...")
                    progress_bar.progress((i + 1) / len(results['failed_tests']))

                    source_json = st.session_state.json_data
                    if results.get('mode') == 'testcases':
                        execution_key = failed_test.get('execution_key')
                        source_json = results.get('execution_map', {}).get(execution_key)

                    if source_json is None:
                        st.session_state.processing_results.append({
                            'step': i + 1,
                            'order': failed_test.get('order', -1),
                            'youtrack_url': "Error occurred",
                            'status': 'error',
                            'error': 'Source execution payload not found for failed test'
                        })
                        continue

                    execution_context = {
                        'execution_id': failed_test.get('execution_id', results.get('execution_id')),
                        'execution_name': failed_test.get('execution_name', results.get('execution_name')),
                        'executed_by': failed_test.get('executed_by', results.get('executed_by')),
                        'executed_on': failed_test.get('executed_on', results.get('executed_on')),
                    }

                    if results.get('mode') == 'testcases':
                        bug_description = format_testcase_bug_description(failed_test, source_json)
                    else:
                        bug_description = format_bug_description(failed_test, execution_context, source_json)

                    inputs = {
                        'bug_description': bug_description,
                        'board_sprint': get_board_sprint(selected_project, selected_board, selected_sprint),
                        'board': selected_board,
                        'url_template': selected_project['url_template'],
                        'current_year': str(datetime.now().year),
                        'board_encoded': quote_plus(selected_board),
                        'board_sprint_encoded': quote_plus(
                            get_board_sprint(selected_project, selected_board, selected_sprint)),
                    }

                    try:
                        mode = results.get('mode', 'gherkin')
                        BugBuilder().crew(mode=mode).kickoff(inputs=inputs)

                        if os.path.exists('bug_report.md'):
                            os.remove('bug_report.md')

                        youtrack_url = "Not generated"
                        if os.path.exists('youtrack_url.txt'):
                            with open('youtrack_url.txt', 'r') as f:
                                youtrack_url = f.read().strip()
                            os.remove('youtrack_url.txt')

                        if mode == 'testcases':
                            scenario_name = failed_test.get('execution_name', 'Unknown Testcase')
                            scenario_number = i + 1
                        else:
                            scenario_name = extract_scenario_name(failed_test.get('action', ''))
                            scenario_number = (failed_test.get('order') or 0) + 1

                        st.session_state.processing_results.append({
                            'step': i + 1,
                            'order': failed_test.get('order', -1),
                            'bug_description': bug_description,
                            'youtrack_url': youtrack_url,
                            'scenario_name': scenario_name,
                            'scenario_number': scenario_number,
                            'status': 'completed'
                        })


                    except Exception as e:

                        import traceback

                        st.session_state.last_error = traceback.format_exc()

                        st.session_state.processing_results.append({

                            'step': i + 1,

                            'order': failed_test.get('order', -1),

                            'bug_description': bug_description,

                            'youtrack_url': "Error occurred",

                            'status': 'error',

                            'error': str(e)

                        })

                status_text.text("✅ All bug reports generated!")
                progress_bar.empty()
                status_text.empty()
                if st.session_state.last_error:
                    st.error(f"❌ Error details:\n{st.session_state.last_error}")
                #st.rerun()
        else:
            st.info("✅ No failed tests to process!")

    with col2:
        if st.button("🔄 Check Again", use_container_width=True):
            if st.session_state.input_source == "mitm":
                if st.session_state.mode == 'gherkin':
                    latest_file = get_latest_captured_file()
                    if latest_file:
                        try:
                            with open(latest_file, 'r') as f:
                                json_data = json.load(f)
                            st.session_state.json_data = json_data
                            st.session_state.last_checked_file = latest_file
                            results = analyze_json_data(json_data)
                            if results:
                                results['mode'] = 'gherkin'
                                results['files_processed'] = 1
                                results['skipped_files'] = []
                            st.session_state.analysis_results = results
                            st.session_state.processing_results = []
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error reading latest file: {str(e)}")
                    else:
                        st.warning("⚠️ No new MITM files found")
                else:
                    file_bundle = get_execution_file_bundle_for_testcases()
                    st.session_state.json_data = None
                    st.session_state.analysis_results = analyze_testcase_files(file_bundle)
                    st.session_state.processing_results = []
                    st.rerun()
            else:
                st.session_state.json_data = None
                st.session_state.input_source = None
                st.session_state.analysis_results = None
                st.session_state.processing_results = []
                st.rerun()

# ─── Processing Results Section ───────────────────────────────────────────────
if st.session_state.processing_results:
    st.header("📄 Generated Bug Reports")
    st.subheader("🔗 Quick Access")

    for result in st.session_state.processing_results:
        if result['status'] == 'completed' and result['youtrack_url'] != "Not generated":
            scenario_name = result.get('scenario_name', 'Unknown Scenario')
            scenario_number = result.get('scenario_number', result.get('step', 1))
            st.markdown(f"**Scenario {scenario_number}:** [{scenario_name}]({result['youtrack_url']})")

    urls = [
        result['youtrack_url']
        for result in st.session_state.processing_results
        if result.get('youtrack_url') and result['youtrack_url'] != "Not generated"
    ]
    if urls:
        st.info("💡 Enable popups for localhost:8501 in your browser before clicking.")
        if st.button("🌐 Open All URLs"):
            js_open = "\n".join([f"window.open('{url}', '_blank');" for url in urls])
            # Embed a unique nonce so Streamlit treats this as a new component on every click,
            # forcing the script to re-execute rather than serving a cached render.
            nonce = datetime.now().strftime('%Y%m%d%H%M%S%f')
            st.components.v1.html(
                f"<!-- {nonce} --><script>{js_open}</script>",
                height=0,
            )

# ─── Auto-refresh for MITM monitoring ────────────────────────────────────────
if not st.session_state.analysis_results:
    time.sleep(3)
    st.rerun()

# ─── Footer ───────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("**Bug Builder** - Automated bug report generation from Squash TM executions")

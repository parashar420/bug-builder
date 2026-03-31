import streamlit as st
import json
import os
import re
import time
from datetime import datetime
from bug_builder import app_config as config
from src.bug_builder.crew import BugBuilder

st.set_page_config(
    page_title="Bug Builder - Squash TM Processor",
    page_icon="🐛",
    layout="wide"
)

# Initialize session state
if 'json_data' not in st.session_state:
    st.session_state.json_data = None
if 'input_source' not in st.session_state:
    st.session_state.input_source = None
if 'analysis_results' not in st.session_state:
    st.session_state.analysis_results = None
if 'processing_results' not in st.session_state:
    st.session_state.processing_results = []
if 'last_checked_file' not in st.session_state:
    st.session_state.last_checked_file = None
if 'nl_processing_result' not in st.session_state:
    st.session_state.nl_processing_result = None


def get_board_sprint(board_name=None):
    """Generate sprint string using correct prefix for selected board"""
    current_week = datetime.now().isocalendar()[1]
    if current_week % 2 == 0:
        sprint_number = current_week - 1
    else:
        sprint_number = current_week
    current_year = datetime.now().year

    # Find sprint prefix for selected board
    boards = config['youtrack']['boards']
    selected_name = board_name or config['youtrack']['default_board']

    sprint_prefix = selected_name  # fallback
    for board in boards:
        if board['name'] == selected_name:
            sprint_prefix = board['sprint_prefix']
            break

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
    captured_dir = config['paths']['capture_dir']
    if not os.path.exists(captured_dir):
        return None
    json_files = [f for f in os.listdir(captured_dir) if f.endswith('.json')]
    if not json_files:
        return None
    latest_file = max(json_files, key=lambda f: os.path.getctime(os.path.join(captured_dir, f)))
    return os.path.join(captured_dir, latest_file)


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


def check_for_new_mitm_file():
    """Check if there's a new MITM captured file"""
    latest_file = get_latest_captured_file()
    if latest_file and latest_file != st.session_state.last_checked_file:
        return latest_file
    return None


# ─── Main UI ──────────────────────────────────────────────────────────────────

st.title("🐛 Bug Builder - Squash TM Processor")
st.markdown("Process Squash TM execution data via MITM proxy or describe a bug in your own words")

board_names = [b['name'] for b in config['youtrack']['boards']]
col_board, _, _, _, _ = st.columns(5)
with col_board:
    selected_board = st.selectbox(
        "🎯 Select YouTrack Board",
        options=board_names,
        index=0,
        help="Select the YouTrack board to create tickets on"
    )

st.markdown("""
    <style>
    [data-baseweb="select"] input,
    [data-baseweb="select"] input:hover,
    [data-baseweb="select"] input:focus,
    [data-baseweb="select"] *,
    [data-baseweb="select"] *:hover,
    div[class*="ValueContainer"] *,
    div[class*="ValueContainer"] input {
        cursor: pointer !important;
        caret-color: transparent !important;
    }
    </style>
""", unsafe_allow_html=True)

st.divider()

# Input Sources Section
st.header("📥 Input Sources")

col1, col2 = st.columns(2)

# ─── MITM Monitoring ──────────────────────────────────────────────────────────
with col1:
    st.subheader("🔍 MITM Proxy Monitoring")

    latest_file = check_for_new_mitm_file()

    if latest_file:
        file_name = os.path.basename(latest_file)
        file_time = datetime.fromtimestamp(os.path.getctime(latest_file)).strftime('%H:%M:%S')
        st.success(f"📄 New file detected: **{file_name}**")
        st.info(f"⏰ Created at: {file_time}")

        if st.button("📊 Analyze MITM File", type="primary"):
            try:
                with open(latest_file, 'r') as f:
                    json_data = json.load(f)

                st.session_state.json_data = json_data
                st.session_state.input_source = "mitm"
                st.session_state.last_checked_file = latest_file
                st.session_state.analysis_results = analyze_json_data(json_data)
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error reading file: {str(e)}")
    else:
        if os.path.exists(config['paths']['capture_dir']):
            st.info("👀 Monitoring for new JSON files...")
        else:
            st.warning("📁 captured_squash_data directory not found")

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
                        'bug_description': bug_description.strip(),
                        'board_sprint': get_board_sprint(selected_board),
                        'board': selected_board,
                        'current_year': str(datetime.now().year)
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

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Execution ID", results['execution_id'])
        st.metric("Executed By", results['executed_by'])
    with col2:
        st.metric("Test Name",
                  results['execution_name'][:30] + "..." if len(results['execution_name']) > 30 else results[
                      'execution_name'])
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
                st.session_state.processing_results = []

                progress_bar = st.progress(0)
                status_text = st.empty()

                for i, failed_test in enumerate(results['failed_tests']):
                    status_text.text(f"Processing step {i + 1}/{len(results['failed_tests'])}...")
                    progress_bar.progress((i + 1) / len(results['failed_tests']))

                    bug_description = format_bug_description(failed_test, results, st.session_state.json_data)

                    inputs = {
                        'bug_description': bug_description,
                        'board_sprint': get_board_sprint(selected_board),
                        'board': selected_board,
                        'current_year': str(datetime.now().year)
                    }

                    try:
                        BugBuilder().crew().kickoff(inputs=inputs)

                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                        execution_id = results['execution_id']

                        if os.path.exists('bug_report.md'):
                            new_filename = f'bug_report_{execution_id}_step_{i + 1}_{timestamp}.md'
                            os.rename('bug_report.md', new_filename)

                        youtrack_url = "Not generated"
                        if os.path.exists('youtrack_url.txt'):
                            with open('youtrack_url.txt', 'r') as f:
                                youtrack_url = f.read().strip()
                            new_url_filename = f'youtrack_url_{execution_id}_step_{i + 1}_{timestamp}.txt'
                            os.rename('youtrack_url.txt', new_url_filename)

                        st.session_state.processing_results.append({
                            'step': i + 1,
                            'order': failed_test['order'],
                            'bug_description': bug_description,
                            'youtrack_url': youtrack_url,
                            'status': 'completed'
                        })

                    except Exception as e:
                        st.session_state.processing_results.append({
                            'step': i + 1,
                            'order': failed_test['order'],
                            'bug_description': bug_description,
                            'youtrack_url': "Error occurred",
                            'status': 'error',
                            'error': str(e)
                        })

                status_text.text("✅ All bug reports generated!")
                progress_bar.empty()
                status_text.empty()
                st.rerun()
        else:
            st.info("✅ No failed tests to process!")

    with col2:
        if st.button("🔄 Check Again", use_container_width=True):
            if st.session_state.input_source == "mitm":
                latest_file = get_latest_captured_file()
                if latest_file:
                    try:
                        with open(latest_file, 'r') as f:
                            json_data = json.load(f)
                        st.session_state.json_data = json_data
                        st.session_state.last_checked_file = latest_file
                        st.session_state.analysis_results = analyze_json_data(json_data)
                        st.session_state.processing_results = []
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error reading latest file: {str(e)}")
                else:
                    st.warning("⚠️ No new MITM files found")
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
            failed_test = None
            for test in st.session_state.analysis_results['failed_tests']:
                if test.get('order') == result['order']:
                    failed_test = test
                    break

            if failed_test:
                scenario_name = extract_scenario_name(failed_test.get('action', ''))
                scenario_number = failed_test.get('order', result['step']) + 1
                st.markdown(f"**Scenario {scenario_number}:** [{scenario_name}]({result['youtrack_url']})")
            else:
                st.markdown(f"**Scenario {result['order'] + 1}:** [View Bug Report]({result['youtrack_url']})")

    urls = [
        result['youtrack_url']
        for result in st.session_state.processing_results
        if result.get('youtrack_url') and result['youtrack_url'] != "Not generated"
    ]
    if urls:
        st.info("💡 Enable popups for localhost:8501 in your browser before clicking.")
        if st.button("🌐 Open All URLs"):
            js_open = "\n".join([f"window.open('{url}', '_blank');" for url in urls])
            st.components.v1.html(f"<script>{js_open}</script>", height=0)

# ─── Auto-refresh for MITM monitoring ────────────────────────────────────────
if not st.session_state.analysis_results:
    time.sleep(3)
    st.rerun()

# ─── Footer ───────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("**Bug Builder** - Automated bug report generation from Squash TM executions")

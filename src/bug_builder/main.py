#!/usr/bin/env python
import sys
import warnings
import json
import os
import glob
import re
import time
import hashlib
import webbrowser
from datetime import datetime
from dotenv import load_dotenv
from bug_builder import app_config, athena_token
config = app_config
#from src.bug_builder.crew import BugBuilder
from bug_builder.crew import BugBuilder
from urllib.parse import quote_plus
from bug_builder.utils import (
    clean_html,
    get_board_sprint,
    extract_execution_comment,
    extract_parent_ticket,
    extract_scenario_name,
    get_latest_captured_file,
    build_inputs
)

load_dotenv()
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# This main file is intended to be a way for you to run your
# crew locally, so refrain from adding unnecessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information





# === SQUASH TM PROCESSING FUNCTIONS ===

def cleanup_on_startup():
    """Delete previous JSON files and consolidated YouTrack URL files when program starts"""

    print("🧹 Cleaning up previous files...")

    # 1. Delete all captured JSON files from known capture directories
    capture_dirs = {
        config['paths']['capture_dir'],
        config['paths'].get('testcase_capture_dir', 'captured_testcase_data')
    }
    for capture_dir in capture_dirs:
        json_files = glob.glob(os.path.join(capture_dir, "*.json"))
        for file in json_files:
            try:
                os.remove(file)
                print(f"🗑️  Deleted: {file}")
            except Exception as e:
                print(f"❌ Failed to delete {file}: {e}")

    # 2. Delete all consolidated YouTrack URL files
    url_files = glob.glob("all_youtrack_urls_*.txt")
    for file in url_files:
        try:
            os.remove(file)
            print(f"🗑️  Deleted: {file}")
        except Exception as e:
            print(f"❌ Failed to delete {file}: {e}")

    # 3. Delete any leftover individual files from previous runs
    cleanup_individual_files()

    print("✅ Cleanup completed")


def cleanup_individual_files():
    """Delete individual bug report files and single YouTrack URL files after consolidation"""

    print("🧹 Cleaning up individual files...")

    # Delete individual bug report files
    bug_report_files = glob.glob("bug_report_*_step_*.md")
    for file in bug_report_files:
        try:
            os.remove(file)
            print(f"🗑️  Deleted: {file}")
        except Exception as e:
            print(f"❌ Failed to delete {file}: {e}")

    # Delete individual YouTrack URL files
    individual_url_files = glob.glob("youtrack_url_*_step_*.txt")
    for file in individual_url_files:
        try:
            os.remove(file)
            print(f"🗑️  Deleted: {file}")
        except Exception as e:
            print(f"❌ Failed to delete {file}: {e}")

    # Delete any generic output files that might be left
    if os.path.exists('bug_report.md'):
        try:
            os.remove('bug_report.md')
            print(f"🗑️  Deleted: bug_report.md")
        except Exception as e:
            print(f"❌ Failed to delete bug_report.md: {e}")

    if os.path.exists('youtrack_url.txt'):
        try:
            os.remove('youtrack_url.txt')
            print(f"🗑️  Deleted: youtrack_url.txt")
        except Exception as e:
            print(f"❌ Failed to delete youtrack_url.txt: {e}")

def get_capture_dir(mode='gherkin'):
    if mode == 'testcases':
        return config['paths'].get('testcase_capture_dir', 'captured_testcase_data')
    return config['paths']['capture_dir']


def is_execution_payload(json_data):
    if not isinstance(json_data, dict):
        return False
    if 'executionStatus' not in json_data:
        return False
    step_views = json_data.get('executionStepViews')
    if not isinstance(step_views, list):
        return False
    return any(isinstance(step, dict) and 'executionStatus' in step and 'order' in step for step in step_views)


def is_failed_execution_payload(json_data):
    if not is_execution_payload(json_data):
        return False
    if str(json_data.get('executionStatus', '')).upper() == 'FAILURE':
        return True
    return any(str(step.get('executionStatus', '')).upper() == 'FAILURE' for step in json_data.get('executionStepViews', []))


def _action_hash(action_text):
    normalized = clean_html(action_text or '').lower().strip()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]


def get_latest_captured_file():
    """Get the most recently captured JSON file"""
    captured_dir = get_capture_dir('gherkin')

    if not os.path.exists(captured_dir):
        return None

    # Get all JSON files
    json_files = [f for f in os.listdir(captured_dir) if f.endswith('.json')]

    if not json_files:
        return None

    # Get most recent file
    latest_file = max(json_files, key=lambda f: os.path.getctime(os.path.join(captured_dir, f)))
    return os.path.join(captured_dir, latest_file)


def get_execution_payloads(mode='gherkin'):
    """Return list of deduplicated eligible failed execution payloads."""
    if mode == 'gherkin':
        latest_file = get_latest_captured_file()
        if not latest_file:
            return []
        try:
            with open(latest_file, 'r') as f:
                json_data = json.load(f)
        except Exception:
            return []
        if not is_failed_execution_payload(json_data):
            return []
        execution_id = str(json_data.get('id', 'unknown'))
        last_executed_on = str(json_data.get('lastExecutedOn', 'unknown'))
        return [{
            'file_path': latest_file,
            'file_name': os.path.basename(latest_file),
            'json_data': json_data,
            'execution_id': execution_id,
            'last_executed_on': last_executed_on,
            'ctime': os.path.getctime(latest_file),
        }]

    # In testcase mode, collect execution payloads from both capture folders.
    # Some environments save execution results in captured_squash_data,
    # while testcase definition payloads are saved in captured_testcase_data.
    candidate_dirs = [
        get_capture_dir('gherkin'),
        get_capture_dir('testcases'),
    ]
    existing_dirs = [d for d in candidate_dirs if os.path.exists(d)]
    if not existing_dirs:
        return []

    deduped = {}

    for captured_dir in existing_dirs:
        json_files = [f for f in os.listdir(captured_dir) if f.endswith('.json')]
        json_files = sorted(json_files, key=lambda f: os.path.getctime(os.path.join(captured_dir, f)))

        for file_name in json_files:
            file_path = os.path.join(captured_dir, file_name)
            try:
                with open(file_path, 'r') as f:
                    payload = json.load(f)
            except Exception:
                continue

            if not is_failed_execution_payload(payload):
                continue

            execution_id = str(payload.get('id', 'unknown'))
            last_executed_on = str(payload.get('lastExecutedOn', 'unknown'))
            key = (execution_id, last_executed_on)
            ctime = os.path.getctime(file_path)
            if key not in deduped or ctime > deduped[key]['ctime']:
                deduped[key] = {
                    'file_path': file_path,
                    'file_name': file_name,
                    'json_data': payload,
                    'execution_id': execution_id,
                    'last_executed_on': last_executed_on,
                    'ctime': ctime,
                }

    return sorted(deduped.values(), key=lambda x: x['ctime'])

# Use comment in the Excecution to Add build and device
# this will extract and send to Crew Ai to add in the Bug Description
def extract_execution_comment(json_data):
    """Extract and clean the root-level execution comment (build/device info)"""

    comment_html = json_data.get('comment', '')

    if not comment_html or comment_html.strip() == '':
        return "Build and device information not provided. Please refer to test execution environment."

    # Use the better HTML cleaning
    clean_comment = clean_html(comment_html)

    #debug
    print(f"📝 extract_execution_comment() output:\n{clean_comment}\n")

    return clean_comment if clean_comment.strip() else "Not provided"


def extract_testcase_narrative(testcase_json, test_case_id=None):
    """Fuse all testcase steps into a single consolidated narrative for testcase agent."""
    steps = testcase_json.get('testSteps', [])
    
    if not steps:
        return None
    
    build_device_info = extract_execution_comment(testcase_json)
    testcase_name = testcase_json.get('name', 'Unknown Testcase')
    testcase_id = test_case_id or testcase_json.get('id', 'unknown')
    prerequisite = testcase_json.get('prerequisite', '')
    prerequisite_clean = clean_html(prerequisite) if prerequisite else "Not specified"
    
    # Fuse all steps into narrative
    steps_narrative = []
    expected_results = []
    
    for step in steps:
        step_order = step.get('stepOrder', 'unknown')
        action = clean_html(step.get('action', ''))
        expected = clean_html(step.get('expectedResult', ''))
        
        steps_narrative.append(f"Step {step_order}: {action}")
        if expected:
            expected_results.append(f"Step {step_order} expects: {expected}")
    
    steps_text = "\n".join(steps_narrative)
    expected_text = "\n".join(expected_results)
    
    narrative = f"""
Testcase ID: {testcase_id}
Testcase Name: {testcase_name}

BUILD & DEVICE INFO:
{build_device_info}

PREREQUISITE:
{prerequisite_clean}

ALL ACTIONS (FUSED):
{steps_text}

INDIVIDUAL EXPECTED RESULTS PER ACTION:
{expected_text}

ANALYZE AND SYNTHESIZE: Based on all actions and their individual expected results above, determine what the TESTCASE AS A WHOLE is supposed to achieve. 
Generate ONE consolidated expected result that captures the holistic intent (not just a list).
"""
    
    return narrative.strip()
# gets data to populate UI
def extract_failed_tests(json_data):
    """Extract failed test scenarios from Squash TM JSON"""
    failed_tests = []

    for step in json_data.get('executionStepViews', []):
        if step.get('executionStatus') == 'FAILURE':
            failed_tests.append({
                'step_id': step.get('id'),
                'order': step.get('order'),
                'action': step.get('action', ''),
                'comment': step.get('comment', 'No actual result provided'),
                'executed_on': step.get('lastExecutedOn'),
                'executed_by': step.get('lastExecutedBy')
            })

    #debug
    print(f"🐛 extract_failed_tests() found: {len(failed_tests)} failed test(s)\n")

    return failed_tests

# Extracts data to send to CrewAI

def extract_full_scenario(json_data, failed_step_order):
    """Extract complete test scenario for AI processing"""
    all_steps = json_data.get('executionStepViews', [])

    # Find the failed step index
    failed_index = None
    for i, step in enumerate(all_steps):
        if step.get('order') == failed_step_order:
            failed_index = i
            break

    if failed_index is None:
        return None

    # Get all steps UP TO and INCLUDING the failed one
    scenario_steps = all_steps[:failed_index + 1]

    # Separate prerequisites (SUCCESS) from failed step
    prerequisites = []
    for step in scenario_steps[:-1]:
        clean_action = clean_html(step.get('action', ''))  # UPDATED
        prerequisites.append({
            'order': step.get('order'),
            'action': clean_action,
            'status': step.get('executionStatus')
        })

    # Get the failed step
    failed_step = scenario_steps[-1]
    clean_failed_action = clean_html(failed_step.get('action', ''))  # UPDATED

    #debug
    print(f"🔍 extract_full_scenario() output:")
    print(f"   Prerequisites: {len(prerequisites)} steps")
    print(f"   Failed step: {clean_failed_action[:80]}...")
    print(f"   Has execution_context: {bool(json_data)}")
    print(f"   execution_context has 'comment' key: {'comment' in json_data}\n")

    return {
        'prerequisites': prerequisites,
        'failed_step': {
            'order': failed_step.get('order'),
            'action': clean_failed_action,
            'comment': failed_step.get('comment', 'No actual result provided'),
            'step_id': failed_step.get('id'),
            'executed_on': failed_step.get('lastExecutedOn'),
            'executed_by': failed_step.get('lastExecutedBy')
        },
        'execution_context': json_data
    }


def format_bug_description_for_ai(full_scenario):
    """Format complete test scenario for AI processing"""

    if not full_scenario:
        return None

    ctx = full_scenario['execution_context']
    failed = full_scenario['failed_step']

    # Extract build/device info from root comment
    build_device_info = extract_execution_comment(ctx)

    # Build prerequisite steps section
    prerequisites_section = ""
    if full_scenario['prerequisites']:
        prerequisites_lines = []
        for i, step in enumerate(full_scenario['prerequisites'], 1):
            prerequisites_lines.append(f"{i}. {step['action']}")
        prerequisites_section = f"""
PREREQUISITE STEPS (Passed):
{chr(10).join(prerequisites_lines)}
"""

    failed_step_number = len(full_scenario['prerequisites']) + 1

    description = f"""
Test Execution: {ctx['id']}
Test Suite: {ctx['name']}
Executed By: {ctx.get('lastExecutedBy', 'Unknown')}     
Executed On: {ctx.get('lastExecutedOn', 'Unknown')} 

BUILD & DEVICE INFO:
{build_device_info}
{prerequisites_section}
FAILED STEP:
{failed_step_number}. {failed['action']}

ACTUAL RESULT:
{failed['comment']}

STEP ORDER IN TEST: {failed['order']}
STEP ID: {failed['step_id']}
"""

    #debug
    print(f"📄 format_bug_description_for_ai() FINAL OUTPUT:")
    print("=" * 70)
    print(description)
    print("=" * 70)
    print("\n")
    return description.strip()

def process_squash(mode='gherkin'):
    """Process captured Squash TM file(s) based on mode."""

    payloads = get_execution_payloads(mode)
    if not payloads:
        print(f"❌ No eligible failed execution payloads found for mode={mode}")
        return

    print(f"🔄 Processing {len(payloads)} execution payload(s) in mode={mode}")

    # === RESOLVE PROJECT AND BOARD FROM CONFIG (CLI uses defaults) ===
    projects = config['youtrack']['projects']
    default_project_name = config['youtrack']['default_project']

    # Find default project object
    selected_project = next(
        (p for p in projects if p['name'] == default_project_name),
        projects[0]  # fallback to first project if default not found
    )

    # Use first board of default project
    selected_board = selected_project['boards'][0]['name']

    # Handle sequential sprint format
    selected_sprint = None
    if selected_project['sprint_format'] == 'sequential':
        print(f"⚠️  Project '{selected_project['display_name']}' uses sequential sprints.")
        try:
            selected_sprint = int(input("🔢 Enter current sprint number: ").strip())
        except (ValueError, EOFError):
            print("❌ Invalid sprint number. Using 1 as default.")
            selected_sprint = 1

    print(f"📋 Using Project: {selected_project['display_name']}")
    print(f"📋 Using Board: {selected_board}")
    print(f"📋 Using Sprint: {get_board_sprint(selected_project, selected_board, selected_sprint)}")

    # === FOR AI PROCESSING ===
    all_youtrack_urls = []

    if mode == 'testcase':
        # ===== TESTCASE MODE: ONE BUG PER TESTCASE =====
        global_testcase_counter = 0
        processed_testcase_ids = set()

        for payload in payloads:
            json_data = payload['json_data']
            file_label = payload['file_name']
            testcase_id = json_data.get('id', 'unknown')

            # Skip if already processed
            if testcase_id in processed_testcase_ids:
                print(f"⏭️  Skipping duplicate testcase {testcase_id}")
                continue

            processed_testcase_ids.add(testcase_id)
            global_testcase_counter += 1

            print(f"🔄 Processing testcase {global_testcase_counter}: {testcase_id}")

            # Extract consolidated narrative from testcase
            consolidated_narrative = extract_testcase_narrative(json_data, testcase_id)
            if not consolidated_narrative:
                print(f"⚠️  Could not extract narrative from testcase {testcase_id}")
                continue

            inputs = {
                'bug_description': consolidated_narrative,
                'board_sprint': get_board_sprint(selected_project, selected_board, selected_sprint),
                'board': selected_board,
                'url_template': selected_project['url_template'],
                'current_year': str(datetime.now().year),
                'board_encoded': quote_plus(selected_board),
                'board_sprint_encoded': quote_plus(get_board_sprint(selected_project, selected_board, selected_sprint)),
            }

            # Call crew with testcase mode
            BugBuilder().crew(mode='testcase').kickoff(inputs=inputs)

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            testcase_name = json_data.get('name', 'unknown')

            if os.path.exists('bug_report.md'):
                os.rename('bug_report.md', f'bug_report_{mode}_{testcase_id}_{timestamp}.md')

            if os.path.exists('youtrack_url.txt'):
                with open('youtrack_url.txt', 'r') as f:
                    url = f.read().strip()
                    all_youtrack_urls.append({
                        'testcase_num': global_testcase_counter,
                        'testcase_id': testcase_id,
                        'testcase_name': testcase_name,
                        'url': url,
                        'execution_id': payload['execution_id'],
                        'source_file': file_label,
                    })
                os.rename('youtrack_url.txt', f'youtrack_url_{mode}_{testcase_id}_{timestamp}.txt')

    else:
        # ===== GHERKIN MODE: ONE BUG PER FAILED STEP =====
        processed_failed_keys = set()
        global_step_counter = 0

        for payload in payloads:
            json_data = payload['json_data']
            file_label = payload['file_name']
            failed_tests = extract_failed_tests(json_data)

            if not failed_tests:
                print(f"✅ No failed tests found in {file_label}")
                continue

            print(f"🐛 Found {len(failed_tests)} failed test(s) in {file_label}")

            for failed_test in failed_tests:
                step_id = failed_test.get('step_id')
                if step_id is not None:
                    failed_key = (payload['execution_id'], str(step_id))
                else:
                    failed_key = (
                        payload['execution_id'],
                        str(failed_test.get('order', 'unknown')),
                        _action_hash(failed_test.get('action', ''))
                    )

                if failed_key in processed_failed_keys:
                    continue

                processed_failed_keys.add(failed_key)
                global_step_counter += 1
                print(f"🔄 Processing failed test {global_step_counter}")

                full_scenario = extract_full_scenario(json_data, failed_test['order'])
                if not full_scenario:
                    print(f"⚠️  Could not extract full scenario for step {failed_test['order']}")
                    continue

                bug_description = format_bug_description_for_ai(full_scenario)
                inputs = {
                    'bug_description': bug_description,
                    'board_sprint': get_board_sprint(selected_project, selected_board, selected_sprint),
                    'board': selected_board,
                    'url_template': selected_project['url_template'],
                    'current_year': str(datetime.now().year),
                    'board_encoded': quote_plus(selected_board),
                    'board_sprint_encoded': quote_plus(get_board_sprint(selected_project, selected_board, selected_sprint)),
                }

                # Call crew with gherkin mode (default)
                BugBuilder().crew(mode='gherkin').kickoff(inputs=inputs)

                execution_id = payload['execution_id']
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                if os.path.exists('bug_report.md'):
                    os.rename('bug_report.md', f'bug_report_{mode}_{execution_id}_step_{global_step_counter}_{timestamp}.md')

                if os.path.exists('youtrack_url.txt'):
                    with open('youtrack_url.txt', 'r') as f:
                        url = f.read().strip()
                        all_youtrack_urls.append({
                            'step': global_step_counter,
                            'title': f"Step {failed_test['order']} Failure",
                            'url': url,
                            'scenario_name': extract_scenario_name(failed_test['action']),
                            'execution_id': execution_id,
                            'source_file': file_label,
                        })
                    os.rename('youtrack_url.txt', f'youtrack_url_{mode}_{execution_id}_step_{global_step_counter}_{timestamp}.txt')

    # Create consolidated URLs file
    if payloads:
        primary_execution_id = payloads[0]['execution_id']
    else:
        primary_execution_id = 'none'
    urls_file = f'all_youtrack_urls_{primary_execution_id}_{mode}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'

    with open(urls_file, 'w') as f:
        f.write(f"YouTrack URLs for mode={mode}\n")
        f.write(f"Payloads processed: {len(payloads)}\n")
        f.write(f"Project: {selected_project['display_name']}\n")
        f.write(f"Board: {selected_board}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 70 + "\n\n")

        if mode == 'testcase':
            for url_info in all_youtrack_urls:
                f.write(f"Bug {url_info['testcase_num']}: {url_info['testcase_name']}\n")
                f.write(f"Testcase ID: {url_info['testcase_id']}\n")
                f.write(f"Execution ID: {url_info['execution_id']}\n")
                f.write(f"Source File: {url_info['source_file']}\n")
                f.write(f"URL: {url_info['url']}\n")
                f.write("-" * 50 + "\n\n")
        else:
            for url_info in all_youtrack_urls:
                f.write(f"Bug {url_info['step']}: {url_info['scenario_name']}\n")
                f.write(f"Title: {url_info['title']}\n")
                f.write(f"Execution ID: {url_info['execution_id']}\n")
                f.write(f"Source File: {url_info['source_file']}\n")
                f.write(f"URL: {url_info['url']}\n")
                f.write("-" * 50 + "\n\n")

    print(f"✅ Generated {len(all_youtrack_urls)} bug reports")
    print(f"📄 Consolidated URLs: {urls_file}")

    cleanup_individual_files()

    print(f"🎉 Process completed! Check: {urls_file}")



# === ORIGINAL MAIN FUNCTIONS ===

def _default_cli_inputs():
    """Build default CLI inputs when no runtime payload is provided."""
    projects = app_config['youtrack']['projects']
    default_project_name = app_config['youtrack']['default_project']
    selected_project = next(
        (p for p in projects if p['name'] == default_project_name),
        projects[0]
    )
    selected_board = selected_project['boards'][0]['name']
    selected_sprint = 1 if selected_project['sprint_format'] == 'sequential' else None
    bug_description = "CLI-triggered BugBuilder execution"
    parent_ticket = None
    return build_inputs(bug_description, selected_project, selected_board, selected_sprint, parent_ticket)

def run():
    """
    Run the crew.
    """
    inputs = _default_cli_inputs()

    try:
        BugBuilder().crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = _default_cli_inputs()
    try:
        BugBuilder().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")


def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        BugBuilder().crew().replay(task_id=sys.argv[1])
    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")


def test():
    """
    Test the crew execution and returns the results.
    """
    inputs = _default_cli_inputs()
    try:
        BugBuilder().crew().test(n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")


def run_with_trigger():
    """
    Run the crew with trigger payload.
    """
    import json

    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    inputs = _default_cli_inputs()

    try:
        result = BugBuilder().crew().kickoff(inputs=inputs)
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}")


def cleanup():
    """
    Clean up previous files and start fresh.
    """
    cleanup_on_startup()


# === LAUNCHER FUNCTIONS ===

def start_mitm_proxy():
    """Start MITM proxy in background"""
    import subprocess
    print("🚀 Starting MITM Proxy...")

    # Create captured data directories
    os.makedirs(config["paths"]["capture_dir"], exist_ok=True)
    os.makedirs(config["paths"].get("testcase_capture_dir", "captured_testcase_data"), exist_ok=True)

    try:
        mitm_process = subprocess.Popen([
            "mitmweb",
            "-s", "squash_capture.py",
            "--listen-port", str(config["ports"]["mitm_proxy"]),
            "--web-port", str(config["ports"]["mitm_web"]),
            "--no-web-open-browser"
        ]) # stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        print("✅ MITM Proxy started on port 8080")
        print("🌐 MITM Web interface: http://127.0.0.1:8081")
        return mitm_process
    except Exception as e:
        print(f"❌ Failed to start MITM: {e}")
        return None


def start_streamlit():
    """Start Streamlit app"""
    import subprocess
    print("🚀 Starting Streamlit App...")

    try:
        streamlit_process = subprocess.Popen([
            sys.executable, "-m", "streamlit", "run",
            "streamlit_app.py",
            "--server.port", str(config["ports"]["streamlit"])
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        print("✅ Streamlit started on port 8501")
        print("🌐 Streamlit App: http://localhost:8501")
        return streamlit_process
    except Exception as e:
        print(f"❌ Failed to start Streamlit: {e}")
        return None


def check_dependencies():
    """Check if required packages are installed"""
    try:
        import mitmproxy
        import streamlit
        print("✅ Dependencies verified")
        return True
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Run: pip install mitmproxy streamlit")
        return False


def launch_full_stack():
    """Launch MITM + Streamlit in full-stack mode"""


    print("🐛 Bug Builder - Full Stack Launcher")
    print("=" * 50)

    # Check dependencies
    if not check_dependencies():
        return

    # Cleanup previous files
    cleanup_on_startup()

    # Start MITM proxy
    mitm_process = start_mitm_proxy()
    if not mitm_process:
        print("❌ Cannot start without MITM proxy")
        return

    # Wait for MITM to initialize
    time.sleep(4)

    # Start Streamlit
    streamlit_process = start_streamlit()
    if not streamlit_process:
        print("❌ Failed to start Streamlit")
        if mitm_process:
            mitm_process.terminate()
        return

    # Wait for Streamlit to initialize
    time.sleep(3)

    print("\n🎉 All services started successfully!")
    print("=" * 50)
    print("📋 Setup Instructions:")
    print("1. Configure browser proxy: 127.0.0.1:8080")
    print("2. Install certificate: http://mitm.it")
    print("3. Navigate to Squash TM and execute tests")
    print("4. Process results in: http://localhost:8501")
    print("=" * 50)


    try:
        print("\n🔄 Services running... (Ctrl+C to stop)")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down services...")
        if streamlit_process:
            streamlit_process.terminate()
        if mitm_process:
            mitm_process.terminate()
        print("✅ Services stopped")

def show_help():
    """
    Display help information about available commands.
    """
    print("""
🚀 BugBuilder Crew - Available Commands:

Basic Operations:
  python main.py                    - Run with default bug description
  python main.py run               - Same as above
  python main.py launch            - Launch MITM + Streamlit (Full Stack)
    python main.py squash [mode]     - Process Squash TM JSON files (mode: gherkin|testcases)
  python main.py cleanup           - Clean up previous files

Training & Testing:
  python main.py train <iterations> <filename> - Train the crew
  python main.py test <iterations> <eval_llm>  - Test the crew
  python main.py replay <task_id>              - Replay specific task

Advanced:
  python main.py trigger '<json>'   - Run with trigger payload
  python main.py help              - Show this help message

Squash TM Workflow:
1. Run: python main.py launch
2. Configure browser proxy to 127.0.0.1:8080
3. Install certificate from http://mitm.it
4. Navigate to Squash TM and execute/view tests
5. Process results automatically in Streamlit
    """)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Default behavior - run normally
        run()
    else:
        command = sys.argv[1].lower()

        if command == "run":
            run()
        elif command == "launch":
            launch_full_stack()
        elif command == "squash":
            mode = "gherkin"
            if len(sys.argv) >= 3 and sys.argv[2].lower() in ["gherkin", "testcases"]:
                mode = sys.argv[2].lower()
            process_squash(mode=mode)
        elif command == "cleanup":
            cleanup()
        elif command == "train":
            train()
        elif command == "test":
            test()
        elif command == "replay":
            replay()
        elif command == "trigger":
            run_with_trigger()
        elif command in ["help", "-h", "--help"]:
            show_help()
        else:
            print(f"❌ Unknown command: {command}")
            show_help()
            sys.exit(1)
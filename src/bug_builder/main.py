#!/usr/bin/env python
import sys
import warnings
import json
import os
import glob
import re
import time
import webbrowser
from datetime import datetime
from dotenv import load_dotenv

from bug_builder import app_config as config
#from src.bug_builder.crew import BugBuilder
from bug_builder.crew import BugBuilder

load_dotenv()
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# This main file is intended to be a way for you to run your
# crew locally, so refrain from adding unnecessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information

board = config["youtrack"]["board"]


def clean_html(html_text):
    """Remove HTML tags and clean up whitespace"""
    if not html_text:
        return ""

    # Remove HTML tags
    clean_text = re.sub(r'<[^>]+>', ' ', html_text)
    # Replace multiple whitespace with single space
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    #debug
    print(f"🧹 clean_html() output: {clean_text[:100]}...")

    return clean_text

def get_current_sprint():
    current_week = datetime.now().isocalendar()[1]
    if current_week % 2 == 0:
        sprint_number = current_week - 1
    else:
        sprint_number = current_week
    return f"{sprint_number:02d}"


def get_board_sprint():
    current_year = datetime.now().year
    sprint = get_current_sprint()
    return f"{board} - Sprint {current_year}.{sprint}"


# === SQUASH TM PROCESSING FUNCTIONS ===

def cleanup_on_startup():
    """Delete previous JSON files and consolidated YouTrack URL files when program starts"""

    print("🧹 Cleaning up previous files...")

    # 1. Delete all captured JSON files
    json_files = glob.glob("captured_squash_data/*.json")
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


def get_latest_captured_file():
    """Get the most recently captured JSON file"""
    captured_dir = "captured_squash_data"

    if not os.path.exists(captured_dir):
        return None

    # Get all JSON files
    json_files = [f for f in os.listdir(captured_dir) if f.endswith('.json')]

    if not json_files:
        return None

    # Get most recent file
    latest_file = max(json_files, key=lambda f: os.path.getctime(os.path.join(captured_dir, f)))
    return os.path.join(captured_dir, latest_file)

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

# def extract_full_scenario(json_data, failed_step_order):
#     """Extract complete test scenario for AI processing"""
#     all_steps = json_data.get('executionStepViews', [])
#
#     # Find the failed step index
#     failed_index = None
#     for i, step in enumerate(all_steps):
#         if step.get('order') == failed_step_order:
#             failed_index = i
#             break
#
#     if failed_index is None:
#         return None
#
#     # Get all steps UP TO and INCLUDING the failed one
#     scenario_steps = all_steps[:failed_index + 1]
#
#     # Separate prerequisites (SUCCESS) from failed step
#     prerequisites = []
#     for step in scenario_steps[:-1]:
#         clean_action = re.sub(r'<[^>]+>', '', step.get('action', ''))
#         prerequisites.append({
#             'order': step.get('order'),
#             'action': clean_action.strip(),
#             'status': step.get('executionStatus')
#         })
#
#     # Get the failed step
#     failed_step = scenario_steps[-1]
#     clean_failed_action = re.sub(r'<[^>]+>', '', failed_step.get('action', ''))
#
#     return {
#         'prerequisites': prerequisites,
#         'failed_step': {
#             'order': failed_step.get('order'),
#             'action': clean_failed_action.strip(),
#             'comment': failed_step.get('comment', 'No actual result provided'),
#             'step_id': failed_step.get('id'),
#             'executed_on': failed_step.get('lastExecutedOn'),
#             'executed_by': failed_step.get('lastExecutedBy')
#         },
#         'execution_context': {
#             'id': json_data.get('id'),
#             'name': json_data.get('name'),
#             'executed_by': json_data.get('lastExecutedBy'),
#             'executed_on': json_data.get('lastExecutedOn')
#         }
#     }


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

    #return description.strip()


# def format_bug_description_for_ai(full_scenario):
#     """Format complete test scenario for AI processing"""
#
#     if not full_scenario:
#         return None
#
#     # Build prerequisite steps section
#     prerequisites_section = ""
#     if full_scenario['prerequisites']:
#         prerequisites_lines = []
#         for i, step in enumerate(full_scenario['prerequisites'], 1):
#             prerequisites_lines.append(f"{i}. {step['action']}")
#         prerequisites_section = f"""
# PREREQUISITE STEPS (Passed):
# {chr(10).join(prerequisites_lines)}
# """
#
#     # Build the complete description
#     ctx = full_scenario['execution_context']
#     failed = full_scenario['failed_step']
#
#     failed_step_number = len(full_scenario['prerequisites']) + 1
#
#     description = f"""
# Test Execution: {ctx['id']}
# Test Suite: {ctx['name']}
# Executed By: {ctx['executed_by']}
# Executed On: {ctx['executed_on']}
# {prerequisites_section}
# FAILED STEP:
# {failed_step_number}. {failed['action']}
#
# ACTUAL RESULT:
# {failed['comment']}
#
# STEP ORDER IN TEST: {failed['order']}
# STEP ID: {failed['step_id']}
# """
#
#     return description.strip()

# def format_bug_description(failed_test, execution_context):
#     """Convert failed test to bug description format"""
#
#     action_text = failed_test['action']
#     # Clean HTML and extract scenario info
#     clean_action = re.sub(r'<[^>]+>', '', action_text)
#
#     description = f"""
# Test execution {execution_context['id']} failed.
#
# Test: {execution_context['name']}
# Executed by: {execution_context['lastExecutedBy']}
# Executed on: {execution_context['lastExecutedOn']}
#
# FAILED SCENARIO:
# {clean_action}
#
# ACTUAL RESULT:
# {failed_test['comment']}
#
# STEP ORDER: {failed_test['order']}
# STEP ID: {failed_test['step_id']}
# """
#
#     return description.strip()


def extract_scenario_name(action_text):
    """Extract clean scenario name for UI hyperlinks"""
    # Remove HTML tags and clean whitespace
    clean_text = clean_html(action_text)  # UPDATED

    # Try to extract scenario name
    scenario_match = re.search(r'Scenario[^:]*:?\s*([^\n\r]+)', clean_text)
    if scenario_match:
        return scenario_match.group(1).strip()

    # Fallback: get first meaningful line
    lines = [line.strip() for line in clean_text.split('\n') if line.strip()]
    if lines:
        return lines[0][:50] + "..." if len(lines[0]) > 50 else lines[0]


    return "Unknown Scenario"

def process_squash():
    """Process the latest captured Squash TM file"""

    # Get latest file
    latest_file = get_latest_captured_file()
    if not latest_file:
        print("❌ No captured JSON files found")
        return

    print(f"🔄 Processing: {latest_file}")

    # Load JSON data
    with open(latest_file, 'r') as f:
        json_data = json.load(f)

    # === FOR UI DISPLAY ===
    failed_tests = extract_failed_tests(json_data)

    if not failed_tests:
        print(f"✅ No failed tests found in {latest_file}")
        return

    print(f"🐛 Found {len(failed_tests)} failed test(s)")

    # === FOR AI PROCESSING ===
    all_youtrack_urls = []

    for i, failed_test in enumerate(failed_tests):
        print(f"🔄 Processing failed test {i + 1}/{len(failed_tests)}")

        # Extract FULL scenario for AI (not just failed step)
        full_scenario = extract_full_scenario(json_data, failed_test['order'])

        if not full_scenario:
            print(f"⚠️  Could not extract full scenario for step {failed_test['order']}")
            continue

        # Format with complete context for AI
        bug_description = format_bug_description_for_ai(full_scenario)

        # Prepare CrewAI inputs
        inputs = {
            'bug_description': bug_description,  # ← Now has FULL context
            'board_sprint': get_board_sprint(),
            'board': board,
            'current_year': str(datetime.now().year)
        }

        print(f"🚀 SENDING TO CREWAI:")
        print(f"   Bug description length: {len(bug_description)} characters")
        print(f"   Board: {inputs['board']}")
        print(f"   Sprint: {inputs['board_sprint']}")
        print(f"\n📨 Full bug_description being sent to AI:")
        print("=" * 70)
        print(inputs['bug_description'])
        print("=" * 70)
        print("\n")

        # Run CrewAI workflow
        result = BugBuilder().crew().kickoff(inputs=inputs)

        # Rename output files
        execution_id = json_data['id']
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        os.rename('bug_report.md',
                  f'bug_report_{execution_id}_step_{i + 1}_{timestamp}.md')

        # Read YouTrack URL and use scenario name from UI function
        if os.path.exists('youtrack_url.txt'):
            with open('youtrack_url.txt', 'r') as f:
                url = f.read().strip()
                all_youtrack_urls.append({
                    'step': i + 1,
                    'title': f"Step {failed_test['order']} Failure",
                    'url': url,
                    'scenario_name': extract_scenario_name(failed_test['action'])  # ← UI function
                })
            os.rename('youtrack_url.txt',
                      f'youtrack_url_{execution_id}_step_{i + 1}_{timestamp}.txt')

    # Create consolidated URLs file (same as before)
    execution_id = json_data['id']
    urls_file = f'all_youtrack_urls_{execution_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'

    with open(urls_file, 'w') as f:
        f.write(f"YouTrack URLs for Execution {execution_id}\n")
        f.write(f"Execution: {json_data['name']}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 70 + "\n\n")

        for url_info in all_youtrack_urls:
            f.write(f"Bug {url_info['step']}: {url_info['scenario_name']}\n")
            f.write(f"Title: {url_info['title']}\n")
            f.write(f"URL: {url_info['url']}\n")
            f.write("-" * 50 + "\n\n")

    print(f"✅ Generated {len(failed_tests)} bug reports")
    print(f"📄 Consolidated URLs: {urls_file}")

    cleanup_individual_files()

    print(f"🎉 Process completed! Check: {urls_file}")
# def process_squash():
#     """Process the latest captured Squash TM file"""
#
#     # Get latest file
#     latest_file = get_latest_captured_file()
#     if not latest_file:
#         print("❌ No captured JSON files found")
#         return
#
#     print(f"🔄 Processing: {latest_file}")
#
#     # Load JSON data
#     with open(latest_file, 'r') as f:
#         json_data = json.load(f)
#
#     # Extract failed tests
#     failed_tests = extract_failed_tests(json_data)
#
#     if not failed_tests:
#         print(f"✅ No failed tests found in {latest_file}")
#         return
#
#     print(f"🐛 Found {len(failed_tests)} failed test(s)")
#
#     # Process each failed test
#     all_youtrack_urls = []
#
#     for i, failed_test in enumerate(failed_tests):
#         print(f"🔄 Processing failed test {i + 1}/{len(failed_tests)}")
#
#         # Format bug description
#         bug_description = format_bug_description(failed_test, json_data)
#
#         # Prepare CrewAI inputs
#         inputs = {
#             'bug_description': bug_description,
#             'board_sprint': get_board_sprint(),
#             'board': board,
#             'current_year': str(datetime.now().year)
#         }
#
#         # Run CrewAI workflow
#         result = BugBuilder().crew().kickoff(inputs=inputs)
#
#         # Rename output files to avoid overwriting
#         execution_id = json_data['id']
#         timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
#
#         os.rename('bug_report.md', f'bug_report_{execution_id}_step_{i + 1}_{timestamp}.md')
#
#         # Read YouTrack URL
#         if os.path.exists('youtrack_url.txt'):
#             with open('youtrack_url.txt', 'r') as f:
#                 url = f.read().strip()
#                 all_youtrack_urls.append({
#                     'step': i + 1,
#                     'title': f"Step {failed_test['order']} Failure",
#                     'url': url,
#                     'scenario_name': extract_scenario_name(failed_test['action'])
#                 })
#             os.rename('youtrack_url.txt', f'youtrack_url_{execution_id}_step_{i + 1}_{timestamp}.txt')
#
#     # Create consolidated URLs file
#     execution_id = json_data['id']
#     urls_file = f'all_youtrack_urls_{execution_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
#
#     with open(urls_file, 'w') as f:
#         f.write(f"YouTrack URLs for Execution {execution_id}\n")
#         f.write(f"Execution: {json_data['name']}\n")
#         f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
#         f.write("=" * 70 + "\n\n")
#
#         for url_info in all_youtrack_urls:
#             f.write(f"Bug {url_info['step']}: {url_info['scenario_name']}\n")
#             f.write(f"Title: {url_info['title']}\n")
#             f.write(f"URL: {url_info['url']}\n")
#             f.write("-" * 50 + "\n\n")
#
#     print(f"✅ Generated {len(failed_tests)} bug reports")
#     print(f"📄 Consolidated URLs: {urls_file}")
#
#     # Clean up individual files after consolidation
#     cleanup_individual_files()
#
#     print(f"🎉 Process completed! Check: {urls_file}")


# === ORIGINAL MAIN FUNCTIONS ===

def run():
    """
    Run the crew.
    """
    inputs = {
        'bug_description': """I am using Medscape-Android-PoC-12.17.0-12884725 on Galaxy A32 OS 13, i am already logged in, i tap on the login button from push login email, i am redirected to Medscape app, login keychain page is shown, i choose yes, the login keychain page is showed again infinite times, i chose no, i am redirected to login page""",
        'board_sprint': get_board_sprint(),  # Dynamic sprint calculation
        'board': board,
        'current_year': str(datetime.now().year)
    }

    try:
        BugBuilder().crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = {
        'bug_description': 'Your bug description here',
        'board_sprint': get_board_sprint(),
        'board': board,
        'current_year': str(datetime.now().year)
    }
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
    inputs = {
        'bug_description': 'Test bug description',
        'board_sprint': get_board_sprint(),
        'board': board,
        'current_year': str(datetime.now().year)
    }
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

    inputs = {
        "crewai_trigger_payload": trigger_payload,
        'bug_description': '',
        'board_sprint': get_board_sprint(),
        'board': board,
        'current_year': str(datetime.now().year)
    }

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

    # Create captured data directory
    os.makedirs(config["paths"]["capture_dir"], exist_ok=True)

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
  python main.py squash            - Process latest Squash TM JSON file
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
            process_squash()
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
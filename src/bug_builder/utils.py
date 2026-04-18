"""
utils.py — Shared utility functions for Bug Builder.
Used by both main.py (CLI) and streamlit_app.py (UI).
"""

import os
import re
from datetime import datetime
from urllib.parse import quote_plus
from bug_builder import app_config

config = app_config


# ─── HTML Cleaning ────────────────────────────────────────────────────────────

def clean_html(html_text):
    """
    Remove HTML tags and clean up whitespace.
    Replaces tags with SPACE (not empty string) to prevent word concatenation.
    e.g. word1<br>word2 → 'word1 word2' not 'word1word2'
    """
    if not html_text:
        return ""
    clean_text = re.sub(r'<[^>]+>', ' ', html_text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text


# ─── Sprint Calculation ───────────────────────────────────────────────────────

def get_board_sprint(project, board_name, sequential_sprint=None):
    """
    Generate sprint string for selected project and board.
    Handles two sprint formats:
    - 'sequential': MEDAIS style — "AI Sprint 30"
    - 'year.week':  WBMDMOB style — "Professional Core App - Sprint 2026.13"
    """
    sprint_format = project['sprint_format']

    if sprint_format == 'sequential':
        sprint_prefix = next(
            (b['sprint_prefix'] for b in project['boards'] if b['name'] == board_name),
            board_name
        )
        return f"{sprint_prefix} Sprint {sequential_sprint}"
    else:
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


# ─── JSON Data Extraction ─────────────────────────────────────────────────────

def extract_execution_comment(json_data):
    """
    Extract and clean the root-level execution comment field.
    This is where testers write build and device information.
    e.g. "Build: Medscape-iOS-12.35.0 Device: iPhone 16 OS 18.3.1"
    """
    comment_html = json_data.get('comment', '')
    if not comment_html or comment_html.strip() == '':
        return "Build and device information not provided."
    clean_comment = clean_html(comment_html)
    return clean_comment if clean_comment.strip() else "Not provided"


def extract_parent_ticket(json_data):
    if not json_data:
        return None

    comment_html = json_data.get('comment', '')
    if not comment_html:
        return None

    # Replace &nbsp; and other HTML entities before cleaning
    comment_html = comment_html.replace('&nbsp;', ' ').replace('&amp;', '&')

    clean_comment = clean_html(comment_html)
    print(f"🔍 Cleaned comment for ticket extraction: {clean_comment}")

    # Updated pattern — handles "Subtask of: TICKET" and "Story: TICKET"
    pattern = r'(?:story|subtask\s+of|subtask|task|parent)\s*:?\s*([A-Z]+-\d+)'
    match = re.search(pattern, clean_comment, re.IGNORECASE)

    if match:
        ticket_id = match.group(1).upper()
        print(f"🎫 Found parent ticket: {ticket_id}")
        return ticket_id

    return None


def extract_scenario_name(action_text):
    """
    Extract ONLY the scenario title from a Gherkin action field.
    Stops at first Gherkin keyword (Given/When/Then/And/But).
    Removes markdown special characters that would break link syntax.
    Returns clean title for UI hyperlink display.
    """
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
    """
    Get the most recently captured JSON file from captured_squash_data/.
    Returns full file path or None if no files found.
    """
    captured_dir = config['paths']['capture_dir']
    if not os.path.exists(captured_dir):
        return None
    json_files = [f for f in os.listdir(captured_dir) if f.endswith('.json')]
    if not json_files:
        return None
    latest_file = max(json_files, key=lambda f: os.path.getctime(os.path.join(captured_dir, f)))
    return os.path.join(captured_dir, latest_file)


# ─── CrewAI Inputs Builder ────────────────────────────────────────────────────

def build_inputs(bug_description, selected_project, selected_board, selected_sprint, parent_ticket=None):
    """
    Build the complete inputs dict for CrewAI kickoff.
    Single source of truth — used by both main.py and streamlit_app.py.

    Args:
        bug_description:  Formatted bug description string for AI
        selected_project: Project dict from config.yaml
        selected_board:   Board name string
        selected_sprint:  Sprint number (int) for sequential sprints, None for year.week
        parent_ticket:    Ticket ID string e.g. 'WBMDMOB-59743' or None

    Returns:
        Complete inputs dict ready for BugBuilder().crew().kickoff(inputs=inputs)
    """
    board_sprint = get_board_sprint(selected_project, selected_board, selected_sprint)

    return {
        'bug_description': bug_description,
        'board_sprint': board_sprint,
        'board': selected_board,
        'url_template': selected_project['url_template'],
        'current_year': str(datetime.now().year),
        'board_encoded': quote_plus(selected_board),
        'board_sprint_encoded': quote_plus(board_sprint),
        'parent_ticket': parent_ticket if parent_ticket else "",
    }

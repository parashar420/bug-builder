import streamlit as st

SESSION_DEFAULTS = {
    "json_data": None,
    "input_source": None,
    "analysis_results": None,
    "processing_results": [],
    "last_checked_file": None,
    "nl_processing_result": None,
    "last_error": None,
    "mode": "gherkin",
    "selected_project_display": None,
    "selected_board": None,
    "selected_sprint": "",
}

BODY_RESET_DEFAULTS = {
    "json_data": None,
    "input_source": None,
    "analysis_results": None,
    "processing_results": [],
    "last_checked_file": None,
    "nl_processing_result": None,
    "last_error": None,
    "nl_bug_input_area": "",
}


def init_session_state():
    for key, default_value in SESSION_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default_value


def reset_body_state():
    for key, default_value in BODY_RESET_DEFAULTS.items():
        st.session_state[key] = default_value

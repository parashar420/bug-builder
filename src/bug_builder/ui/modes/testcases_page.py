import os

import streamlit as st


def render_testcases_mitm_panel(get_execution_file_bundle_for_testcases, get_capture_dir, analyze_testcase_files):
    st.subheader("🔍 MITM Proxy Monitoring")

    file_bundle = get_execution_file_bundle_for_testcases()
    files = file_bundle.get("files", [])

    if files:
        st.success("📚 Testcase execution data found.")

        if st.button("📊 Analyze Testcase Files", type="primary"):
            st.session_state.json_data = None
            st.session_state.input_source = "mitm"
            st.session_state.analysis_results = analyze_testcase_files(file_bundle)
            st.rerun()
    else:
        if os.path.exists(get_capture_dir("gherkin")) or os.path.exists(get_capture_dir("testcases")):
            st.info("👀 Waiting for Failed Testcases...")
        else:
            st.warning(
                f"📁 Directories not found: {get_capture_dir('gherkin')} and {get_capture_dir('testcases')}"
            )

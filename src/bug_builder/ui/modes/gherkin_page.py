import json
import os
from datetime import datetime

import streamlit as st


def render_gherkin_mitm_panel(
    check_for_new_mitm_file,
    get_capture_dir,
    is_execution_payload,
    is_failed_execution_payload,
    analyze_json_data,
):
    st.subheader("🔍 MITM Proxy Monitoring")

    latest_file = check_for_new_mitm_file()

    if latest_file:
        file_name = os.path.basename(latest_file)
        file_time = datetime.fromtimestamp(os.path.getctime(latest_file)).strftime("%H:%M:%S")
        st.success(f"📄 New file detected: **{file_name}**")
        st.info(f"⏰ Created at: {file_time}")

        if st.button("📊 Analyze MITM File", type="primary"):
            try:
                with open(latest_file, "r") as f:
                    json_data = json.load(f)

                if not is_execution_payload(json_data):
                    st.error("❌ Latest file is not an execution payload. Skipping.")
                elif not is_failed_execution_payload(json_data):
                    st.warning("⚠️ Execution has no failed steps. Nothing to process.")
                else:
                    st.session_state.json_data = json_data
                    st.session_state.input_source = "mitm"
                    st.session_state.last_checked_file = latest_file
                    results = analyze_json_data(json_data)
                    if results:
                        results["mode"] = "gherkin"
                        results["files_processed"] = 1
                        results["skipped_files"] = []
                    st.session_state.analysis_results = results
                    st.rerun()
            except Exception as e:
                st.error(f"❌ Error reading file: {str(e)}")
    else:
        if os.path.exists(get_capture_dir("gherkin")):
            st.info("👀 Waiting for Failed Gherkin Testcases...")
        else:
            st.warning(f"📁 Directory not found: {get_capture_dir('gherkin')}")

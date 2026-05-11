import streamlit as st


def _render_header_styles():
    st.markdown(
        """
        <style>
        [data-testid=\"stSegmentedControl\"] {
            display: flex;
            justify-content: flex-end;
        }

        [data-testid=\"stSegmentedControl\"] [role=\"radiogroup\"] {
            background: #f1f1f1;
            border: 1px solid #e3e3e3;
            border-radius: 999px;
            padding: 4px;
            gap: 4px;
        }

        [data-testid=\"stSegmentedControl\"] [role=\"radio\"] {
            border-radius: 999px;
            min-width: 120px;
            justify-content: center;
            font-weight: 600;
        }

        [data-testid=\"stSegmentedControl\"] [role=\"radio\"][aria-checked=\"true\"] {
            background: #0e0e0e !important;
            color: #ffffff !important;
        }

        [data-testid=\"stSegmentedControl\"] [role=\"radio\"][aria-checked=\"false\"] {
            color: #7a7a7a !important;
        }

        [data-baseweb=\"select\"] input,
        [data-baseweb=\"select\"] input:hover,
        [data-baseweb=\"select\"] input:focus,
        [data-baseweb=\"select\"] *,
        [data-baseweb=\"select\"] *:hover {
            cursor: pointer !important;
            caret-color: transparent !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(config):
    st.title("🦂 Bug Builder - Squash TM Processor")
    st.markdown("Process Squash TM execution data via MITM proxy or describe a bug in your own words")

    previous_mode = st.session_state.mode

    mode_col_left, mode_col_right = st.columns([4, 1])
    with mode_col_right:
        selected_mode_label = st.segmented_control(
            "Mode",
            options=["Gherkin", "Testcases"],
            default="Testcases" if st.session_state.mode == "testcases" else "Gherkin",
            key="mode_toggle_segmented",
            selection_mode="single",
        )

    selected_mode = (selected_mode_label or "Gherkin").lower()

    projects = config["youtrack"]["projects"]
    project_names = [p["display_name"] for p in projects]

    if not st.session_state.selected_project_display or st.session_state.selected_project_display not in project_names:
        st.session_state.selected_project_display = project_names[0]

    col_project, col_board, _, _, _ = st.columns(5)

    with col_project:
        st.selectbox(
            "📁 Select Project",
            options=project_names,
            key="selected_project_display",
        )

    selected_project = next(
        p for p in projects if p["display_name"] == st.session_state.selected_project_display
    )

    board_names = [b["name"] for b in selected_project["boards"]]
    if st.session_state.selected_board not in board_names:
        st.session_state.selected_board = board_names[0]

    with col_board:
        st.selectbox(
            "🎯 Select Board",
            options=board_names,
            key="selected_board",
        )

    if selected_project["sprint_format"] == "sequential":
        col_sprint, _, _, _, _ = st.columns(5)
        with col_sprint:
            st.text_input(
                "🔢 Sprint Number",
                placeholder="e.g. 20",
                key="selected_sprint",
            )
    else:
        st.session_state.selected_sprint = ""

    _render_header_styles()

    return {
        "selected_mode": selected_mode,
        "mode_changed": selected_mode != previous_mode,
        "selected_project": selected_project,
        "selected_board": st.session_state.selected_board,
        "selected_sprint": st.session_state.selected_sprint,
    }

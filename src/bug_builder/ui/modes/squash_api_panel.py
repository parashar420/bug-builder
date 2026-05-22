import streamlit as st


def render_squash_api_panel(mode: str):
    st.subheader("☁️ Squash API")
    iteration_text = st.text_input(
        "Iteration ID",
        placeholder="e.g. 17706",
        key=f"squash_iteration_id_{mode}",
    )
    extract_clicked = st.button(
        "📥 Extract from Squash API",
        type="primary",
        key=f"extract_squash_api_{mode}",
    )
    return iteration_text, extract_clicked

"""Streamlit chat UI for the Excel agent.  Run:  streamlit run q1_excel_agent/app.py"""
import json

import streamlit as st

from agent import DF, chat

st.set_page_config(page_title="Inventory Data Agent", page_icon="📦")
st.title("📦 Inventory Data Agent")
st.caption("Ask questions about the inventory spreadsheet. The agent writes and runs pandas code, "
           "searches the web for definitions, and answers in plain English.")

with st.expander("Preview the data"):
    st.dataframe(DF, width="stretch")


def show_steps(steps):
    """Show each tool call (code run / search made) in a collapsible box, for transparency."""
    for step in steps:
        with st.expander(f"🔧 {step['tool']}"):
            if step["tool"] == "run_python":
                st.code(step["input"]["code"], language="python")
            else:
                st.write(json.dumps(step["input"]))
            st.text(step["output"][:2000])


if "history" not in st.session_state:
    st.session_state.history = []   # what the model sees
    st.session_state.display = []   # what the UI shows (includes tool steps)

for item in st.session_state.display:
    with st.chat_message(item["role"]):
        show_steps(item.get("steps", []))
        st.markdown(item["content"])

if question := st.chat_input("e.g. Which product has the highest total cost?"):
    st.session_state.history.append({"role": "user", "content": question})
    st.session_state.display.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            answer, steps = chat(st.session_state.history)
        show_steps(steps)
        st.markdown(answer)
    st.session_state.history.append({"role": "assistant", "content": answer})
    st.session_state.display.append({"role": "assistant", "content": answer, "steps": steps})

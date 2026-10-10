"""Streamlit chat UI for the support assistant.  Run:  streamlit run q2_support_bot/app.py"""
import streamlit as st

from bot import SupportBot

st.set_page_config(page_title="HDFC Forms Support Assistant", page_icon="💬")
st.title("💬 HDFC Life Forms - Support Assistant")
st.caption("Answers from the onboarding forms, remembers the conversation, and cites the section it used.")

if "bot" not in st.session_state:
    st.session_state.bot = SupportBot()

if st.sidebar.button("New conversation"):
    st.session_state.bot.reset()

for m in st.session_state.bot.transcript:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

if question := st.chat_input("Ask about any of the forms..."):
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Looking through the forms..."):
            r = st.session_state.bot.ask(question)
        st.markdown(r["answer"])
        st.caption(f"Search query: {r['query']}")

with st.sidebar:
    st.subheader("Already told (session memory)")
    for t in st.session_state.bot.told:
        st.markdown(f"- {t['note']}  \n  _{t['section']}_")

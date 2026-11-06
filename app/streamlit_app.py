"""Streamlit UI: type a question, see the SQL, the rows and the assumptions.

This is a thin client. It only calls the FastAPI service over HTTP (API_URL), so it never imports
t2sql or psycopg. Run it with:

    streamlit run app/streamlit_app.py
"""

import os

import pandas as pd
import requests
import streamlit as st

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000").rstrip("/")
EXAMPLES = [
    "How many customers do we have?",
    "What is our MRR this month?",
    "Which enterprise customers churned in the last 30 days?",
    "How many users were active in the last 7 days?",
    "How many open support tickets are there?",
    "What was total revenue this month?",
]


def ask_api(question: str) -> dict:
    """POST the question to the API. Raises requests exceptions when the API is unreachable."""
    response = requests.post(f"{API_URL}/ask", json={"question": question}, timeout=120)
    if response.status_code == 200:
        return response.json()
    if response.status_code == 422:
        raise ValueError("Please type a question of 3 to 500 characters.")
    detail = response.json().get("detail", "The API could not answer right now.")
    raise ValueError(str(detail))


def show_answer(result: dict) -> None:
    if result["ok"]:
        if result["rows"]:
            st.dataframe(pd.DataFrame(result["rows"], columns=result["columns"]))
        else:
            st.info("The query ran and returned no rows.")
    else:
        st.error(result["error"] or "No safe answer was produced.")
    if result["sql"]:
        st.code(result["sql"], language="sql")
    if result["truncated"]:
        st.warning("Only the first rows are shown. The full answer is longer.")
    if result["assumptions"]:
        st.subheader("Assumptions")
        st.markdown("\n".join(f"- {item}" for item in result["assumptions"]))
    tables = ", ".join(result["tables_used"]) or "none"
    st.caption(
        f"Tables used: {tables} | attempts: {result['attempts']} | seconds: {result['seconds']}"
    )


def set_question(text: str) -> None:
    st.session_state["question"] = text


st.set_page_config(page_title="SQL Copilot")
st.title("SQL Copilot")
st.caption("Ask a question in plain English. The answer comes from a read-only SQL query.")

with st.sidebar:
    st.header("Example questions")
    for example in EXAMPLES:
        st.button(example, on_click=set_question, args=(example,), use_container_width=True)

question = st.text_input("Your question", key="question", placeholder="e.g. What is our MRR?")
if st.button("Ask", type="primary"):
    if not question.strip():
        st.warning("Type a question first.")
    else:
        with st.spinner("Writing and checking the query..."):
            try:
                result = ask_api(question.strip())
            except requests.ConnectionError:
                st.error(
                    f"Cannot reach the API at {API_URL}. Start it with: "
                    "uvicorn api.main:app --port 8000"
                )
            except requests.Timeout:
                st.error("The API took too long to answer. Try again in a moment.")
            except (requests.RequestException, ValueError) as exc:
                st.error(str(exc))
            else:
                show_answer(result)

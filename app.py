"""
CustomsAI – Interfaccia web Streamlit

Avvio: streamlit run app.py
CLI invariato: python3 main.py "domanda"
"""

import streamlit as st

from main import query


# ── Helper: rendering di un singolo risultato ─────────────────────────────────

def _render_entry(question: str, result: dict, show_question: bool = True) -> None:
    if show_question:
        st.markdown(f"**{question}**")

    # Routing log (collassato)
    if result["log"]:
        with st.expander("Routing", expanded=False):
            for msg in result["log"]:
                st.text(msg)

    # Contenuto principale
    if result["mode"] == "empty":
        st.warning("Nessun risultato trovato.")

    elif result["mode"] == "direct":
        st.subheader("Testo normativo")
        for chunk in result["chunks"]:
            st.text(chunk.get("chunk_text", ""))
            st.divider()

    else:  # mode == "llm"
        st.subheader("Risposta")
        st.markdown(result["answer"])

    # Fonti normative (aperto)
    if result["sources"]:
        with st.expander("Fonti normative", expanded=True):
            for src in result["sources"]:
                if src.get("label"):
                    st.markdown(f"**{src['label']}**")
                celex = src["celex"]
                url   = src["url"]
                st.markdown(f"CELEX: [{celex}]({url})")


# ── Layout ────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="CustomsAI", layout="centered")
st.title("CustomsAI")
st.caption("Motore normativo AI-first per la dogana europea")

# ── Storico sessione ───────────────────────────────────────────────────────────

if "history" not in st.session_state:
    st.session_state.history = []

# ── Form di input ──────────────────────────────────────────────────────────────

with st.form("query_form"):
    question = st.text_input(
        "Domanda",
        placeholder='es. "cosa è la voce 8544" oppure "obblighi per esportare 2B002"',
    )
    submitted = st.form_submit_button("Invia")

# ── Elaborazione query ─────────────────────────────────────────────────────────

if submitted:
    if not question.strip():
        st.warning("Inserire una domanda.")
    else:
        with st.spinner("Elaborazione..."):
            try:
                result = query(question.strip())
            except Exception as e:
                st.error(f"Errore: {e}")
                result = None

        if result is not None:
            st.session_state.history.append(
                {"question": question.strip(), "result": result}
            )

# ── Mostra il risultato più recente ───────────────────────────────────────────

if st.session_state.history:
    latest = st.session_state.history[-1]
    _render_entry(latest["question"], latest["result"])

# ── Storico sessione (domande precedenti, collassate) ─────────────────────────

if len(st.session_state.history) > 1:
    st.divider()
    st.subheader("Storico sessione")
    for entry in reversed(st.session_state.history[:-1]):
        with st.expander(entry["question"], expanded=False):
            _render_entry(entry["question"], entry["result"], show_question=False)

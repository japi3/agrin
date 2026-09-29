"""
Saathi on Streamlit — a second front door to the same system.

The React app in `apps/web` is the real interface: it installs on a phone,
works offline, and was designed for someone who may not read. This is not a
replacement for it. It exists so the platform can be opened in a browser by
anyone with a link, without a container, a key of their own, or a laptop
with Docker on it — which is what a reviewer, an extension officer or a
state department actually has when they first want to look.

The important thing here is what it does *not* contain. There is no second
copy of the agronomy, the tool layer, the prompt discipline or the grounding
check. It calls `orchestrator.stream_turn`, the same function the FastAPI
app calls, and renders the events that come back. If retrieval starts
abstaining, or the water balance changes, this interface changes with it and
nobody has to remember that there were two.

What a Streamlit Cloud deployment gives up, stated plainly rather than
discovered:

  * **Satellite crop health.** It needs rasterio and GDAL, which are heavy
    and unnecessary for everything else. The tool reports that it is
    unavailable, honestly, rather than guessing.
  * **The local soil map.** The 158 MB map of India is not in the
    repository, so soil comes from ISRIC's live service instead: correct,
    but seconds rather than milliseconds.
  * **Persistence.** Streamlit Cloud's filesystem is ephemeral, so a
    farmer's field and season memory last as long as the session.

Everything else — the water balance, disease pressure, carbon, prices,
schemes, retrieval with its citations, the grounding check, 24 languages,
voice output — is the same code.

    streamlit run streamlit_app.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
for package in ("apps/api", "packages/agronomy", "packages/geo", "packages/rag"):
    path = str(ROOT / package)
    if path not in sys.path:
        sys.path.insert(0, path)

# Keys come from Streamlit's secrets in a deployment and from .env locally,
# so the same file runs both places without being edited.
for name in ("GEMINI_API_KEY", "GEMINI_API_KEYS", "DATA_GOV_IN_KEY",
             "AGRIN_MODEL", "AGRIN_MODEL_FALLBACKS"):
    try:
        if name in st.secrets and not os.environ.get(name):
            os.environ[name] = str(st.secrets[name])
    except Exception:  # noqa: BLE001
        pass

env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

os.environ.setdefault("AGRIN_DB", "/tmp/agrin-streamlit.db")
os.environ.setdefault("AGRIN_CACHE_DIR", "/tmp/agrin-cache")
os.environ.setdefault("AGRIN_ADVISORY_INDEX", str(ROOT / "data" / "advisory"))

from agrin_api import llm, storage  # noqa: E402
from agrin_api.orchestrator import stream_turn  # noqa: E402

st.set_page_config(page_title="Saathi", page_icon="🌾", layout="centered")

# The FastAPI app creates the schema on startup; nothing here does, so the
# first thing this file touched was a table that did not exist. Cached so it
# runs once per process rather than on every rerun.
@st.cache_resource
def _database():
    storage.init_db()
    return True


_database()

# The app's own palette, so the two interfaces are recognisably one product.
st.markdown("""
<style>
  .stApp { background: #1A1611; color: #F2ECE1; }
  .stChatMessage { background: #241F18; border: 1px solid #3A3226;
                   border-radius: 12px; }
  .saathi-src { background:#12100C; border:1px solid #3A3226;
                border-radius:10px; padding:10px 14px; margin-top:8px;
                font-size:0.86rem; }
  .saathi-src a { color:#7CB86A; }
  .saathi-warn { background:#2A1D12; border:1px solid #C2703D;
                 border-radius:10px; padding:10px 14px; margin-top:8px;
                 font-size:0.88rem; }
</style>
""", unsafe_allow_html=True)


LANGUAGES = {
    "English": "en", "हिन्दी": "hi", "ਪੰਜਾਬੀ": "pa", "मराठी": "mr",
    "বাংলা": "bn", "தமிழ்": "ta", "తెలుగు": "te", "ಕನ್ನಡ": "kn",
    "ગુજરાતી": "gu", "മലയാളം": "ml", "ଓଡ଼ିଆ": "or", "অসমীয়া": "as",
}

# Ludhiana, Punjab — a real wheat-growing district, so the defaults answer.
DEFAULT_LAT, DEFAULT_LON = 30.90, 75.85


@st.cache_resource
def corpus_status() -> tuple[int, bool]:
    from rag.index import load_index
    index = load_index()
    if index is None:
        return 0, False
    return len(index), bool(index.manifest.get("complete"))


with st.sidebar:
    st.markdown("### ✳ Saathi")
    st.caption("Regenerative agricultural intelligence, in the farmer's own voice")

    language_name = st.selectbox("Language", list(LANGUAGES), index=0)
    language = LANGUAGES[language_name]

    st.markdown("**Your field**")
    latitude = st.number_input("Latitude", value=DEFAULT_LAT, format="%.4f")
    longitude = st.number_input("Longitude", value=DEFAULT_LON, format="%.4f")

    passages, complete = corpus_status()
    st.divider()
    if passages:
        st.caption(
            f"Advisory library: {passages:,} passages"
            + ("" if complete else " (indexing in progress)")
        )
    else:
        st.caption("Advisory library not installed — published guidance "
                   "questions will say so rather than answer from memory.")
    st.caption(f"{len(llm.api_keys())} API key(s) configured")
    st.caption("Satellite crop health is unavailable in this deployment.")

    if st.button("Start a new conversation"):
        for key in ("messages", "farmer_id", "conversation_id", "field_id"):
            st.session_state.pop(key, None)
        st.rerun()


if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.farmer_id = storage.create_farmer(language=language)
    st.session_state.conversation_id = storage.create_conversation(
        st.session_state.farmer_id, None, title="Streamlit session")
    st.session_state.field_id = storage.add_field(
        st.session_state.farmer_id, latitude, longitude)

if not st.session_state.messages:
    st.markdown("#### Hello, I'm Saathi")
    st.caption("Ask me anything about your field. Every number I give you "
               "comes from a validated model or a published source — and I "
               "will tell you when I don't know.")
    st.caption("Try: *Should I irrigate my wheat this week?* · "
               "*What seed treatment before sowing wheat?* · "
               "*ਕਣਕ ਦੀ ਬਿਜਾਈ ਤੋਂ ਪਹਿਲਾਂ ਬੀਜ ਦਾ ਇਲਾਜ ਕੀ ਹੈ?*")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        for source in message.get("sources", []):
            st.markdown(
                f"<div class='saathi-src'>📄 <b>{source['title']}</b><br>"
                f"<a href='{source['url']}' target='_blank'>"
                f"{source.get('section', '')}</a></div>",
                unsafe_allow_html=True)
        if message.get("warning"):
            st.markdown(f"<div class='saathi-warn'>⚠ {message['warning']}</div>",
                        unsafe_allow_html=True)


async def run_turn(history, placeholder, tool_slot):
    """Consume the orchestrator's events and paint them as they arrive."""
    text: list[str] = []
    sources: list[dict] = []
    warning = None
    tools_run: list[str] = []

    async for event in stream_turn(
        history, language=language, field_id=st.session_state.field_id,
    ):
        kind, data = event.type, event.data
        if kind == "text":
            text.append(data["delta"])
            placeholder.markdown("".join(text))
        elif kind == "tool_start":
            tools_run.append(data["name"].replace("_", " "))
            tool_slot.caption("⚙ " + " · ".join(tools_run))
        elif kind == "card" and data.get("card") == "sources":
            sources = data.get("sources", [])
        elif kind in ("grounding", "pesticide_notice"):
            warning = data.get("note")
        elif kind == "error":
            placeholder.error(data.get("message", "Something went wrong."))
    return "".join(text), sources, warning


question = st.chat_input("Ask about your field…")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    history = [
        {"role": m["role"], "content": [{"type": "text", "text": m["content"]}]}
        for m in st.session_state.messages
    ]
    # The model is told where the field is rather than made to ask, exactly
    # as the FastAPI app does it.
    history[-1]["content"].append({
        "type": "text",
        "text": f"[field location: latitude {latitude}, longitude {longitude}]",
    })

    with st.chat_message("assistant"):
        tool_slot = st.empty()
        placeholder = st.empty()
        with st.spinner("Thinking…"):
            try:
                answer, sources, warning = asyncio.run(
                    run_turn(history, placeholder, tool_slot))
            except Exception as exc:  # noqa: BLE001
                answer, sources, warning = "", [], None
                placeholder.error(
                    f"The service is busy right now — free-tier capacity is "
                    f"tight. Please try again in a moment. ({type(exc).__name__})")

        for source in sources:
            st.markdown(
                f"<div class='saathi-src'>📄 <b>{source['title']}</b><br>"
                f"<a href='{source['url']}' target='_blank'>"
                f"{source.get('section', '')}</a></div>",
                unsafe_allow_html=True)
        if warning:
            st.markdown(f"<div class='saathi-warn'>⚠ {warning}</div>",
                        unsafe_allow_html=True)

    if answer:
        st.session_state.messages.append({
            "role": "assistant", "content": answer,
            "sources": sources, "warning": warning,
        })

import streamlit as st
from app.config import DEFAULT_SYSTEM_PROMPT
from app.client import get_client
from app.utils import stream_response
from app.docs_extractor import extract
import streamlit.components.v1 as components
import push_to_github

# --------------------------------------------------------------------------- #
# Helper – run the extractor once (same folder as app.py)
# --------------------------------------------------------------------------- #
def refresh_docs() -> str:
    """Run the extractor once (same folder as app.py)."""
    out_path = extract()                 # defaults to current dir + repo_docs.md
    return out_path.read_text(encoding="utf‑8")

# --------------------------------------------------------------------------- #
# Streamlit UI
# --------------------------------------------------------------------------- #
def main():
    st.set_page_config(page_title="Chat with GPT‑OSS", layout="wide")

    # ---- Session state ----------------------------------------------------
    if "history" not in st.session_state:
        st.session_state.history = []          # [(user, bot), ...]
    if "system_prompt" not in st.session_state:
        st.session_state.system_prompt = DEFAULT_SYSTEM_PROMPT
    if "repo_docs" not in st.session_state:
        st.session_state.repo_docs = ""        # will hold the full codebase
    if "has_pushed" not in st.session_state:   # <-- NEW flag
        st.session_state.has_pushed = False

    # ---- Sidebar ----------------------------------------------------------
    with st.sidebar:
        st.header("Settings")

        # 1️⃣  System‑prompt editor (unchanged)
        prompt = st.text_area(
            "System prompt",
            st.session_state.system_prompt,
            height=120,
        )
        if prompt != st.session_state.system_prompt:
            st.session_state.system_prompt = prompt

        if st.button("New Chat"):
            st.session_state.history = []          # wipe the chat history
            st.session_state.repo_docs = ""        # optional: also clear docs
            st.success("Chat history cleared. Start fresh!")

        # 2️⃣  One‑click “Refresh Docs” button
        if st.button("Refresh Docs"):
            st.session_state.repo_docs = refresh_docs()
            st.success("Codebase docs updated!")
        
        if st.button("Push to GitHub"):
            with st.spinner("Pushing to GitHub…"):
                try:
                    push_to_github.main()          # run the external script
                    st.session_state.has_pushed = True
                    st.success("✅  Repository pushed to GitHub.")
                except Exception as exc:
                    st.error(f"❌  Push failed: {exc}")

        # Show push status
        status = "✅  Pushed" if st.session_state.has_pushed else "⚠️  Not pushed"
        st.markdown(f"**Push status:** {status}")

    # ---- Conversation UI --------------------------------------------------
    # Render the *past* messages
    for user_msg, bot_msg in st.session_state.history:
        with st.chat_message("user"):
            st.markdown(user_msg)
        with st.chat_message("assistant"):
            st.markdown(bot_msg)

    # ---- Input -------------------------------------------------------------
    if user_input := st.chat_input("Enter request…"):
        # Show the user’s text immediately
        st.chat_message("user").markdown(user_input)

        client = get_client()
        bot_output = ""

        with st.chat_message("assistant") as assistant_msg:
            # Placeholder inside that element – we’ll update it in place
            placeholder = st.empty()

            for partial in stream_response(
                st.session_state.history,
                user_input,
                client,
                st.session_state.system_prompt,
                st.session_state.repo_docs, 
            ):
                bot_output = partial
                placeholder.markdown(bot_output, unsafe_allow_html=True)

        # Save the finished reply
        st.session_state.history.append((user_input, bot_output))
    
    has_pushed = st.session_state.get("has_pushed", False)
    components.html(
        f"""
        <script>
        // Store the push state in a global JS variable
        window.hasPushed = {str(has_pushed).lower()};

        // Hook into the browser's beforeunload event
        window.onbeforeunload = function(e) {{
          if (!window.hasPushed) {{
            // Returning a string triggers the browser confirmation dialog
            return 'You have not pushed to GitHub yet.\\nDo you really want to leave?';
          }}
        }};
        </script>
        """,
        height=0,
    )

if __name__ == "__main__":
    main()
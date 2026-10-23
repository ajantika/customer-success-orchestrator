"""'How to use this demo' guide, shown on the Overview and in the sidebar."""
import streamlit as st

GUIDE = """
**No login or setup is needed.** The demo uses sample data and prepared responses.

1. **Choose a walkthrough** on the Overview page. It opens the example customer and explains the situation.
2. **Follow the highlighted step.** The progress bar shows where you are, and each step has one main button.
3. **Read the result** shown after each click. Open “Details” for what the assistant found and why.
4. **Stuck or made a wrong choice?** Choose **Restart this walkthrough** (resets only that example customer) or **Back to overview**. “Reset all demo data” in the sidebar resets everything. Refreshing the browser tab also starts a new demo.

**Example customer replies:** “The directory connection is failing.” · “We see an authentication error.” · “It times out when we connect.” · “We already tried those steps.” · “Please stop sending messages.”
"""


def render_guide(expanded: bool = False):
    with st.expander("How to use this demo", expanded=expanded):
        st.markdown(GUIDE)

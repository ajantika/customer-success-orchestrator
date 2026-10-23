"""'How to use this demo' guide, shown on the Overview and in the sidebar."""
import streamlit as st

GUIDE = """
**No login, API key or setup is needed.** Everything is fictional and runs in your browser session.

1. **Pick a walkthrough** on the Overview page. It opens the right customer and explains the situation.
2. **Follow the bar at the top.** It shows your progress, the next action and **who you are playing** at that step.
3. **After every action** read the **What just happened** box: what the system found, what it did, why, and what to do next. Tool calls and evidence are in the expandable sections.
4. **Roles.** *Customer reply:* you are the customer. *Support task:* you are the support specialist. *Recommendation review:* you are the Account Team. The assistant plays itself.
5. **Stuck or made a wrong choice?** Use **Restart this walkthrough** (resets only that customer) or **Back to overview**. “Reset all demo data” in the sidebar resets everything. Refreshing the browser tab also starts a brand-new demo.

**Example customer replies:** “The directory connection is failing.” · “We see an authentication error.” · “It times out when we connect.” · “We already tried those steps.” · “Setup is now complete.” · “Please stop sending messages.”

**What “Demo mode” means:** the assistant follows prepared scenarios and rules. No AI model is called. Tools, rules and data changes are real inside this session.
"""


def render_guide(expanded: bool = False):
    with st.expander("How to use this demo", expanded=expanded):
        st.markdown(GUIDE)

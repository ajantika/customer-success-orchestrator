"""'How to use this demo' guide, shown on the Overview and in the sidebar."""
import streamlit as st

GUIDE = """
**No login or setup is needed.** The demo uses sample data and prepared responses. No live AI model is called.

1. **Select a customer** on the Overview page. Every page then shows that same customer.
2. **Choose what to explore:** setup support, or a customer brief with learning recommendations.
3. **Read what happened** after each click. Open “Details” or “Why this decision?” for the reasoning.
4. **Made a wrong choice?** Use **Reset this customer's demo activity** on a customer page, or **Reset all demo data** in the sidebar. Refreshing the browser tab also starts a new demo.
"""


def render_guide(expanded: bool = False):
    with st.expander("How to use this demo", expanded=expanded):
        st.markdown(GUIDE)


import streamlit.components.v1 as components

_select_output_type = components.declare_component(
    "output_selector",
    path=str(__file__).replace("__init__.py", "frontend/build")
)

def select_output_type():
    return _select_output_type()

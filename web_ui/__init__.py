
import os
from pathlib import Path
import streamlit.components.v1 as components

_component_func = components.declare_component(
    "react_ui_bridge",
    path=str(Path(__file__).parent / "frontend" / "build")
)

def select_output_type():
    return _component_func(default="Video + Blog")

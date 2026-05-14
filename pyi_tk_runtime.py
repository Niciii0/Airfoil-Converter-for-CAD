import os
import sys
from pathlib import Path

base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
tcl_root = base / "tcl"
tcl_lib = tcl_root / "tcl8.6"
tk_lib = tcl_root / "tk8.6"

if tcl_lib.exists():
    os.environ["TCL_LIBRARY"] = str(tcl_lib)
if tk_lib.exists():
    os.environ["TK_LIBRARY"] = str(tk_lib)

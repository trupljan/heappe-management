import os
import sys

# Local py4heappe package marker
# If heappe_v6 is not local, extend __path__ to allow fallback to pip-installed package
local_v6 = os.path.join(os.path.dirname(__file__), "heappe_v6")
if not os.path.exists(local_v6):
    current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for p in sys.path:
        if p and p != current_dir:
            candidate = os.path.join(p, "py4heappe")
            if os.path.isdir(candidate) and os.path.abspath(candidate) != os.path.abspath(os.path.dirname(__file__)):
                if candidate not in __path__:
                    __path__.append(candidate)

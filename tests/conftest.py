"""Let the pure-logic tests import recorder.py off Windows.

`recorder.py` imports pyaudiowpatch at module level, which only exists on
Windows. The functions under test here — title parsing, slug rules, protokoll
replacement — touch no audio at all, so a stub is enough to reach them.

This means the suite runs on any machine, which matters: these are the checks
you want available while fixing something on a laptop that is not the target
platform.
"""

import sys
from unittest.mock import MagicMock

if "pyaudiowpatch" not in sys.modules:
    try:
        import pyaudiowpatch  # noqa: F401
    except ImportError:
        # MagicMock answers paInt16 and anything else read at import time.
        sys.modules["pyaudiowpatch"] = MagicMock()

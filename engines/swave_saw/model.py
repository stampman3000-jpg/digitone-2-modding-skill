"""SWAVE-SAW reference. Shared oscillator code lives in engines/swave_common.

Run from anywhere:

    python3 -c "import sys; sys.path[:0]=['engines/swave_common','engines/swave_saw']; import model"
"""

from __future__ import annotations

import os
import sys

_COMMON = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'swave_common'))
if _COMMON not in sys.path:
    sys.path.insert(0, _COMMON)

from osc import NPHASE, Voice, render_saw  # noqa: E402
from tables import load_waves  # noqa: E402

MACHINE = 'saw'
N_PHASE = NPHASE[MACHINE]


def render(voice, waves=None):
    return render_saw(voice, waves if waves is not None else load_waves())

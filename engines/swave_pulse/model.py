"""SWAVE-PULSE reference. Shared oscillator code lives in engines/swave_common."""

from __future__ import annotations

import os
import sys

_COMMON = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'swave_common'))
if _COMMON not in sys.path:
    sys.path.insert(0, _COMMON)

from osc import NPHASE, Voice, render_pulse  # noqa: E402
from tables import load_waves  # noqa: E402

MACHINE = 'pulse'
N_PHASE = NPHASE[MACHINE]


def render(voice, waves=None):
    return render_pulse(voice, waves if waves is not None else load_waves())

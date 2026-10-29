"""SHARC program for SWAVE-ENS. See engines/swave_common/kernel.py."""

from __future__ import annotations

import os
import sys

_COMMON = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'swave_common'))
if _COMMON not in sys.path:
    sys.path.insert(0, _COMMON)

from kernel import assemble, build_ens, executed_cost, run_voice  # noqa: E402
from tables import load_waves  # noqa: E402


def build(waves=None):
    waves = waves if waves is not None else load_waves()
    kern = build_ens(waves)
    code, texts = assemble(kern, 'swave_ens_entry')
    return kern, code, texts, executed_cost(code), waves


if __name__ == '__main__':
    _kern, code, _texts, info, waves = build()
    print(f'SWAVE-ENS  {info["executed"]} instructions / sounding voice / block')
    print(f'static {info["static"]}  code {len(code)} bytes  table {waves.source}')

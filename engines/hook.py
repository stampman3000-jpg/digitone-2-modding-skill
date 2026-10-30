"""Machine-id hook for the new engines.

Stock Digitone machines stay on ids 0–4 (FM TONE, WAVETONE, FM DRUM, SWARMER,
MIDI). FM+STATIC is already shipped as type 5 and is not ours. FM+DYNAMIC is
6 and FM+PARALLELL is 7. The SHARC routine below only
rewrites the engine word for those two ids, and only to the skip-stock
sentinel (the value 4). It does not write the voice's machine id and it does
not touch the stock dispatch table.

Address math uses shifts. fxdsl has no integer multiply; 564 = 2^9+2^5+2^4+2^2
and the byte strides are powers of two. Checked against fm_common for voices
0..15.
"""
from __future__ import annotations

import fm_common as C
import fxdsl


def build_decide():
    """I4 = machine id word, I5 = engine-word address, I3 = flag word.

    flag 0 = pass the voice to the stock dispatch (replay the displaced jump).
    flag 6 or 7 = we own it; engine word becomes 4. Type 5 is not ours.
    """
    k = fxdsl.Kernel('fm_decide', inputs={'mach': 'I4', 'ew': 'I5', 'flag': 'I3'})
    m = k.var('i', k.ld(k['mach'], 0, 'i'))
    k.st(k['flag'], 0, k.i(0), t='i')
    with k.if_(m == C.MACHINE_FM_DYNAMIC):
        k.st(k['flag'], 0, k.i(C.MACHINE_FM_DYNAMIC), t='i')
        k.st(k['ew'], 0, k.i(C.ENGINE_WORD_SKIP_STOCK), t='i')
    with k.if_(m == C.MACHINE_FM_PARALLEL):
        k.st(k['flag'], 0, k.i(C.MACHINE_FM_PARALLEL), t='i')
        k.st(k['ew'], 0, k.i(C.ENGINE_WORD_SKIP_STOCK), t='i')
    return k


def build_addrs():
    """I4 = voice index word. I5 = 3-word output: engine word, state, buffer."""
    k = fxdsl.Kernel('fm_addrs', inputs={'voice': 'I4', 'out': 'I5'})
    v = k.var('i', k.ld(k['voice'], 0, 'i'))
    # 564 * v = (v << 9) + (v << 5) + (v << 4) + (v << 2)
    scaled = k.lsh(v, 9) + k.lsh(v, 5) + k.lsh(v, 4) + k.lsh(v, 2)
    k.st(k['out'], 0, scaled + (C.ENGINE_WORD_BASE + C.ENGINE_WORD_OFFSET), t='i')
    k.st(k['out'], 1, k.lsh(v, 9) + C.L2_STATE, t='i')          # * 512 bytes
    k.st(k['out'], 2, k.lsh(v, 7) + C.VOICE_BUF_BASE, t='i')    # * 128 bytes
    return k

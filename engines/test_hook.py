"""Machine-id hook: stock ids, shipped FM+STATIC (5), and super-wave pass through. 6 and 7 do not.

    python3 engines/test_hook.py
"""
from __future__ import annotations

import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', 'skills', 'digitone-2-modding-skill', 'scripts')))

import fm_common as C

FAILS = []


def check(cond, msg):
    if cond:
        print(f'  ok  {msg}')
    else:
        FAILS.append(msg)
        print(f'  FAIL  {msg}')


def policy():
    names = {
        0: 'FM TONE', 1: 'WAVETONE', 2: 'FM DRUM', 3: 'SWARMER', 4: 'MIDI',
        5: 'FM+STATIC (shipped)', 8: 'super-wave', 9: 'super-wave', 127: 'unused',
    }
    for mid, name in names.items():
        which, word = C.decide(mid, 99)
        check(which == 0 and word == 99, f'machine {mid} ({name}) is left alone')
    check(C.decide(4, 4) == (0, 4), 'MIDI keeps engine word 4 without us writing it')
    check(C.MACHINE_FM_STATIC == 5 and C.MACHINE_FM_DYNAMIC == 6
          and C.MACHINE_FM_PARALLEL == 7 and C.MACHINE_SUPERWAVE == 8,
          'type 5 static, 6 dynamic, 7 parallel, super-wave from 8')
    check(C.decide(6, 99) == (6, 4), 'FM+DYNAMIC is rendered, then stock loops are skipped')
    check(C.decide(7, 3) == (7, 4), 'FM+PARALLELL is rendered, then stock loops are skipped')
    for v in range(16):
        check(C.engine_word_addr(v) == 0x2554B8 + 564 * v + 436, f'engine-word address voice {v}')
        check(C.state_addr(v) == C.L2_STATE + v * C.STATE_BYTES, f'state address voice {v}')
        check(C.voice_buf_addr(v) == C.VOICE_BUF_BASE + v * 128, f'buffer address voice {v}')
    try:
        C.engine_word_addr(16)
        check(False, 'voice 16 rejected')
    except ValueError:
        check(True, 'voice 16 rejected')


def sim_hook():
    try:
        import sharc_run
        import sim
        import visa
        from hook import build_addrs, build_decide
    except Exception as e:
        print('SKIP sim: the SHARC assembler is not available (' + str(e).splitlines()[0] + ').')
        print('This comparison does not need a stock DSP boot snapshot.')
        return

    def run(kernel, ptrs, blob, base):
        code, labels = sharc_run.assemble(kernel)
        img = visa.Image.__new__(visa.Image)
        img.raw = code
        img.regions = [(sharc_run.L2_CODE, code)]
        s = sim.Sim(img)
        s.strict_hw = True
        for i in range(0, len(blob), 4):
            s.mem.w(base + i, struct.unpack_from('<I', blob, i)[0])
        for ireg, addr in ptrs.items():
            s.I[ireg] = addr
        halt = sharc_run.L2_CODE_SW + len(code) // 2 + 4
        s.stop_at.add(halt)
        s.pcstk.append(halt)
        s.pc = labels[kernel.name]
        assert s.run(max_insns=20000) == 'stop'
        return s

    base = 0x20098000
    decide = build_decide()
    for mid in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9):
        blob = struct.pack('<III', mid, 99, 7)
        s = run(decide, {4: base, 5: base + 4, 3: base + 8}, blob, base)
        which, word = C.decide(mid, 99)
        check(s.mem.r(base + 8) == which and s.mem.r(base + 4) == word and s.mem.r(base) == mid,
              f'sim decide machine {mid}')
    addrs = build_addrs()
    for v in (0, 1, 7, 15):
        blob = struct.pack('<IIII', v, 0, 0, 0)
        s = run(addrs, {4: base, 5: base + 4}, blob, base)
        got = [s.mem.r(base + 4 + 4 * i) for i in range(3)]
        exp = [C.engine_word_addr(v), C.state_addr(v), C.voice_buf_addr(v)]
        check(got == exp, f'sim addresses voice {v}')


if __name__ == '__main__':
    print('policy')
    policy()
    print('sim')
    sim_hook()
    print('FAIL' if FAILS else 'OK', len(FAILS))
    sys.exit(1 if FAILS else 0)

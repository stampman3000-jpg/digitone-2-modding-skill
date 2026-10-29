"""Run one engine kernel on the SHARC simulator without a stock firmware image.

The simulator fetches the bytes we just assembled. Nothing is read from a
Digitone boot snapshot. If dnfw (the assembler support library) is missing,
importing this module fails; the engine tests skip that part with a message.
"""
from __future__ import annotations

import struct

import fm_common as C
import fxdsl
import sasm
import sim
import visa
from sasm import NOP48

L2_CODE = 0x20090000
L2_CODE_SW = visa.Image.load_to_sw(L2_CODE)
BUF_ADDR = 0x2009E000          # test-only buffer, clear of state and tables
HALT_PAD = 16


def call_lab(label):
    def fix(at, labels):
        entry = labels[label]
        return (sasm.W(0x06BE, (entry >> 16) & 0xFFFF, entry & 0xFFFF),
                f'CALL {entry:#x}')
    return fix


def _kernels(kernels):
    if isinstance(kernels, (list, tuple)):
        return list(kernels)
    return [kernels]


def assemble(kernels):
    """Machine code for `render` (calls every kernel in order) plus the kernels."""
    kernels = _kernels(kernels)
    a = sasm.Asm(L2_CODE_SW)
    a.label('render')
    for kernel in kernels:
        a((NOP48, 'NOP'))
        a(fix=call_lab(kernel.name))
        a((NOP48, 'NOP'))
    a((sasm.W(0x0ABE), 'RTS'))
    for _ in range(12):
        a((NOP48, 'NOP'))
    for kernel in kernels:
        kernel.emit(a)
        for _ in range(12):                     # prefetch after that kernel's RTS
            a((NOP48, 'NOP'))
    code, _texts = a.assemble()
    if len(code) > 0x8000:
        raise RuntimeError(f'engine code is {len(code)} bytes; L2 code window is 32 KiB')
    return code, a.labels


def _poke(mem, addr, blob):
    for i in range(0, len(blob), 4):
        mem.w(addr + i, struct.unpack_from('<I', blob, i)[0])


def _words_blob(words):
    return struct.pack('<' + 'I' * len(words), *words)


def _read(mem, addr, n):
    return [mem.r(addr + 4 * i) for i in range(n)]


def _audio(mem, addr=BUF_ADDR):
    return [C.bits_f32(mem.r(addr + 4 * i)) for i in range(C.BLOCK)]


class Runner:
    def __init__(self, kernels, tables, words):
        self.kernels = _kernels(kernels)
        self.tables = tables
        self.code, self.labels = assemble(self.kernels)
        self.entry = self.labels['render']
        self.blob = C.pack_tables(tables)
        self.words0 = list(words)

    def _image(self):
        img = visa.Image.__new__(visa.Image)
        img.raw = self.code
        img.regions = [(L2_CODE, self.code)]
        return img

    def run_dsl(self, n_blocks):
        mem = fxdsl.DictMem()
        _poke(mem, C.L2_TABLES, self.blob)
        st = C.state_addr(0)
        _poke(mem, st, _words_blob(self.words0))
        audio = []
        for _ in range(n_blocks):
            for kernel in self.kernels:
                kernel.run(mem, {'state': st, 'buf': BUF_ADDR})
            audio.extend(_audio(mem))
        state = _read(mem, st, C.STATE_WORDS)
        return audio, state

    def run_sim(self, n_blocks, entry=None):
        s = sim.Sim(self._image())
        s.strict_hw = True
        _poke(s.mem, C.L2_TABLES, self.blob)
        st = C.state_addr(0)
        _poke(s.mem, st, _words_blob(self.words0))
        entry = self.entry if entry is None else entry
        halt = L2_CODE_SW + len(self.code) // 2 + 4
        s.stop_at.add(halt)
        audio = []
        counts = []
        for _ in range(n_blocks):
            s.I[4] = st
            s.I[5] = BUF_ADDR
            s.M[5] = 0
            s.M[6] = 1
            s.pcstk.append(halt)
            s.pc = entry
            before = s.icount
            reason = s.run(max_insns=200_000)
            if reason != 'stop':
                raise RuntimeError(f'sim stopped with {reason} at pc {s.pc:#x}')
            counts.append(s.icount - before)
            audio.extend(_audio(s.mem))
        state = _read(s.mem, st, C.STATE_WORDS)
        return audio, state, counts

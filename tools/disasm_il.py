#!/usr/bin/env python3
"""Minimal CIL disassembler for a .NET method body.

Resolves call/callvirt/l dfld/stfld tokens to method/field names so we can
understand a method's control flow without a full decompiler.

Usage:
    python tools/disasm_il.py <assembly.dll> --type TypeName --method MethodName
"""
import struct
import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_signatures import Assembly

# ECMA-335 opcode table: opcode -> (mnemonic, operand kind, operand size)
OP = {
    0x00: ("nop", "none", 0), 0x01: ("break", "none", 0), 0x02: ("ldarg.0", "none", 0),
    0x03: ("ldarg.1", "none", 0), 0x04: ("ldarg.2", "none", 0), 0x05: ("ldarg.3", "none", 0),
    0x06: ("ldloc.0", "none", 0), 0x07: ("ldloc.1", "none", 0), 0x08: ("ldloc.2", "none", 0),
    0x09: ("ldloc.3", "none", 0), 0x0A: ("stloc.0", "none", 0), 0x0B: ("stloc.1", "none", 0),
    0x0C: ("stloc.2", "none", 0), 0x0D: ("stloc.3", "none", 0), 0x0E: ("ldarg.s", "si1", 1),
    0x0F: ("ldarga.s", "si1", 1), 0x10: ("starg.s", "si1", 1), 0x11: ("ldloc.s", "si1", 1),
    0x12: ("ldloca.s", "si1", 1), 0x13: ("stloc.s", "si1", 1), 0x14: ("ldnull", "none", 0),
    0x15: ("ldc.i4.m1", "none", 0), 0x16: ("ldc.i4.0", "none", 0), 0x17: ("ldc.i4.1", "none", 0),
    0x18: ("ldc.i4.2", "none", 0), 0x19: ("ldc.i4.3", "none", 0), 0x1A: ("ldc.i4.4", "none", 0),
    0x1B: ("ldc.i4.5", "none", 0), 0x1C: ("ldc.i4.6", "none", 0), 0x1D: ("ldc.i4.7", "none", 0),
    0x1E: ("ldc.i4.8", "none", 0), 0x1F: ("ldc.i4.s", "si1", 1), 0x20: ("ldc.i4", "i4", 4),
    0x21: ("ldc.i8", "i8", 8), 0x22: ("ldc.r4", "r4", 4), 0x23: ("ldc.r8", "r8", 8),
    0x25: ("dup", "none", 0), 0x26: ("pop", "none", 0), 0x27: ("jmp", "method", 4),
    0x28: ("call", "method", 4), 0x29: ("calli", "sig", 4), 0x2A: ("ret", "none", 0),
    0x2B: ("br.s", "sbr", 1), 0x2C: ("brfalse.s", "sbr", 1), 0x2D: ("brtrue.s", "sbr", 1),
    0x2E: ("beq.s", "sbr", 1), 0x2F: ("bge.s", "sbr", 1), 0x30: ("bgt.s", "sbr", 1),
    0x31: ("ble.s", "sbr", 1), 0x32: ("blt.s", "sbr", 1), 0x33: ("bne.un.s", "sbr", 1),
    0x34: ("bge.un.s", "sbr", 1), 0x35: ("bgt.un.s", "sbr", 1), 0x36: ("ble.un.s", "sbr", 1),
    0x37: ("blt.un.s", "sbr", 1), 0x38: ("br", "br", 4), 0x39: ("brfalse", "br", 4),
    0x3A: ("brtrue", "br", 4), 0x3B: ("beq", "br", 4), 0x3C: ("bge", "br", 4),
    0x3D: ("bgt", "br", 4), 0x3E: ("ble", "br", 4), 0x3F: ("blt", "br", 4),
    0x40: ("bne.un", "br", 4), 0x41: ("bge.un", "br", 4), 0x42: ("bgt.un", "br", 4),
    0x43: ("ble.un", "br", 4), 0x44: ("blt.un", "br", 4), 0x45: ("switch", "switch", 0),
    0x46: ("ldind.i1", "none", 0), 0x47: ("ldind.u1", "none", 0), 0x48: ("ldind.i2", "none", 0),
    0x49: ("ldind.u2", "none", 0), 0x4A: ("ldind.i4", "none", 0), 0x4B: ("ldind.u4", "none", 0),
    0x4C: ("ldind.i8", "none", 0), 0x4D: ("ldind.i", "none", 0), 0x4E: ("ldind.r4", "none", 0),
    0x4F: ("ldind.r8", "none", 0), 0x50: ("ldind.ref", "none", 0), 0x51: ("stind.ref", "none", 0),
    0x52: ("stind.i1", "none", 0), 0x53: ("stind.i2", "none", 0), 0x54: ("stind.i4", "none", 0),
    0x55: ("stind.i8", "none", 0), 0x56: ("stind.r4", "none", 0), 0x57: ("stind.r8", "none", 0),
    0x58: ("add", "none", 0), 0x59: ("sub", "none", 0), 0x5A: ("mul", "none", 0),
    0x5B: ("div", "none", 0), 0x5C: ("div.un", "none", 0), 0x5D: ("rem", "none", 0),
    0x5E: ("rem.un", "none", 0), 0x5F: ("and", "none", 0), 0x60: ("or", "none", 0),
    0x61: ("xor", "none", 0), 0x62: ("shl", "none", 0), 0x63: ("shr", "none", 0),
    0x64: ("shr.un", "none", 0), 0x65: ("neg", "none", 0), 0x66: ("not", "none", 0),
    0x67: ("conv.i1", "none", 0), 0x68: ("conv.i2", "none", 0), 0x69: ("conv.i4", "none", 0),
    0x6A: ("conv.i8", "none", 0), 0x6B: ("conv.r4", "none", 0), 0x6C: ("conv.r8", "none", 0),
    0x6D: ("conv.u4", "none", 0), 0x6E: ("conv.u8", "none", 0), 0x6F: ("callvirt", "method", 4),
    0x70: ("cpobj", "type", 4), 0x71: ("ldobj", "type", 4), 0x72: ("ldstr", "str", 4),
    0x73: ("newobj", "method", 4), 0x74: ("castclass", "type", 4), 0x75: ("isinst", "type", 4),
    0x76: ("conv.r.un", "none", 0), 0x79: ("unbox", "type", 4), 0x7A: ("throw", "none", 0),
    0x7B: ("ldfld", "field", 4), 0x7C: ("ldflda", "field", 4), 0x7D: ("stfld", "field", 4),
    0x7E: ("ldsfld", "field", 4), 0x7F: ("stsfld", "field", 4), 0x80: ("stobj", "type", 4),
    0x81: ("conv.ovf.i1.un", "none", 0), 0x82: ("conv.ovf.i2.un", "none", 0),
    0x83: ("conv.ovf.i4.un", "none", 0), 0x84: ("conv.ovf.i8.un", "none", 0),
    0x85: ("conv.ovf.u1.un", "none", 0), 0x86: ("conv.ovf.u2.un", "none", 0),
    0x87: ("conv.ovf.u4.un", "none", 0), 0x88: ("conv.ovf.u8.un", "none", 0),
    0x8A: ("conv.ovf.u1", "none", 0), 0x8B: ("conv.ovf.u2", "none", 0),
    0x8C: ("conv.ovf.u4", "none", 0), 0x8D: ("conv.ovf.u8", "none", 0),
    0x8F: ("conv.ovf.i4", "none", 0), 0x90: ("conv.ovf.i8", "none", 0),
    0x91: ("box", "type", 4), 0x92: ("newarr", "type", 4), 0x93: ("ldlen", "none", 0),
    0x94: ("ldelema", "type", 4), 0x95: ("ldelem.i1", "none", 0), 0x96: ("ldelem.u1", "none", 0),
    0x97: ("ldelem.i2", "none", 0), 0x98: ("ldelem.u2", "none", 0), 0x99: ("ldelem.i4", "none", 0),
    0x9A: ("ldelem.u4", "none", 0), 0x9B: ("ldelem.i8", "none", 0), 0x9C: ("ldelem.i", "none", 0),
    0x9D: ("ldelem.r4", "none", 0), 0x9E: ("ldelem.r8", "none", 0), 0x9F: ("ldelem.ref", "none", 0),
    0xA0: ("stelem.i", "none", 0), 0xA1: ("stelem.i1", "none", 0), 0xA2: ("stelem.i2", "none", 0),
    0xA3: ("stelem.i4", "none", 0), 0xA4: ("stelem.i8", "none", 0), 0xA5: ("stelem.r4", "none", 0),
    0xA6: ("stelem.r8", "none", 0), 0xA7: ("stelem.ref", "none", 0),
    0xB3: ("conv.ovf.i1", "none", 0), 0xB4: ("conv.ovf.u1", "none", 0),
    0xB5: ("conv.ovf.i2", "none", 0), 0xB6: ("conv.ovf.u2", "none", 0),
    0xC2: ("refanyval", "type", 4), 0xC6: ("mkrefany", "type", 4),
    0xD0: ("ldtoken", "tok", 4), 0xD1: ("conv.u2", "none", 0), 0xD2: ("conv.u1", "none", 0),
    0xD3: ("conv.i", "none", 0), 0xD4: ("conv.ovf.i", "none", 0), 0xD5: ("conv.ovf.u", "none", 0),
    0xD6: ("add.ovf", "none", 0), 0xD7: ("add.ovf.un", "none", 0), 0xD8: ("mul.ovf", "none", 0),
    0xD9: ("mul.ovf.un", "none", 0), 0xDA: ("sub.ovf", "none", 0), 0xDB: ("sub.ovf.un", "none", 0),
    0xDC: ("endfinally", "none", 0), 0xDD: ("leave", "br", 4), 0xDE: ("leave.s", "sbr", 1),
    0xDF: ("stind.i", "none", 0), 0xE0: ("conv.u", "none", 0),
    0xFE: ("FE", "fe", 0),
}
FE_OP = {
    0x00: ("arglist", "none", 0), 0x01: ("ceq", "none", 0), 0x02: ("cgt", "none", 0),
    0x03: ("cgt.un", "none", 0), 0x04: ("clt", "none", 0), 0x05: ("clt.un", "none", 0),
    0x06: ("ldftn", "method", 4), 0x07: ("ldvirtftn", "method", 4), 0x09: ("ldarg", "i2", 2),
    0x0A: ("ldarga", "i2", 2), 0x0B: ("starg", "i2", 2), 0x0C: ("ldloc", "i2", 2),
    0x0D: ("ldloca", "i2", 2), 0x0E: ("stloc", "i2", 2), 0x0F: ("localloc", "none", 0),
    0x11: ("endfilter", "none", 0), 0x12: ("unaligned.", "i1", 1), 0x13: ("volatile.", "none", 0),
    0x14: ("tail.", "none", 0), 0x15: ("initobj", "type", 4), 0x16: ("constrained.", "type", 4),
    0x17: ("cpblk", "none", 0), 0x18: ("initblk", "none", 0), 0x1A: ("rethrow", "none", 0),
    0x1C: ("sizeof", "type", 4), 0x1D: ("refanytype", "none", 0), 0x1E: ("readonly.", "none", 0),
}


class Disassembler:
    def __init__(self, asm):
        self.asm = asm
        self._build_memberref()

    def _build_memberref(self):
        d = self.asm.data
        # sizes for tables up to MemberRef (0x0A)
        si = 4 if self.asm.STR4 else 2
        bi = 4 if self.asm.BLB4 else 2
        self.asm.sizes[0x08] = 2 + 2 + si          # Param
        self.asm.sizes[0x09] = 2 + 2               # InterfaceImpl
        self.asm.sizes[0x0A] = 4 + si + bi         # MemberRef (Class coded=4)
        o = self.asm.t_off + 24 + 4 * len([t for t in range(64) if struct.unpack_from("<Q", d, self.asm.t_off + 8)[0] & (1 << t)])
        # recompute offsets (present tables only)
        valid = struct.unpack_from("<Q", d, self.asm.t_off + 8)[0]
        present = [i for i in range(64) if valid & (1 << i)]
        off = {}
        for t in present:
            off[t] = o
            o += self.asm.sizes.get(t, 0) * self.asm.rc.get(t, 0)
        self.off = off
        # MemberRef rows: (class_coded, name_idx)
        self.memberrefs = []
        if 0x0A in self.asm.rc:
            for i in range(self.asm.rc[0x0A]):
                r = off[0x0A] + i * self.asm.sizes[0x0A]
                cls = struct.unpack_from("<I", d, r)[0]
                nm = self.asm.s_at(struct.unpack_from("<I", d, r + 4)[0])
                self.memberrefs.append((cls, nm))

    def _type_name(self, coded):
        tag = coded & 7
        row = coded >> 3
        if tag == 0:
            return self.asm.td_names[row - 1] if row <= len(self.asm.td_names) else "TypeDef#%d" % row
        if tag == 1:
            return self.asm.tr_names[row - 1] if row <= len(self.asm.tr_names) else "TypeRef#%d" % row
        if tag == 2:
            return "MethodDef#%d" % row
        if tag == 3:
            return "ModuleRef#%d" % row
        return "TypeSpec#%d" % row

    def resolve_method_token(self, tok):
        table = (tok >> 24) & 0xFF
        row = tok & 0xFFFFFF
        if table == 0x06:  # MethodDef
            if 0 < row <= len(self.asm.methods):
                return self.asm.methods[row - 1][0]
            return "MethodDef#%d" % row
        if table == 0x0A:  # MemberRef
            if 0 < row <= len(self.memberrefs):
                cls, nm = self.memberrefs[row - 1]
                return "%s::%s" % (self._type_name(cls), nm)
            return "MemberRef#%d" % row
        if table == 0x2B:
            return "MethodSpec#%d" % row
        return "tok 0x%08x" % tok

    def resolve_field_token(self, tok):
        table = (tok >> 24) & 0xFF
        row = tok & 0xFFFFFF
        if table == 0x04:
            if 0 < row <= len(self.asm.fields):
                return self.asm.fields[row - 1][0]
            return "Field#%d" % row
        if table == 0x0A:
            if 0 < row <= len(self.memberrefs):
                cls, nm = self.memberrefs[row - 1]
                return "%s::%s" % (self._type_name(cls), nm)
        return "tok 0x%08x" % tok

    def disasm(self, type_short, method_short):
        asm = self.asm
        d = asm.data
        rows = asm.type_rows()
        si = 4 if asm.STR4 else 2
        bi = 4 if asm.BLB4 else 2
        msz = 4 + 2 + 2 + si + bi + 2
        for ti, (fn, fl, ml) in enumerate(rows):
            if fn != type_short and not fn.endswith("." + type_short):
                continue
            ml_end = rows[ti + 1][2] if ti + 1 < asm.n_td else asm.n_md + 1
            for mi in range(ml - 1, ml_end - 1):
                if not (0 <= mi < asm.n_md):
                    continue
                if asm.methods[mi][0] != method_short:
                    continue
                r = asm.off[0x06] + mi * msz
                rva = struct.unpack_from("<I", d, r)[0]
                if rva == 0:
                    print("%s :: no body (abstract/extern)" % method_short)
                    return
                fo = asm.r2o(rva)
                print("==== %s.%s (RVA 0x%x) ====" % (fn, method_short, rva))
                self._dump_body(fo)
                return
        print("method not found:", type_short, method_short)

    def _dump_body(self, fo):
        d = self.asm.data
        hdr = d[fo]
        if hdr & 3 == 2:  # tiny
            code_sz = hdr >> 2
            il = d[fo + 1: fo + 1 + code_sz]
            self._dump_il(il)
        elif hdr & 3 == 3:  # fat
            flags = struct.unpack_from("<H", d, fo)[0]
            code_sz = struct.unpack_from("<I", d, fo + 4)[0]
            il = d[fo + 12: fo + 12 + code_sz]
            self._dump_il(il)
        else:
            print("unknown method body header 0x%02x" % hdr)

    def _dump_il(self, il):
        pos = 0
        n = len(il)
        out = []
        while pos < n:
            off = pos
            b = il[pos]; pos += 1
            if b == 0xFE:
                fb = il[pos]; pos += 1
                name, kind, sz = FE_OP.get(fb, ("FE 0x%02x" % fb, "none", 0))
            else:
                name, kind, sz = OP.get(b, ("0x%02x" % b, "none", 0))
            operand = ""
            if kind == "none":
                pass
            elif kind == "si1":
                operand = "%d" % struct.unpack_from("b", il, pos)[0]; pos += 1
            elif kind == "sbr":
                target = pos + 1 + struct.unpack_from("b", il, pos)[0]
                operand = "-> IL_%04x" % target; pos += 1
            elif kind in ("i4", "method", "field", "str", "type", "sig", "tok"):
                raw = struct.unpack_from("<I", il, pos)[0]; pos += 4
                if kind == "method":
                    operand = self.resolve_method_token(raw)
                elif kind == "field":
                    operand = self.resolve_field_token(raw)
                elif kind == "str":
                    operand = "<str>"
                elif kind == "type":
                    operand = "0x%08x" % raw
                else:
                    operand = "0x%08x" % raw
            elif kind == "i8":
                raw = struct.unpack_from("<Q", il, pos)[0]; pos += 8
                operand = "%d" % raw
            elif kind == "r4":
                raw = struct.unpack_from("<f", il, pos)[0]; pos += 4
                operand = "%.4f" % raw
            elif kind == "r8":
                raw = struct.unpack_from("<d", il, pos)[0]; pos += 8
                operand = "%.4f" % raw
            elif kind == "br":
                target = pos + 4 + struct.unpack_from("<i", il, pos)[0]
                operand = "-> IL_%04x" % target; pos += 4
            elif kind == "i2":
                operand = "%d" % struct.unpack_from("<H", il, pos)[0]; pos += 2
            elif kind == "i1":
                operand = "%d" % struct.unpack_from("B", il, pos)[0]; pos += 1
            elif kind == "switch":
                cnt = struct.unpack_from("<I", il, pos)[0]; pos += 4
                targs = []
                for _ in range(cnt):
                    targs.append(struct.unpack_from("<i", il, pos)[0]); pos += 4
                operand = "%d targets" % cnt
            out.append("  IL_%04x: %-14s %s" % (off, name, operand))
        print("\n".join(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--type", required=True)
    ap.add_argument("--method", required=True)
    args = ap.parse_args()
    asm = Assembly(args.path)
    asm.build_names()
    dis = Disassembler(asm)
    dis.disasm(args.type, args.method)


if __name__ == "__main__":
    main()

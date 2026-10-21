#!/usr/bin/env python3
"""Extract exact method/field signatures from a .NET assembly's CLI metadata.

Read-only analysis helper for the Draw & Guess plugin. No decompiler needed:
parses the PE/CLI header, metadata streams, and the #~ tables to recover type
names, method names, and their signatures (from the #Blob signature heap).

Usage:
    python tools/extract_signatures.py <assembly.dll> [--type TypeName] [--method MethodName] [--all-types]
"""
import struct
import sys
import argparse

ELT = {
    0x01: "void", 0x02: "bool", 0x03: "char", 0x04: "i1", 0x05: "u1",
    0x06: "i2", 0x07: "u2", 0x08: "i4", 0x09: "u4", 0x0A: "i8", 0x0B: "u8",
    0x0C: "float", 0x0D: "double", 0x0E: "string", 0x0F: "ptr", 0x10: "byref",
    0x11: "valuetype", 0x12: "class", 0x13: "!var", 0x14: "array",
    0x15: "genericinst", 0x16: "typedbyref", 0x18: "nativeint", 0x19: "nativeuint",
    0x1B: "fnptr", 0x1C: "object", 0x1D: "[]", 0x1E: "!!mvar", 0x1F: "modreq",
    0x20: "modopt", 0x45: "pinned",
}


class Assembly:
    def __init__(self, path):
        self.path = path
        self.data = open(path, "rb").read()
        self._parse_pe()
        self._parse_metadata()

    def _parse_pe(self):
        d = self.data
        e = struct.unpack_from("<I", d, 0x3C)[0]
        self.nsect = struct.unpack_from("<H", d, e + 6)[0]
        optsz = struct.unpack_from("<H", d, e + 20)[0]
        opt = e + 24
        magic = struct.unpack_from("<H", d, opt)[0]
        dd = opt + (112 if magic == 0x20B else 96)
        self.com_rva = struct.unpack_from("<I", d, dd + 14 * 8)[0]
        self.sec_off = opt + optsz

    def r2o(self, rva):
        d = self.data
        for i in range(self.nsect):
            s = self.sec_off + i * 40
            va = struct.unpack_from("<I", d, s + 12)[0]
            vs = struct.unpack_from("<I", d, s + 8)[0]
            pr = struct.unpack_from("<I", d, s + 20)[0]
            rs = struct.unpack_from("<I", d, s + 16)[0]
            if va <= rva < va + max(vs, rs):
                return pr + rva - va
        return None

    def _parse_metadata(self):
        d = self.data
        cli = self.r2o(self.com_rva)
        meta_rva = struct.unpack_from("<I", d, cli + 8)[0]
        md = self.r2o(meta_rva)
        vlen = struct.unpack_from("<I", d, md + 12)[0]
        nstrm = struct.unpack_from("<H", d, md + 16 + vlen + 2)[0]
        pos = md + 16 + vlen + 4
        streams = {}
        for _ in range(nstrm):
            off = struct.unpack_from("<I", d, pos)[0]; pos += 4
            sz = struct.unpack_from("<I", d, pos)[0]; pos += 4
            j = pos
            while d[j] != 0:
                j += 1
            name = d[pos:j].decode("ascii")
            pos = (j + 1 + 3) & ~3
            streams[name] = (md + off, sz)
        self.t_off, _ = streams["#~"]
        self.s_off, _ = streams["#Strings"]
        self.b_off, _ = streams["#Blob"]
        hs = d[self.t_off + 6]
        self.STR4 = bool(hs & 1)
        self.BLB4 = bool(hs & 4)
        valid = struct.unpack_from("<Q", d, self.t_off + 8)[0]
        present = [i for i in range(64) if valid & (1 << i)]
        rc = {}
        rp = self.t_off + 24
        for t in present:
            rc[t] = struct.unpack_from("<I", d, rp)[0]; rp += 4
        si = 4 if self.STR4 else 2
        bi = 4 if self.BLB4 else 2
        # row sizes for the tables we touch (Module, TypeRef, TypeDef, Field, MethodDef)
        sizes = {0x00: 2 + si + 2 + 2 + 2, 0x01: 2 + si * 2, 0x02: 4 + si * 2 + 2 + 2 + 2,
                 0x04: 2 + si + bi, 0x06: 4 + 2 + 2 + si + bi + 2}
        self.sizes = sizes
        self.si = si
        self.bi = bi
        self.off = {}
        o = self.t_off + 24 + 4 * len(present)
        for t in present:
            self.off[t] = o
            o += sizes.get(t, 0) * rc.get(t, 0)
        self.rc = rc
        self.n_td = rc.get(0x02, 0)
        self.n_md = rc.get(0x06, 0)
        self.n_fd = rc.get(0x04, 0)

    def s_at(self, idx):
        if idx == 0:
            return ""
        off = self.s_off + idx
        j = self.data.find(b"\x00", off)
        return self.data[off:j].decode("utf-8", "replace")

    def blob_at(self, idx):
        off = self.b_off + idx
        ln, off = self._read_comp_abs(off)
        return self.data[off:off + ln]

    def _read_comp_abs(self, off):
        d = self.data
        b = d[off]
        if b & 0x80 == 0:
            return b, off + 1
        if b & 0xC0 == 0x80:
            return ((b & 0x3F) << 8) | d[off + 1], off + 2
        return ((b & 0x1F) << 24) | (d[off + 1] << 16) | (d[off + 2] << 8) | d[off + 3], off + 4

    def _read_comp(self, buf, pos):
        b = buf[pos]
        if b & 0x80 == 0:
            return b, pos + 1
        if b & 0xC0 == 0x80:
            return ((b & 0x3F) << 8) | buf[pos + 1], pos + 2
        return ((b & 0x1F) << 24) | (buf[pos + 1] << 16) | (buf[pos + 2] << 8) | buf[pos + 3], pos + 4

    def _type_name(self, idx):
        tag = idx & 3
        row = idx >> 2
        if row == 0:
            return "<null>"
        if tag == 0:
            return self.td_names[row - 1] if row <= len(self.td_names) else "TypeDef#%d" % row
        if tag == 1:
            return self.tr_names[row - 1] if row <= len(self.tr_names) else "TypeRef#%d" % row
        return "TypeSpec#%d" % row

    def _parse_type(self, buf, pos):
        e = buf[pos]; pos += 1
        if e in ELT and e not in (0x0F, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x1B, 0x1D, 0x1E, 0x1F, 0x20):
            return ELT[e], pos
        if e in (0x11, 0x12):
            idx, pos = self._read_comp(buf, pos)
            return ELT[e] + " " + self._type_name(idx), pos
        if e == 0x1D:
            el, pos = self._parse_type(buf, pos)
            return el + "[]", pos
        if e == 0x10:
            el, pos = self._parse_type(buf, pos)
            return el + "&", pos
        if e == 0x0F:
            el, pos = self._parse_type(buf, pos)
            return el + "*", pos
        if e in (0x13, 0x1E):
            n, pos = self._read_comp(buf, pos)
            return ("!" if e == 0x13 else "!!") + str(n), pos
        if e == 0x14:
            el, pos = self._parse_type(buf, pos)
            rank, pos = self._read_comp(buf, pos)
            return el + "[...]", pos
        if e == 0x15:
            kind, pos = self._parse_type(buf, pos)
            n, pos = self._read_comp(buf, pos)
            args = []
            for _ in range(n):
                a, pos = self._parse_type(buf, pos)
                args.append(a)
            return "%s<%s>" % (kind, ",".join(args)), pos
        if e in (0x1F, 0x20):
            idx, pos = self._read_comp(buf, pos)
            el, pos = self._parse_type(buf, pos)
            return el, pos
        return "elt0x%02x" % e, pos

    def parse_method_sig(self, blob):
        pos = 0
        flags = blob[0]; pos = 1
        if flags & 0x10:
            _, pos = self._read_comp(blob, pos)
        nparam, pos = self._read_comp(blob, pos)
        ret, pos = self._parse_type(blob, pos)
        params = []
        for _ in range(nparam):
            t, pos = self._parse_type(blob, pos)
            params.append(t)
        return ret, params

    def parse_field_sig(self, blob):
        t, _ = self._parse_type(blob, 1)
        return t

    def _str_i(self, off):
        return struct.unpack_from("<I" if self.STR4 else "<H", self.data, off)[0]

    def _blob_i(self, off):
        return struct.unpack_from("<I" if self.BLB4 else "<H", self.data, off)[0]

    def build_names(self):
        d = self.data
        si = 4 if self.STR4 else 2
        bi = 4 if self.BLB4 else 2
        off = self.off
        # TypeDef names
        self.td_names = []
        for i in range(self.n_td):
            r = off[0x02] + i * (4 + si * 2 + 2 + 2 + 2)
            nm = self.s_at(self._str_i(r + 4))
            ns = self.s_at(self._str_i(r + 4 + si))
            self.td_names.append((ns + "." + nm) if ns else nm)
        # TypeRef names
        self.tr_names = []
        for i in range(self.rc.get(0x01, 0)):
            r = off[0x01] + i * (2 + si * 2)
            nm = self.s_at(self._str_i(r + 2))
            ns = self.s_at(self._str_i(r + 2 + si))
            self.tr_names.append((ns + "." + nm) if ns else nm)
        # methods: (name, sig_blob_index) per row
        self.methods = []
        for i in range(self.n_md):
            r = off[0x06] + i * (4 + 2 + 2 + si + bi + 2)
            name_i = self._str_i(r + 8)
            sig_i = self._blob_i(r + 8 + si)
            self.methods.append((self.s_at(name_i), sig_i))
        # fields: (name, sig_blob_index) per row
        self.fields = []
        for i in range(self.n_fd):
            r = off[0x04] + i * (2 + si + bi)
            name_i = self._str_i(r + 2)
            sig_i = self._blob_i(r + 2 + si)
            self.fields.append((self.s_at(name_i), sig_i))

    def type_rows(self):
        d = self.data
        si = 4 if self.STR4 else 2
        rows = []
        for i in range(self.n_td):
            r = self.off[0x02] + i * (4 + si * 2 + 2 + 2 + 2)
            nm = self.s_at(self._str_i(r + 4))
            ns = self.s_at(self._str_i(r + 4 + si))
            fl = struct.unpack_from("<H", d, r + 4 + si * 2 + 2)[0]
            ml = struct.unpack_from("<H", d, r + 4 + si * 2 + 4)[0]
            rows.append(((ns + "." + nm) if ns else nm, fl, ml))
        return rows

    def find_methods(self, type_short, method_short):
        res = []
        rows = self.type_rows()
        for ti, (fn, fl, ml) in enumerate(rows):
            if fn != type_short and not fn.endswith("." + type_short):
                continue
            ml_end = rows[ti + 1][2] if ti + 1 < self.n_td else self.n_md + 1
            for mi in range(ml - 1, ml_end - 1):
                if 0 <= mi < self.n_md and self.methods[mi][0] == method_short:
                    ret, params = self.parse_method_sig(self.blob_at(self.methods[mi][1]))
                    res.append((method_short, ret, params))
        return res

    def find_fields(self, type_short, field_short):
        res = []
        rows = self.type_rows()
        for ti, (fn, fl, ml) in enumerate(rows):
            if fn != type_short and not fn.endswith("." + type_short):
                continue
            fl_end = rows[ti + 1][1] if ti + 1 < self.n_td else self.n_fd + 1
            for fi in range(fl - 1, fl_end - 1):
                if 0 <= fi < self.n_fd and self.fields[fi][0] == field_short:
                    res.append((field_short, self.parse_field_sig(self.blob_at(self.fields[fi][1]))))
        return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--type")
    ap.add_argument("--method")
    ap.add_argument("--field")
    ap.add_argument("--all-types", action="store_true")
    args = ap.parse_args()
    asm = Assembly(args.path)
    asm.build_names()

    if args.all_types:
        for fn, fl, ml in asm.type_rows():
            print(fn)
        return

    if args.type and args.method:
        for m, ret, params in asm.find_methods(args.type, args.method):
            print("%s %s(%s)" % (ret, m, ", ".join(params)))
        return

    if args.type and args.field:
        for f, t in asm.find_fields(args.type, args.field):
            print("%s : %s" % (t, f))
        return

    if args.type:
        rows = asm.type_rows()
        matched = [(fn, fl, ml) for fn, fl, ml in rows if fn.endswith("." + args.type) or fn == args.type]
        if not matched:
            print("type not found:", args.type)
            return
        for fn, fl, ml in matched:
            ti = rows.index((fn, fl, ml))
            fl_end = rows[ti + 1][1] if ti + 1 < asm.n_td else asm.n_fd + 1
            ml_end = rows[ti + 1][2] if ti + 1 < asm.n_td else asm.n_md + 1
            flds = [asm.fields[i][0] for i in range(fl - 1, fl_end - 1) if 0 <= i < asm.n_fd]
            mths = [asm.methods[i][0] for i in range(ml - 1, ml_end - 1) if 0 <= i < asm.n_md]
            print("TYPE", fn)
            print("  FIELDS:", ", ".join(flds))
            print("  METHODS:", ", ".join(mths))
        return

    ap.print_help()


if __name__ == "__main__":
    main()

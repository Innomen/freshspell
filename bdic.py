#!/usr/bin/env python3
"""
Pure-Python reader + writer for Chromium/Brave's BDic (.bdic) spellcheck format.

Faithful port of chromium third_party/hunspell/google/bdict_writer.cc (+ bdict.h),
operating on bytes throughout (the trie keys on raw bytes / UTF-8). No external deps,
no compiled binary. Format: BDic v2.0, 32-byte header with MD5(aff+dic) digest.

Validated by round-tripping Brave's shipped en-US-10-1.bdic byte-for-byte (see --validate).
Reference sources saved in /home/innomen/dict-build/bdic-format-reference/.

Usage:
  python3 bdic.py --validate /path/to/en-US-10-1.bdic
  python3 bdic.py --build wordlist.txt out.bdic        # one word per line (UTF-8)
"""
import argparse, hashlib, struct, sys

SIGNATURE = 0x63694442  # "BDic"
MAJOR, MINOR = 2, 0
HEADER_FMT = "<IHHII"   # signature, major, minor, aff_offset, dic_offset (then 16B digest)
HEADER_SIZE = 32

# leaf
LEAF_MAX_FIRST_AFFIX_ID = 0x1FFE
FIRST_AFFIX_IS_UNUSED = 0x1FFF
MAX_AFFIXES_PER_WORD = 32

# ---------------------------------------------------------------- writer side

class DicNode:
    __slots__ = ("addition", "children", "leaf_addition", "affix_indices", "storage", "size")
    def __init__(self):
        self.addition = 0
        self.children = []
        self.leaf_addition = b""
        self.affix_indices = []
        self.storage = None
        self.size = 0
    def is_leaf(self):
        return not self.children

def _nth_is(word, n, ch):
    if n > len(word):
        return False
    c = word[n] if n < len(word) else 0
    return c == ch

def build_trie(words, begin, end, depth, node):
    """words: list of (bytes, [affix ints]) sorted ascending by bytes, unique."""
    begin_str = words[begin][0]
    if len(begin_str) < depth:
        node.addition = 0
        node.affix_indices = words[begin][1]
        return begin + 1

    if depth == 0 and begin == 0:
        match = end - begin
        node.addition = 0
    else:
        match = 0
        node.addition = begin_str[depth - 1]
        while begin + match < end and _nth_is(words[begin + match][0], depth - 1, node.addition):
            match += 1

    if match == 1:
        node.affix_indices = words[begin][1]
        node.leaf_addition = begin_str[depth:]
        return begin + 1

    i = begin
    while i < begin + match:
        cur = DicNode()
        i = build_trie(words, i, begin + match, depth + 1, cur)
        node.children.append(cur)
    return begin + match

def _lookup_details(children):
    if not children:
        return False, 0, 0
    first_offset = 0
    has_0th = False
    if children[0].addition == 0:
        has_0th = True
        first_offset = 1
    if len(children) == first_offset:
        return has_0th, 0, 0
    first_item = children[first_offset].addition & 0xFF
    last_item = children[-1].addition & 0xFF
    return has_0th, first_item, last_item - first_item + 1

def compute_storage(node):
    if node.is_leaf():
        supp = 0
        if node.affix_indices[0] > LEAF_MAX_FIRST_AFFIX_ID:
            supp = len(node.affix_indices) * 2 + 2
        elif len(node.affix_indices) > 1:
            supp = len(node.affix_indices) * 2
        if not node.leaf_addition:
            node.storage = "LEAF"; node.size = 2 + supp
        else:
            node.storage = "LEAFMORE"; node.size = 3 + len(node.leaf_addition) + supp
        return node.size

    child_size = sum(compute_storage(c) for c in node.children)
    n = len(node.children)
    if n < 16 and child_size <= 0xFF:
        node.storage = "LIST8"; node.size = 1 + n * 2 + child_size; return node.size
    if n < 16 and child_size <= 0xFFFF:
        node.storage = "LIST16"; node.size = 1 + n * 3 + child_size; return node.size
    has_0th, _first, count = _lookup_details(node.children)
    if child_size + 2 + (2 if has_0th else 0) + count * 2 < 0xFFFF:
        node.storage = "LOOKUP16"; node.size = 2 + (2 if has_0th else 0) + count * 2 + child_size
    else:
        node.storage = "LOOKUP32"; node.size = 2 + (4 if has_0th else 0) + count * 4 + child_size
    return node.size

def _ser_leaf(node, out):
    aff = node.affix_indices
    first = aff[0] if aff else 0
    first_in_supp = 1
    if first > LEAF_MAX_FIRST_AFFIX_ID:
        first_in_supp = 0
        first = FIRST_AFFIX_IS_UNUSED
    idb = (first >> 8) & 0x1F
    if node.storage == "LEAFMORE":
        idb |= 0x40
    if len(aff) > 1 or first_in_supp == 0:
        idb |= 0x20
    out.append(idb)
    out.append(first & 0xFF)
    if node.storage == "LEAFMORE":
        out += node.leaf_addition; out.append(0)
    if len(aff) > first_in_supp:
        for i in range(first_in_supp, min(len(aff), MAX_AFFIXES_PER_WORD)):
            out.append(aff[i] & 0xFF); out.append((aff[i] >> 8) & 0xFF)
        out.append(0xFF); out.append(0xFF)

def _ser_list(node, out, base):
    is8 = node.storage == "LIST8"
    idb = 0xE0 | (0 if is8 else 0xF0) | len(node.children)
    out.append(idb)
    bpe = 2 if is8 else 3
    table = len(out)
    out += b"\x00" * (len(node.children) * bpe)
    children_begin = len(out)
    for i, c in enumerate(node.children):
        out[table + i * bpe] = c.addition & 0xFF
        off = len(out) - children_begin
        if is8:
            assert off <= 0xFF
            out[table + i * bpe + 1] = off & 0xFF
        else:
            struct.pack_into("<H", out, table + i * bpe + 1, off)
        _ser_trie(c, out, base)

def _ser_lookup(node, out, base):
    has_0th, first_item, count = _lookup_details(node.children)
    is32 = node.storage == "LOOKUP32"
    idb = 0xC0
    if is32: idb |= 0xC2
    if has_0th: idb |= 0xC1
    begin = len(out)
    out.append(idb); out.append(first_item & 0xFF); out.append(count & 0xFF)
    bpe = 4 if is32 else 2
    zeroth = len(out)
    if has_0th:
        out += b"\x00" * bpe
    table = len(out)
    out += b"\x00" * (count * bpe)
    for i, c in enumerate(node.children):
        if i == 0 and has_0th:
            off_at = zeroth
        else:
            off_at = table + ((c.addition & 0xFF) - first_item) * bpe
        if is32:
            # 32-bit offsets are ABSOLUTE from the start of the FILE (base = dic offset)
            struct.pack_into("<I", out, off_at, base + len(out))
        else:
            struct.pack_into("<H", out, off_at, len(out) - begin)
        _ser_trie(c, out, base)

def _ser_trie(node, out, base):
    s = node.storage
    if s in ("LEAF", "LEAFMORE"): _ser_leaf(node, out)
    elif s in ("LIST8", "LIST16"): _ser_list(node, out, base)
    else: _ser_lookup(node, out, base)

def serialize_dic(words, base_offset=0):
    """words: list of (bytes, [affixes]); returns dic-section bytes.
    base_offset = absolute position of the dic section in the final file (for LOOKUP32)."""
    root = DicNode()
    build_trie(words, 0, len(words), 0, root)
    compute_storage(root)
    out = bytearray()
    _ser_trie(root, out, base_offset)
    return bytes(out)

def build_aff_empty(comment=b""):
    """Minimal aff section: no affix groups/rules/replacements (flat wordlist)."""
    out = bytearray(16)               # AffHeader placeholder (4 x uint32)
    out.append(0x0A); out += comment; out.append(0x0A)   # \n comment \n
    ag = len(out); out += b"AF 0"; out.append(0); out.append(0)        # "AF 0\0\0"
    ar = len(out); out.append(0)
    rep = len(out); out.append(0)
    oth = len(out); out.append(0)
    struct.pack_into("<IIII", out, 0, ag, ar, rep, oth)
    return bytes(out)

def write_bdict(words):
    aff_bytes = build_aff_empty()
    aff_off = HEADER_SIZE
    dic_off = aff_off + len(aff_bytes)
    dic_bytes = serialize_dic(words, base_offset=dic_off)   # LOOKUP32 needs the file-absolute base
    out = bytearray(HEADER_SIZE)
    out += aff_bytes
    out += dic_bytes
    struct.pack_into(HEADER_FMT, out, 0, SIGNATURE, MAJOR, MINOR, aff_off, dic_off)
    out[16:32] = hashlib.md5(bytes(out[aff_off:])).digest()
    return bytes(out)

# ---------------------------------------------------------------- reader side

def parse_header(data):
    sig, major, minor, aff_off, dic_off = struct.unpack_from(HEADER_FMT, data, 0)
    assert sig == SIGNATURE, "bad signature"
    return major, minor, aff_off, dic_off, data[16:32]

def enumerate_dic(data, dic_off):
    """Walk the trie, yielding (word_bytes, [affixes]) in trie (sorted) order."""
    out = []
    def read_leaf(pos):
        idb = data[pos]
        field = ((idb & 0x1F) << 8) | data[pos + 1]
        p = pos + 2
        has_add = (idb & 0xC0) == 0x40
        has_follow = (idb & 0xA0) == 0x20
        add = b""
        if has_add:
            z = data.index(0, p); add = data[p:z]; p = z + 1
        aff = []
        if field != FIRST_AFFIX_IS_UNUSED:
            aff.append(field)
        if has_follow:
            while True:
                v = struct.unpack_from("<H", data, p)[0]; p += 2
                if v == 0xFFFF: break
                aff.append(v)
        return add, aff
    def walk(pos, path):
        idb = data[pos]
        if (idb & 0x80) == 0:                     # leaf
            add, aff = read_leaf(pos)
            out.append((path + add, aff)); return
        if (idb & 0xFC) == 0xC0:                  # lookup
            has_0th = idb & 1; is32 = idb & 2
            first_item = data[pos + 1]; count = data[pos + 2]
            bpe = 4 if is32 else 2
            kids = []
            zeroth = pos + 3
            table = pos + 3 + (bpe if has_0th else 0)
            if has_0th:
                off = struct.unpack_from("<I" if is32 else "<H", data, zeroth)[0]
                if off: kids.append((0, off if is32 else pos + off))
            for i in range(count):
                off_at = table + i * bpe
                off = struct.unpack_from("<I" if is32 else "<H", data, off_at)[0]
                if off: kids.append((first_item + i, off if is32 else pos + off))
            for ch, cabs in kids:
                walk(cabs, path + (bytes([ch]) if ch else b""))
            return
        if (idb & 0xE0) == 0xE0:                  # list
            is16 = (idb & 0xF0) == 0xF0; count = idb & 0x0F
            bpe = 3 if is16 else 2
            table = pos + 1; children_begin = table + count * bpe
            for i in range(count):
                ch = data[table + i * bpe]
                off = struct.unpack_from("<H", data, table + i * bpe + 1)[0] if is16 else data[table + i * bpe + 1]
                walk(children_begin + off, path + (bytes([ch]) if ch else b""))
            return
        raise ValueError(f"unknown node id {idb:#x} at {pos}")
    walk(dic_off, b"")
    return out

# ---------------------------------------------------------------- cli

def main():
    sys.setrecursionlimit(100000)
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", metavar="BDIC")
    ap.add_argument("--build", nargs=2, metavar=("WORDLIST", "OUT"))
    args = ap.parse_args()

    if args.validate:
        data = open(args.validate, "rb").read()
        major, minor, aff_off, dic_off, digest = parse_header(data)
        print(f"version {major}.{minor}  aff_off={aff_off}  dic_off={dic_off}  size={len(data)}")
        print("header MD5 matches:", hashlib.md5(data[aff_off:]).digest() == digest)
        words = enumerate_dic(data, dic_off)
        print(f"enumerated words: {len(words)}")
        # spot check a few common words are present
        wset = {w for w, _ in words}
        for probe in (b"the", b"cat", b"dictionary", b"experience"):
            print(f"  contains {probe!r}: {probe in wset}")
        # round-trip the DIC section byte-for-byte (proves the serializer)
        rebuilt = serialize_dic(words, base_offset=dic_off)
        real_dic = data[dic_off:]
        print(f"dic re-serialized: {len(rebuilt)} bytes vs real {len(real_dic)}")
        print("DIC SECTION BYTE-IDENTICAL:", rebuilt == real_dic)
        if rebuilt != real_dic:
            for i in range(min(len(rebuilt), len(real_dic))):
                if rebuilt[i] != real_dic[i]:
                    print(f"  first diff at byte {i}: got {rebuilt[i]:#x} want {real_dic[i]:#x}")
                    break
        return

    if args.build:
        wl, out = args.build
        seen = set(); words = []
        for line in open(wl, "rb"):
            w = line.strip()
            if not w or w.startswith(b"#") or w in seen:
                continue
            seen.add(w); words.append((w, [0]))
        words.sort(key=lambda x: x[0])
        blob = write_bdict(words)
        open(out, "wb").write(blob)
        # self-check: read it back
        _, _, ao, do, dg = parse_header(blob)
        ok_md5 = hashlib.md5(blob[ao:]).digest() == dg
        back = {w for w, _ in enumerate_dic(blob, do)}
        miss = [w for w, _ in words if w not in back]
        print(f"wrote {out}: {len(words)} words, {len(blob)} bytes, md5_ok={ok_md5}, "
              f"readback_missing={len(miss)}")
        return

    ap.print_help()

if __name__ == "__main__":
    main()

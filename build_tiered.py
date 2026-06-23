#!/usr/bin/env python3
"""
Build a frequency-TIERED en-US .bdic: keep every word RECOGNIZED, but only let common
words be OFFERED as spelling SUGGESTIONS.

Why: Brave/Chromium suggests corrections by mutating your typo and asking the dictionary
"is this a word?" for each mutation. A comprehensive 1M-word dict means a typo's mutations
land on obscure junk (hydroxypropiophenone, ...) that crowds out the obvious fix — and some
typos ARE rare words, so they never even flag. Hunspell's NOSUGGEST flag ('!') fixes this:
a NOSUGGEST word stays in the dictionary (no red underline) but is never produced as a
suggestion. Stock Brave already uses it for profanity (recognized, never suggested).

So we tag:
  - common / yours  -> affix 0      (no flags: recognized AND suggestable)
  - obscure tail    -> NOSUGGEST    (recognized, never suggested)

"Common" = top-N wordfreq words  UNION  your own added-words + personal coinages (words YOU
use stay suggestable even if globally rare). The NOSUGGEST alias is found dynamically in the
carried-over stock aff section (don't hardcode it; group order shifts across browser versions).

"Common" defaults to the top-N wordfreq words; pass --added FILE to also keep your own
vocabulary suggestable (one word per line — e.g. an export of your browser's custom dictionary),
and the repo's personal-words.txt is always included.

Usage:
  python3 build_tiered.py [--top-n 60000] [--added my-words.txt] [--out en-US-ems.bdic]
"""
import argparse, glob, os, struct, sys
import bdic  # local

def default_stock():
    for cand in (
        "~/.config/BraveSoftware/Brave-Browser/Dictionaries/en-US-10-1.bdic.stock-backup",
        "~/.config/google-chrome/Default/Dictionaries/en-US-10-1.bdic.stock-backup"):
        p = os.path.expanduser(cand)
        if os.path.exists(p):
            return p
    return os.path.expanduser(
        "~/.config/BraveSoftware/Brave-Browser/Dictionaries/en-US-10-1.bdic.stock-backup")
STOCK = default_stock()

def find_nosuggest_alias(aff_bytes):
    """Return the 1-based AF alias whose flagset is exactly '!' (pure NOSUGGEST), or None."""
    ag, ar, rep, oth = struct.unpack_from("<IIII", aff_bytes, 0)
    fields = aff_bytes[16:ar].split(b"\x00")
    if not fields or b"AF " not in fields[0]:
        return None
    count = int(fields[0].split(b"AF ")[1])
    for k in range(1, count + 1):
        f = fields[k]
        if f.startswith(b"AF ") and f[3:] == b"!":
            return k
    return None

def load_lines(path):
    if not os.path.exists(path):
        return set()
    out = set()
    for ln in open(path, "rb"):
        w = ln.strip()
        if w and not w.startswith(b"#"):
            out.add(w.lower())
    return out

def main():
    sys.setrecursionlimit(1_000_000)
    ap = argparse.ArgumentParser()
    ap.add_argument("--wordlist", default="build/combined-words.txt")
    ap.add_argument("--stock", default=STOCK)
    ap.add_argument("--top-n", type=int, default=60000,
                    help="how many of the most common English words stay suggestable")
    ap.add_argument("--added", default=None,
                    help="optional file of your own words (one per line) to keep suggestable "
                         "even if globally rare, e.g. an export of your custom dictionary")
    ap.add_argument("--out", default="en-US-ems.bdic")
    a = ap.parse_args()

    from wordfreq import top_n_list
    common = set(w.encode("utf8") for w in top_n_list("en", a.top_n))
    # words YOU use stay suggestable even if globally rare:
    mine = load_lines("personal-words.txt")
    if a.added:
        mine |= load_lines(a.added)
    suggestable_lc = common | mine

    aff_bytes = bdic.extract_aff(a.stock)
    nosug = find_nosuggest_alias(aff_bytes)
    if nosug is None:
        sys.exit("ABORT: no pure-'!' NOSUGGEST group found in stock aff; cannot tier safely.")
    print(f"NOSUGGEST alias in stock aff: {nosug}")

    seen, words = set(), []
    n_sugg = n_nosug = 0
    for ln in open(a.wordlist, "rb"):
        w = ln.strip()
        if not w or w.startswith(b"#") or w in seen:
            continue
        seen.add(w)
        is_sugg = (w.lower() in suggestable_lc)
        words.append((w, [0] if is_sugg else [nosug]))
        n_sugg += is_sugg
        n_nosug += not is_sugg
    words.sort(key=lambda x: x[0])

    blob = bdic.write_bdict(words, aff_bytes)
    open(a.out, "wb").write(blob)

    # self-check
    _, _, ao, do, dg = bdic.parse_header(blob)
    import hashlib
    md5_ok = hashlib.md5(blob[ao:]).digest() == dg
    print(f"wrote {a.out}: {len(words)} words ({n_sugg} suggestable / {n_nosug} NOSUGGEST), "
          f"{len(blob)} bytes, md5_ok={md5_ok}")
    # spot check: common words suggestable, obscure tail not
    back = {w: aff for w, aff in bdic.enumerate_dic(blob, do)}
    def tag(w):
        a_ = back.get(w.encode())
        return "MISSING" if a_ is None else ("suggestable" if a_ == [] or a_ == [0] else f"NOSUGGEST{a_}")
    for probe in ("interests", "experience", "the", "antifragile", "hedcore",
                  "hydroxypropiophenone", "thymidylyltransferase"):
        print(f"   {probe:24} -> {tag(probe)}")

if __name__ == "__main__":
    main()

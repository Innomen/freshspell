#!/usr/bin/env python3
"""
Build a comprehensive modern English wordlist from the kaikki.org Wiktionary extract.

Source (build-time SDK download, ~470 MB; the shipped artifacts are small):
  https://kaikki.org/dictionary/English/words/kaikki.org-dictionary-English-words.jsonl.gz

Outputs (into --build-dir, default /home/innomen/dict-build):
  core-words.txt   English words, lemmas + inflected forms, proper nouns excluded
  names.txt        proper nouns (pos == "name")  -> the optional names pack
  core-lc.txt      lowercased uniq core (for coverage tests / hunspell .dic)

Design notes:
  - Proper nouns split out (pos == "name") so core stays a clean spellcheck list and names
    are an opt-in pack (see README "Names" decision).
  - Wiktionary lists misspellings / eye-dialect / obsolete spellings AS entries. A raw dump
    therefore "accepts" things like "commentor". We FILTER those by sense gloss/tags so the
    dictionary doesn't bless errors. (Found 2026-06-16: "commentor" leaked through unfiltered.)
"""
import argparse, gzip, json, os, re, sys, urllib.request

SRC = "https://kaikki.org/dictionary/English/words/kaikki.org-dictionary-English-words.jsonl.gz"
TOKEN = re.compile(r"^[A-Za-z][A-Za-z'’.\-]*$")   # single token, letter-initial, no spaces
BAD_GLOSS = re.compile(
    r"\b(misspelling|eye dialect|obsolete spelling|obsolete form|nonstandard spelling|"
    r"common misspelling|alternative misspelling|informal spelling of|deliberate misspelling)\b",
    re.I,
)
BAD_TAGS = {"misspelling", "eye-dialect", "obsolete", "nonstandard"}

def keep_token(w):
    # NOTE: lower bound is 1, not 2 — single-letter words ("a", "I", "O") are real.
    # An earlier `1 < len(w)` silently dropped them, so "a" read as a misspelling.
    return isinstance(w, str) and 1 <= len(w) <= 40 and TOKEN.match(w) and not w.endswith(".")

def is_bad_entry(o):
    """True if every sense marks this as a misspelling/eye-dialect/obsolete spelling."""
    senses = o.get("senses") or []
    if not senses:
        return False
    bad = 0
    for s in senses:
        tags = set(s.get("tags") or [])
        glosses = " ".join(s.get("glosses") or [])
        if (tags & BAD_TAGS) or BAD_GLOSS.search(glosses):
            bad += 1
    return bad == len(senses)   # only drop if NO sense is legitimate

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", default="build")
    args = ap.parse_args()
    os.makedirs(args.build_dir, exist_ok=True)
    gz = os.path.join(args.build_dir, "english-words.jsonl.gz")
    if not os.path.exists(gz):
        print(f"downloading {SRC} ...")
        urllib.request.urlretrieve(SRC, gz)

    core, names = set(), set()
    n = dropped = 0
    with gzip.open(gz, "rt", encoding="utf-8") as f:
        for line in f:
            n += 1
            try:
                o = json.loads(line)
            except Exception:
                continue
            if is_bad_entry(o):
                dropped += 1
                continue
            w, pos = o.get("word"), o.get("pos", "")
            bucket = names if pos == "name" else core
            if keep_token(w):
                bucket.add(w)
            for fm in o.get("forms", []) or []:
                fw = fm.get("form")
                if keep_token(fw):
                    bucket.add(fw)

    def write(name, words):
        with open(os.path.join(args.build_dir, name), "w") as fh:
            fh.write("\n".join(sorted(words)) + "\n")

    write("core-words.txt", core)
    write("names.txt", names)
    write("core-lc.txt", {w.lower() for w in core})
    print(f"lines: {n}  dropped(misspelling-tagged): {dropped}")
    print(f"core: {len(core)}  names: {len(names)}")

if __name__ == "__main__":
    main()

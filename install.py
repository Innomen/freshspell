#!/usr/bin/env python3
"""
Install the comprehensive .bdic into Brave (or any Chromium browser), fail-safe.

- Verifies the source is a valid BDic (signature + internal MD5) BEFORE touching anything.
- Backs up the *pristine* stock dictionary once (never overwrites an existing backup, so the
  original is always recoverable).
- Atomic replace (temp + os.replace) so an interrupted run can't leave a half-written file.
- Idempotent: re-running does nothing if ours is already installed -> doubles as the REPATCH
  tool for when the browser re-downloads a stock dict after a version bump.

Usage:
  python3 install.py                     # Brave, default built dict
  python3 install.py --src X.bdic --dict-dir ~/.config/google-chrome/Default/... (any chromium)
  python3 install.py --restore           # put the stock dict back
"""
import argparse, glob, hashlib, os, shutil, struct, sys

DEFAULT_DICTDIR = os.path.expanduser(
    "~/.config/BraveSoftware/Brave-Browser/Dictionaries")
DEFAULT_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "en-US-ems.bdic")
BACKUP_SUFFIX = ".stock-backup"

def is_valid_bdic(path):
    try:
        d = open(path, "rb").read()
        sig, major, minor, aff, dic = struct.unpack_from("<IHHII", d, 0)
        if sig != 0x63694442:
            return False, "bad signature"
        if hashlib.md5(d[aff:]).digest() != d[16:32]:
            return False, "internal MD5 mismatch"
        return True, f"valid BDic {major}.{minor}, {len(d)} bytes"
    except Exception as e:
        return False, str(e)

def md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()

def targets(dictdir):
    return [p for p in glob.glob(os.path.join(dictdir, "en-US-*.bdic"))
            if not p.endswith(BACKUP_SUFFIX)]

def install(src, dictdir):
    ok, msg = is_valid_bdic(src)
    if not ok:
        sys.exit(f"ABORT: source not a valid bdic ({msg})")
    print(f"source: {src} -> {msg}")
    if not os.path.isdir(dictdir):
        sys.exit(f"ABORT: dict dir not found: {dictdir}")
    tgts = targets(dictdir)
    if not tgts:
        tgts = [os.path.join(dictdir, "en-US-10-1.bdic")]
        print("no existing en-US dict; will create en-US-10-1.bdic")
    src_hash = md5(src)
    for tgt in tgts:
        if os.path.exists(tgt) and md5(tgt) == src_hash:
            print(f"already installed: {os.path.basename(tgt)} (skip)")
            continue
        backup = tgt + BACKUP_SUFFIX
        if os.path.exists(tgt) and not os.path.exists(backup):
            shutil.copy2(tgt, backup)
            print(f"backed up stock -> {os.path.basename(backup)}")
        tmp = tgt + ".tmp"
        shutil.copy2(src, tmp)
        os.replace(tmp, tgt)               # atomic
        print(f"installed -> {os.path.basename(tgt)}")
    print("\nDone. Restart Brave for spellcheck to pick up the new dictionary.")

def restore(dictdir):
    for backup in glob.glob(os.path.join(dictdir, "*" + BACKUP_SUFFIX)):
        tgt = backup[:-len(BACKUP_SUFFIX)]
        shutil.copy2(backup, tgt)
        print(f"restored {os.path.basename(tgt)} from backup")
    print("Done. Restart Brave.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--dict-dir", default=DEFAULT_DICTDIR)
    ap.add_argument("--restore", action="store_true")
    a = ap.parse_args()
    if a.restore:
        restore(a.dict_dir)
    else:
        install(a.src, a.dict_dir)

if __name__ == "__main__":
    main()

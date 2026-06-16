#!/usr/bin/env bash
# Build a comprehensive en-US .bdic from Wiktionary, end to end.
# Output: ./en-US-ems.bdic  (then run: python3 install.py)
set -euo pipefail
cd "$(dirname "$0")"

echo "[1/3] building wordlist from Wiktionary (downloads ~470MB to build/ on first run)"
python3 build_wordlist.py --build-dir build

echo "[2/3] combining core + names (+ optional personal-words.txt)"
cat build/core-words.txt build/names.txt > build/combined-words.txt
[ -f personal-words.txt ] && cat personal-words.txt >> build/combined-words.txt

echo "[3/3] serializing .bdic"
python3 bdic.py --build build/combined-words.txt en-US-ems.bdic

echo
echo "Done -> en-US-ems.bdic"
echo "Install into Brave with:  python3 install.py"
echo "(core only, no proper-noun pack: cat build/core-words.txt > build/combined-words.txt before step 3)"

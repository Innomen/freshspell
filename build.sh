#!/usr/bin/env bash
# Build a comprehensive en-US .bdic from Wiktionary, end to end.
# Output: ./en-US-ems.bdic  (then run: python3 install.py)
set -euo pipefail
cd "$(dirname "$0")"

echo "[1/3] building wordlist from Wiktionary (downloads ~470MB to build/ on first run)"
python3 build_wordlist.py --build-dir build

echo "[2/3] combining core + names (+ optional personal-words.txt)"
cat build/core-words.txt build/names.txt > build/combined-words.txt
if [ -f personal-words.txt ]; then
  cat personal-words.txt >> build/combined-words.txt
else
  echo "  NOTE: no personal-words.txt found — building WITHOUT any coinages/private words." >&2
  echo "        (copy personal-words.txt.example to personal-words.txt to include them.)" >&2
fi

echo "[3/3] serializing .bdic"
# Carry a real aff section (TRY string + REP table) so spellcheck SUGGESTIONS work.
# A flat wordlist alone yields an empty aff -> Brave recognizes words but can't suggest
# corrections for typos (no TRY string => no edit-distance candidates). We borrow the aff
# from the stock dict the browser shipped (the pristine backup install.py made, or the live
# stock dict). No stock found -> build anyway, but warn that suggestions will be degraded.
STOCK=""
for cand in \
  "$HOME/.config/BraveSoftware/Brave-Browser/Dictionaries/en-US-10-1.bdic.stock-backup" \
  /usr/lib*/chromium*/en-US-*.bdic \
  "$HOME/.config/google-chrome/Default/Dictionaries/en-US-*.bdic.stock-backup"; do
  if [ -f "$cand" ]; then STOCK="$cand"; break; fi
done
if [ -n "$STOCK" ]; then
  echo "  carrying aff (TRY+REP suggestion data) from: $STOCK"
  python3 bdic.py --build build/combined-words.txt en-US-ems.bdic --aff-from "$STOCK"
else
  echo "  WARN: no stock .bdic found to borrow an aff section from — building with an EMPTY" >&2
  echo "        aff. Words will be RECOGNIZED but typo SUGGESTIONS will be poor. Install the" >&2
  echo "        browser's default dict first, then rebuild." >&2
  python3 bdic.py --build build/combined-words.txt en-US-ems.bdic
fi

echo
echo "Done -> en-US-ems.bdic"
echo "Install into Brave with:  python3 install.py"
echo "(core only, no proper-noun pack: cat build/core-words.txt > build/combined-words.txt before step 3)"

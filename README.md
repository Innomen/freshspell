# freshspell

A comprehensive, current English spellcheck dictionary for Brave and other Chromium
browsers, plus the pure-Python tooling to build and install it.

## Why this exists

Browser spellcheck dictionaries are curated and conservative. They are built from SCOWL,
which is careful and slow to add words, so they reject large amounts of legitimate modern
English: technical terms, internet coinages that have entered normal use, philosophy and
science vocabulary, ordinary derived forms, and proper nouns.

The motivating measurement: one writer's 958 manually added words (every one a case of the
browser flagging a real word, the user looking it up, confirming it, and adding it) were run
against the *large* hunspell dictionary (about 77,000 roots, far bigger than what Brave
ships). It covered only 272. The other 678 were legitimate words both dictionaries missed.
At least 241 of those are common enough that even a crude 370,000 word list contains them.
The browser was simply wrong, hundreds of times.

freshspell builds the dictionary those words should have been in.

## How it works

Words come from Wiktionary (via the kaikki.org wiktextract export), which tracks real usage
and so includes the modern vocabulary SCOWL lags on. The pipeline:

1. `build_wordlist.py` downloads the kaikki English extract and produces two lists: `core`
   (about 900k words, lemmas plus inflected forms) and `names` (proper nouns, split out so
   they are an opt-in layer rather than masking typos in the core).
2. `bdic.py` serializes a word list into Chromium's binary `.bdic` format.
3. `install.py` installs it into the browser, fail-safe.

Entries Wiktionary marks as misspellings, eye dialect, or obsolete spellings are filtered out
so the dictionary does not bless errors.

## Quick start

```sh
./build.sh            # downloads Wiktionary, builds en-US-ems.bdic (about 9 MB, ~1M words)
python3 install.py    # installs into Brave, backing up the stock dictionary first
# restart Brave
```

Revert anytime:

```sh
python3 install.py --restore
```

The installer is idempotent. If the browser later re-downloads a stock dictionary after a
version bump, run `install.py` again to re-apply (it doubles as the repatch tool).

## Suggestions (recognition is only half the job)

A `.bdic` is two independent things: a word trie (*is this a word?*) and an **aff section**
(Hunspell's `TRY` string + `REP` table) that drives *correction suggestions*. A flat wordlist
gives an empty aff — words get recognized but the browser can't suggest a fix for a typo
(`intrests` never offers `interests`, because with no `TRY` string Hunspell generates no
candidates). `build.sh` therefore **carries the aff section forward from the browser's stock
dictionary** automatically (`bdic.py --aff-from`), so suggestions keep working.

A second, subtler issue: a *comprehensive* dictionary makes suggestions *worse*, because the
browser suggests corrections by mutating your typo and keeping mutations that are real words —
and with a million words, obscure entries (`hydroxypropiophenone`...) crowd out the obvious fix,
while some typos are themselves rare words and never flag. The fix is Hunspell's `NOSUGGEST`
flag: a word stays **recognized** but is never **offered** (stock browsers already do this for
profanity). `build_tiered.py` tiers the dictionary on word frequency:

```sh
python3 build_tiered.py --top-n 60000 --added my-custom-dictionary.txt
python3 install.py
```

Common words (top-N by `wordfreq`) plus your own `personal-words.txt` and any `--added` list stay
suggestable; the rare tail is recognized-but-NOSUGGEST. (Requires `pip install wordfreq`. The
NOSUGGEST flag-group is located dynamically in the carried-over aff, so it survives browser
version bumps.) **Ceiling:** Hunspell can't *rank* suggestions by frequency — that needs a
frequency-native engine (AOSP/keyboard dictionaries), not a browser speller — so tiering cleans
the candidate pool but can't reorder within it.

## bdic.py: a standalone Chromium .bdic reader and writer

There was no maintained pure-Python writer for Chromium's `.bdic` format. The only public
options were an unverified precompiled binary or building Chromium's `convert_dict` from
source. `bdic.py` is a dependency-free port of Chromium's `bdict_writer.cc`, with a matching
reader.

It is verified by round-tripping Brave's shipped dictionary byte for byte: read the real
`.bdic`, rebuild its trie, and the serialized output is identical to the original.

```sh
python3 bdic.py --validate /path/to/en-US-10-1.bdic   # round-trip proof
python3 bdic.py --build words.txt out.bdic            # one word per line (UTF-8)
```

## Personal supplement

A `personal-words.txt` in the repo root (one word per line) is appended to the build. Use it
for your own coinages and niche names that no general dictionary will ever carry.

## Licensing

The code in this repository is MIT (see `LICENSE`). Built dictionary artifacts are derived
from Wiktionary and are therefore CC-BY-SA 4.0, attributing Wiktionary. The repository ships
code only; you build the data, or download a release.

## Credits

Word data from [Wiktionary](https://www.wiktionary.org/) via
[kaikki.org](https://kaikki.org/) (wiktextract). Format ported from
[Chromium](https://source.chromium.org/) hunspell `bdict`. By Brandon M. Sergent.

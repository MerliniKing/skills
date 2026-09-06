#!/usr/bin/env python3
"""Write-side fidelity gate: verify that every quotation in a note file
actually exists in the book's OCR/text cache.

Write-side?  Existing checks verify you READ a page correctly (OCR vs image).
This one verifies you WROTE faithfully: each blockquote in the note must trace
back to ocr/full.txt. It catches (all real incidents):
  - quotes written from memory against a cache that lacks the passage
    (silently incomplete EPUB text layers)
  - transcription inversions / character swaps inside "verbatim" quotes
  - paraphrases accidentally wrapped in quotation marks

Usage:
  python3 tools/quote_check.py <ocr_full.txt> <note.md> [more.md ...]

Method: blockquote lines are split on punctuation into fragments (>=5 chars);
whitespace/stripped-control-char cache is searched for each fragment verbatim.
Interlinear notes: the cache may flatten the original's double-line small notes
inline (scan-to-archive pipelines, e.g. GLM 直读) — such notes are part of the
original text layer. Quote-side parentheses are dropped before matching, so a
quote whose middle carries a parenthesized note would break continuity against
a cache that still contains it. Fix (fs6-lesson-03, 52/52): each fragment is
sought in BOTH the raw cache and a paren-stripped copy of it.
A MISS is only a *suspect*, never a verdict: OCR noise, traditional/simplified
variants, edition variants and translated quotes (foreign-language books) all
miss legitimately. The gate's job is to force every miss to be *resolved* as
one of: (a) OCR/variant noise — checked and documented, (b) translation,
(c) marked ⚠unverified with the reason. Exit 1 if any miss remains, so it can
gate a commit.

Limitations: no fuzzy matching (deliberately — misses must be eyeballed);
inline (non-blockquote) quotes are not scanned; synthetic EPUB page numbering
means page citations are not checked, only text presence.
"""
import re
import sys
import pathlib

MIN_FRAG = 5
# common OCR/edition glyph pairs worth trying before declaring a miss
VARIANTS = {'入': '人', '微': '薇', '辨': '辯', '蚀': '食', '睺': '喉'}


def load_cache(path: str):
    """Return (raw_cache, paren_stripped_cache), both whitespace-free.

    The stripped copy lets quotes whose inline （…） was dropped (editorial or
    interlinear-note parens) stay contiguous against archives that flatten the
    original's double-line small notes into the text layer (fs6-lesson-03).
    """
    raw = pathlib.Path(path).read_bytes().decode('utf-8', errors='ignore')
    flat = re.sub(r'[\x00-\x08\x0b-\x1f\x7f\s]', '', raw)
    return flat, re.sub(r'（[^）]*）', '', flat)


def fragments(line: str):
    line = re.sub(r'^\s*>\s?', '', line)
    line = re.sub(r'[*_`]', '', line)
    line = re.sub(r'（[^）]*）', '', line)  # drop inline editorial parentheses
    parts = re.split(
        r'[……。；：、，！？“”「」『』《》\[\]()（）·—\-\s]', line)
    return [p for p in parts if len(p) >= MIN_FRAG]


def check_note(note_path: str, caches):
    suspects = []
    for i, line in enumerate(pathlib.Path(note_path).read_text(
            errors='ignore').splitlines(), 1):
        if not line.lstrip().startswith('>'):
            continue
        for frag in fragments(line):
            if any(frag in cache for cache in caches):
                continue
            if any(frag.replace(k, v) in cache
                   for cache in caches
                   for k, v in VARIANTS.items() if k in frag):
                continue
            suspects.append((i, frag))
    return suspects


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    caches = load_cache(sys.argv[1])
    total_miss = 0
    for note in sys.argv[2:]:
        if 'ocr' in pathlib.Path(note).parts:  # never scan the cache itself
            continue
        suspects = check_note(note, caches)
        name = pathlib.Path(note).name
        if suspects:
            for line_no, frag in suspects:
                print(f'  MISS {name}:L{line_no}  {frag}')
            total_miss += len(suspects)
        else:
            print(f'  OK   {name}')
    if total_miss:
        print(f'\n{total_miss} unresolved quotation fragment(s). Every MISS must be '
              'resolved as: OCR/variant noise (verified), translation, or '
              '⚠unverified-marked with reason. Do not commit unresolved.')
        sys.exit(1)
    print('\nAll quotations trace to the cache (or are documented variants).')


if __name__ == '__main__':
    main()

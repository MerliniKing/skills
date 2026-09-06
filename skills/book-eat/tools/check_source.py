#!/usr/bin/env python3
"""Source-completeness gate: catch silently incomplete text caches BEFORE
notes are written against them.

Incident class it guards (real): an EPUB whose «chapter N» page contained only
the heading — the chapter body never made it into full.txt. Every later note
quoting that chapter was unsourced, and nothing flagged it because
quality_report.txt is only generated on the OCR path.

Checks per ocr/full.txt:
  1. control/NUL bytes mixed into the text layer (breaks grep silently)
  2. heading-only pages: page markers whose body is <25 chars
     (front-matter and figure-only pages are expected; the report makes the
     judgment call explicit instead of silent)

Usage:
  python3 tools/check_source.py <book>/ocr/full.txt [more ...]
Exit 1 if anything needs a human decision.
"""
import re
import sys
import pathlib

PAGE_SPLIT = re.compile(r'===== (?:PDF|EPUB)第\d+页[^=]*=====')
THIN = 25


def check(path: str):
    raw = pathlib.Path(path).read_bytes()
    issues = []
    if b'\x00' in raw:
        issues.append(f'{raw.count(b"\x00")} NUL bytes in text layer — grep '
                      'treats the file as binary; re-extract or strip (never '
                      'rewrite by hand: regenerate from the source file)')
    text = raw.decode('utf-8', errors='ignore')
    pages = PAGE_SPLIT.split(text)[1:]
    thin = [(i, ' '.join(p.split())[:THIN])
            for i, p in enumerate(pages, 1) if 0 < len(p.strip()) < THIN]
    if thin:
        preview = '; '.join(f'p{i}«{t}»' for i, t in thin[:8])
        more = '' if len(thin) <= 8 else f' …(+{len(thin) - 8})'
        issues.append(f'{len(thin)} heading-only/thin page(s): {preview}{more} '
                      '— verify no chapter body is missing before writing notes')
    return issues


def main():
    any_issue = False
    for path in sys.argv[1:]:
        print(f'== {path}')
        issues = check(path)
        if issues:
            any_issue = True
            for it in issues:
                print(f'  ⚠ {it}')
        else:
            print('  source cache looks complete')
    if any_issue:
        sys.exit(1)


if __name__ == '__main__':
    main()

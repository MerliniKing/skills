# book-eat

**Your AI eats the book. You learn from the digest.**

Most "read with AI" skills are reading *coaches* — they quiz you while you read the chapters yourself. book-eat inverts that: the agent reads the entire book (PDF or EPUB, scanned or text-layer) and builds you a permanent, page-cited knowledge base. You grasp the book through layered notes, and go back to the original only when you need to verify.

## What it does

A six-step pipeline, resumable at any point (reentrant state machine — drop in mid-book, it picks up from the breakpoint):

1. **Full-text cache** — text-layer PDFs/EPUBs extracted in seconds; scanned PDFs go through local OCR (RapidOCR, ~8 s/page). Produces per-page files, a `full.txt` with stable page markers, a TOC map, and an OCR quality report. *Nothing is sent to external services.*
2. **Outline + tiering** — the agent skims the whole book and proposes a chapter tiering table (deep-read core / summarize / skip), then **stops and waits for your confirmation**. Tiering is an editorial decision; wrong tiering = wasted work, so the gate is non-negotiable.
3. **Tiered close reading** — deep notes and summaries, every claim cited to book+page or book+chapter.
4. **Archiving** — topic notes, glossary backfill, ⚠unverified knowledge upgraded once book evidence arrives.
5. **Review cards** — Q/A cards with source, difficulty 1–5, and status.
6. **Kanban** — progress board updated every phase.

**Quality gate**: quotations, dates, names, editions, tables and plates get verified against the original page image (via an image-capable tool when available; otherwise emitted as a ⚠ needs-human-review list — never silently skipped).

**Audit trail**: the OCR cache is an immutable raw layer. Corrections only ever land in note layers, so every claim can be traced back to machine output.

## Install

```bash
npx skills add MerliniKing/book-eat@book-eat
```

Requirements: Python 3 with `pymupdf` (all books) and `rapidocr-onnxruntime` (scanned PDFs only). The skill auto-installs them if missing.

## Quickstart

```bash
mkdir my-library && cd my-library && git init
mkdir sources && cp /path/to/your-book.pdf sources/
```

Then tell your agent: **"eat this book"** (吃这本书). The skill bootstraps the library layout (sources/, books/, cards/, topics/, INDEX.md) on first run, caches the text, and stops at the outline confirmation gate.

## Why not just ask the model to summarize?

One-shot summaries flatten a book into a single take with no citations and no way back to the source. book-eat gives you **layers**: summaries to grasp the structure fast, deep notes to master the core, and the full-text cache to settle any dispute with the original page. It's how you'd want a research assistant to actually read a book for you — with receipts.

## Layout

```
skills/book-eat/
├── SKILL.md           # canonical (English)
├── SKILL.zh.md        # Chinese mirror
├── tools/run_ocr.py   # PDF/EPUB caching pipeline (text-layer or OCR)
└── scaffold/          # library bootstrap templates
```

## License

MIT

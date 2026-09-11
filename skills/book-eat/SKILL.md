---
name: book-eat
description: "Deep-digest a book into a permanent, page-cited knowledge base — text is taken from the source directly whenever present (text layer / structural unpack); vision reading is the fallback for scanned pages; every page is archived (figure/table presence + bbox + full text) (figure/table presence + bbox + full text). every page is distilled by AI (no skipping, no outline gate), topic archiving, glossary building, spaced-repetition review cards, figure harvesting driven by the archive's bboxes, and a resumable state machine. Use when the user says 'eat this book' / 'process this book', drops a new PDF/EPUB into sources/, asks to resume or check a book's processing status, or wants structured book notes built."
---

# Book Eat v2 · extraction-first pipeline (2026-08-28)

Extraction first: the text comes from the source directly (text layer, structural
unpack) whenever present; vision reading is reserved for scanned pages and for figure/table
judgment. The per-page archive produced by `tools/book_parse.py` (canonical PROMPT embedded —
prompt changes require user sign-off) is the truth for what each page contains. (`tools/book_parse.py`, canonical PROMPT embedded — prompt
changes require user sign-off). Nothing else is a completeness witness.

## Library layout

```
book-content/
  topics/                  CROSS-DOMAIN shared glossary (术语库.md; 2026-09-07 domain split)
  <domain>/                domain = lowercase pinyin slug (xuanxue, zhongyi, …); one per domain:
    books/<book>/
    book-parse/              TRUTH SOURCE (per-page / per-chapter archive)
      pages.jsonl            PDF: {page, book_page, is_toc, toc, has_figure, has_table, regions, text}
                             regions: [y0,y1,type]（2026-08-31 起：左右无环绕正文时上下两界简写，crop 取整页宽）
                                      或 [x0,y0,x1,y1,type]（左右有环绕正文时的全四坐标；旧档案均为四坐标，crop 双兼容）
      verify/                10% sampled crop verification: samples.json + sample-report.jsonl (+ temporary page renders, gitignored)
      chapters.jsonl         chapter table: {title, print_page, pdf_page, end_pdf_page, verified}
      media/                 EPUB embedded media (extracted, unregistered until harvest)
    img/                     cropped figures actually harvested (+ 图录.json manifest)
    <domain>-<slug>-chapter-<NN>-<标题>.md   chapter page (publish unit; lid = full file stem)
    精读-*.md 摘要-*.md README.md 学习进度.md
site/
  build_html.py · publish_web.sh · home/ · theme/ · assets/
  dist/                       generated site (gitignored in the private repo)
tools/                       book_parse etc.
sources/                     book files (PDF/EPUB) — local only, gitignored
```

Publish resolves each `src="img/…"` in a chapter page directly from
`book-content/<domain>/books/<book>/img/`; a missing file blocks publish (that is a guard, not a bug).
Published tree (2026-09-07): root `/` = cross-domain React shelf + kanban/roadmap/glossary +
progress.json + home-data.json; domain content under `/books/<domain>/<bookslug>/`
(`<domain>-<slug>-chapter-<NN>.html`, `<domain>-<slug>-book.html`, per-book `img/`;
domain card page `/books/<domain>/<domain>-cards.html`). Old flat `/xuanxue/` URLs retired (404).

## Tools

`tools/book_parse.py` — render / prompts / merge / chapters / crop / distill / timing (canonical)

Tool status (do NOT resurrect without user sign-off):

| tool | status |
|---|---|
| book_parse.py | **current** — parse + harvest pipeline |
| pages_probe.py | optional pre-filter only; never a completeness witness |
| extract_figures.py | legacy (private library); superseded by `book_parse crop` |
| run_ocr.py · quote_check.py · check_source.py | **retired** with OCR (2026-08-28) |
| fig_coverage_lint.py · audit_library.py | chapter-glob updated to the multi-domain layout; ocr-fed appendix probe inert post-purge (kept for history) |

Private-library layout note: the pipeline lives under `book-content/<domain>/books/<book>`
(generators under `site/`); run book_parse from the repository root so relative paths resolve.

## Stage × tool map

| stage | tool / command | output |
|---|---|---|
| ① parse · render | `book_parse render <book> [--pdf src]`（EPUB 自动走结构化分支） | page renders / `chapters.jsonl` + `media/` |
| ① parse · vision read | `book_parse prompts <book>` prints shard briefs（**20 页/片**，2026-09-11 定案——缩小单 agent 上下文的污染半径）→ spawn one Read-only agent per shard (**max 2 concurrent** — user-set 2026-08-31; gateway hard-caps ≈4 with account-level 429 at 5+)；**安全审核风暴 → 隔离派发 runbook（见下）** | shard JSONL files, appended per page with `ts` (never chat-only, never batch-at-end); 卡页记 `# stuck` 行 |
| ① parse · crop | `book_parse crop <book> --round A --dir <shards>`（merge 之前；regions → `book-parse/imgs/`，幂等） | per-page figure/table crops |
| ① parse · verify | `book_parse sample <book>`（10% 随机抽裁图 → 渲染 300dpi 原页 → 打印抽检派工；agent 回填报告后 `sample --check` 验收，非 pass＝exit 1。**2026-08-31 起替代逐张目验**） | `book-parse/verify/{samples.json,sample-report.jsonl}` |
| ① parse · merge | `book_parse merge <book> --round A --dir <shards>`（自动附章节解析） | `book-parse/pages.jsonl` + `chapters.jsonl` + `chapters/<章>/`（原文聚合＋图表 md 引用） |
| ② distill | `book_parse distill <book>` prints per-chapter briefs → agents write 精读 notes | 精读/chapter-<NN>-*.md（每页必有提炼，无跳过） |
| ③–⑤ write & archive | 章节页写作（基于精读与档案）；卡片 | chapter pages / cards |
| ⑥ build & publish | `site/build_html.py` → `site/publish_web.sh`（missing figure = fail） | live site, then proxy-verify 200 |
| audit (aux) | `pages_probe.py` pre-filter · overlay eyeball | flagged pages only |

## Step 0 · State detection (every invocation)

| book-content/<domain>/books/<book>/book-parse/ | book-content/<domain>/books/<book>/<lid>-<标题>.md | state |
|---|---|---|
| absent | absent | fresh → ① |
| present | absent | parsed → ② outline gate |
| present | present | reading/publishing → ③–⑥ |
| partially filled | any | interrupted merge → `book_parse merge` to resume |

## ① Parse (full-book archive) — extraction first, vision fallback

| source | text | figure/table |
|---|---|---|
| **Native PDF** (text layer) | extract from the text layer directly | render pages → visual pass judges presence & bboxes |
| **Scanned PDF** (no text layer) | vision transcription IS the text source | same visual pass |
| **EPUB** | structural unpack: spine XHTML → chapter text | embedded media extracted whole to `book-parse/media/` (chapter-anchored, no page semantics) |

- Scanned path: `book_parse render` (serial, dpi100) → `book_parse prompts` prints per-shard
  agent briefs → one Read-only agent per shard (presence + bbox + full text) → `merge`
  (validates continuity/fields). Concurrency = 2 (user-set 2026-08-31, down from gateway
  cap ≈4, to cut 429s and agent deaths). Vision agents append each page line (with `"ts"`
  unix-stamp) to the shard file immediately and never re-paste JSONL in their final reply —
  a death then loses at most one page, and the file tail is the resume point.
- `book_parse timing <book>` aggregates per-stage timing (`book-parse/timing/report.json`):
  render/crop per-page measured; 直读 from shard `ts` diffs; 精读 from note t0/t1 stamps.
  Archives parsed before 2026-08-31 carry no timing data.
- Acceptance: merge reports continuity; crop quality is verified by `sample` — a random
  10% (≥3) of crops are checked against 300dpi originals with report-style prompts
  (what's inside / edges cut / annex text), never yes/no questions; `sample --check`
  gates on missing or non-pass verdicts. (2026-08-31 user decision, superseding
  per-crop eyeballing; the p332-class lesson stands: third-party vision stays pre-screen
  only, direct Read of full-resolution pages is the acceptor.)

### 直读安全审核风暴 · 隔离派发（2026-09-11 定案，星命溯源 b 片实证）

某页图触发 GLM API 安全审核后，该图留在分片 agent 的会话历史里，后续每个请求都背着
全部历史图反复被拦——星命溯源 b 片（45 页）从每页 3 分钟恶化到 36 分钟、9 小时才爬完；
并发跑的干净 agent 同等内容 3 小时收工。**污染在上下文，不在内容**：同一页换干净会话
通常一次过。处置原则＝卡页隔离、原会话废弃、余页换新：

- **判定**（任一即成立）：① shard 文件出现 `# stuck <页号> <unix秒>` 行（PROMPT 停损
  铁律自报）；② 主会话盯盘：shard 文件最新页行落盘后 >8 分钟无后页而 agent 仍在跑
  （正常页 0.5–3 分钟，参照 `book_parse timing` 直读段）。
- **处置**（顺序执行）：
  1. **废弃原 agent**——TaskStop 杀掉，永不复用：上下文已被卡页图污染，留它越跑越慢。
  2. **卡页派单页专责 agent**——干净上下文只读这一页；brief＝`book_parse prompts`
     重取的正典逐页规则、范围钉死到该单页；仍追加写同一 shard 文件（merge 按页号
     排序归一，交错无害）。
  3. **余页派新 agent**——从文件内第一个未交付页到本片末页，同文件追加；并发守 ≤2，
     超出排队。
  4. 单页专责 agent 仍卡：换新 agent 再试一次（防偶发）；再卡＝**登记隔离**（页号＋
     现象记入该书 README 源状况节），报告用户人工复核页面图（复核-安全审核-*/ 目录
     模式）。merge 对缺页 exit 1 是故意的——档案完整性 loud fail，不许无源补线。
- **风暴史回溯**：shard `ts` 差值＋`# stuck` 行即完整现场（timing 直读段呈尖峰）。

## ② Distill — every page, no skipping

The user has not read the book; tier/skip decisions are not theirs to make. Distillation
covers EVERY page: per chapter, write 精读 notes from chapter.md (verbatim quotes only,
术语首现必释, each page ≥1 提炼, figure refs kept with one-line readings). Output to
精读/chapter-<NN>-*.md.

## ③④⑤ Chapter pages → archiving → cards

- Write 章节页 (chapter pages) from the 精读 notes; every quotation is copied from the
  book-parse archive text. If it is not in the archive, it may not be quoted — mark ⚠未验证.
- Figures were cropped pre-merge (book-parse/imgs/); chapter pages reference them via
  the assembled links. A missing file blocks publish (strong linkage check).
- Cards to cards/*.md with source + difficulty + review ladder.

## ⑥ Kanban & publish

学习进度.md is the progress ledger (read-marker harvest from CF KV via mihomo proxy
127.0.0.1:7890). Publish via publish_web.sh; verify through the proxy afterwards
(mandatory global rule): expect HTTP 200 on changed URLs after the Workers build window.

## Hard rules

- Extraction first, vision fallback (rule 1). No OCR tools anywhere; OCR history stays deleted.
- One canonical PROMPT (inside book_parse.py). No A/B/C prompt rounds; no pixel-probe
  completeness claims. The archive is the only presence witness.
- Absence claims ("no figures", "fully covered") are forbidden in notes — state what was
  parsed and where, and let the archive speak.
- Decorative ornaments (page-tail flourishes, seals) are not figures.

## Red Flags (stop and self-check)

- "I remember this passage" — quoting from memory instead of the archive (P0 class).
- Announcing harvest completeness without the archive diff.
- Third-party vision tools as final acceptors (they misjudge; direct Read is the acceptor).
- Sharded agents delivering to chat only, or batching all pages into one end-of-run
  Write (death-prone; the canonical PROMPT requires per-page append + `ts` stamp).
- EPUB media treated as page-anchored (it has no page semantics).
- A shard agent grinding tens of minutes per page on moderation/safety-review retries —
  that is context poisoning, not hard pages. Stop-loss (`# stuck`), abandon the agent,
  isolate the page to a clean single-page agent (storm runbook above). Never let it ride.

## Maintenance

PROMPT / pipeline changes require user confirmation; truth source is the private repo
`~/code/my-skills/skills/book-eat` (library `.claude/skills/book-eat` symlinks into it).
The open repo (github.com/MerliniKing/book-eat) is retired, no sync (2026-09-07 定案).
Legacy OCR-era artifacts were purged 2026-08-28 (recoverable at git 34e6842^ if ever needed).

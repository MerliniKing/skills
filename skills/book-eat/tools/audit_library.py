#!/usr/bin/env python3
r"""库级内容审核统一入口 —— 一条命令跑全部机械门，产出 triage 用报告。

背景：2026-08 对抗审计暴露的门禁各自为政（引文回溯／源完整性／图版覆盖／
卡片覆盖分散在规则文字与多个脚本里），导致「每层都查了、没一层查全」。
本工具把四类检查串成一次运行＋一份报告：

  [源完整性]  逐书 tools/check_source.py（NUL 污染＋标题页空洞）
  [引文回溯]  精读/摘要/课页/deep/summary 笔记逐文件回对本书缓存；
              卡片逐文件回对**全部书缓存**（卡片跨书引用，任一命中即 OK，
              全部未命中才是 suspect）
  [图版覆盖]  提图零嵌图 SUSPECT ＋ 书级附录区尾页探测（fig_coverage_lint 同逻辑）
  [卡片覆盖]  有精读笔记的书 ↔ 卡片文件 松匹配（文件名或来源头行含书名 token）；
              未匹配者列为需人工裁决（豁免须成文）

MISS 是嫌疑不是判决——报告只负责把嫌疑收拢，逐条归因（OCR 噪声已开页核对 /
译引已对原文 / ⚠未验证＋原因）仍由人完成。--strict 用于发布门：存在未处置
suspect 时 exit 1。

用法（在库根目录）：python3 tools/audit_library.py [--out 报告.md] [--strict]
默认报告写 /tmp/audit-library-<时间戳>.md；console 出各节摘要与 top 未命中清单。
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_source as cs          # noqa: E402
import fig_coverage_lint as fcl    # noqa: E402
import quote_check as qc           # noqa: E402

NOTE_PATS = ['books/*/精读-*.md', 'books/*/摘要-*.md',
             'books/*/deep-*.md', 'books/*/summary-*.md', 'books/*/lesson-*.md']
BOOK_PREFIXES = ('今-', '古-', '唐-', '宋-', '明-', '清-', '汉-', '隋-', '晋-', '民国-')


def note_files():
    seen, out = set(), []
    for pat in NOTE_PATS:
        for p in sorted(glob.glob(pat)):
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out


def book_tokens(book):
    parts = [p for p in re.split(r'-', book) if p]
    return {p for i, p in enumerate(parts) if not (i == 0 and p in BOOK_PREFIXES)} | \
           {''.join(parts[1:])} if len(parts) > 1 else set(parts)


def run(out_path=None):
    # 书名=路径第二段（basename 会把 'books/书/ocr' 的 ocr 当书名——见 fs1-04 残留教训）
    books = sorted(p.split('/')[1] for p in glob.glob('books/*/ocr/full.txt'))
    caches, norm_caches = {}, {}
    lines = ['# 库级机检报告\n']
    n_src_issues = 0

    # ── 1 源完整性 ────────────────────────────────────────────────
    print('== [1] 源完整性')
    lines.append('\n## 一、源完整性\n')
    for b in books:
        issues = cs.check(os.path.join('books', b, 'ocr', 'full.txt'))
        caches[b] = None            # 延迟加载
        if issues:
            n_src_issues += len(issues)
            print('  ⚠ {}: {}'.format(b, '; '.join(issues)))
            lines.append('- **{}**: {}'.format(b, '; '.join(issues)))
    if n_src_issues == 0:
        print('  全部通过')
        lines.append('全部通过。\n')

    # ── 2 引文回溯 ────────────────────────────────────────────────
    def cache_of(book):
        if caches[book] is None:
            raw = open(os.path.join('books', book, 'ocr', 'full.txt'),
                       errors='ignore').read()
            caches[book] = raw
            norm_caches[book] = qc.load_cache(os.path.join('books', book,
                                                           'ocr', 'full.txt'))
        return norm_caches[book]

    def card_header(path):
        first_gt = next((l.lstrip('> ').strip() for l in
                         open(path, errors='ignore').read().splitlines()
                         if l.startswith('>')), '')
        return os.path.basename(path) + ' ' + first_gt

    rows = []
    print('== [2] 引文回溯（笔记→本书缓存；卡片→全书缓存任一命中即过）')
    lines.append('\n## 二、引文回溯\n')
    files = [(p, True) for p in note_files()] + \
            [(p, False) for p in sorted(glob.glob('cards/*.md'))]
    for path, per_book in files:
        book = path.replace('\\', os.sep).split(os.sep)[1]
        targets = [book] if per_book else books
        frag_total, misses = 0, []
        for i, line in enumerate(open(path, errors='ignore'), 1):
            if not line.lstrip().startswith('>'):
                continue
            frags = qc.fragments(line)
            if not frags:
                continue
            frag_total += len(frags)
            for f in frags:
                okf = f in cache_of(targets[0]) or any(
                    f.replace(k, v) in cache_of(targets[0])
                    for k, v in qc.VARIANTS.items() if k in f)
                if not okf and not per_book:
                    okf = any(f in cache_of(b) for b in targets[1:])
                if not okf:
                    misses.append((i, f))
        if frag_total:
            rows.append((path, frag_total, len(misses), misses))

    rows.sort(key=lambda r: -r[2])
    grand_t = sum(r[1] for r in rows)
    grand_m = sum(r[2] for r in rows)
    print('  文件 {} · 片段 {} · 工具未命中 {} ({:.1%})'.format(
        len(rows), grand_t, grand_m, grand_m / max(grand_t, 1)))
    lines.append('| 文件 | 片段 | 未命中 | 率 |')
    lines.append('|---|---|---|---|')
    for path, t, m, _ in rows:
        flag = ' **' if m * 20 > t and t > 10 else (' ' if m == 0 else ' ')
        mark = '⚠高' if flag.strip() else ''
        lines.append('|{} {} | {} | {} | {:.0%} {}|'.format(
            flag, path, t, m, m / max(t, 1), mark))
    print('  （明细见报告：每文件 MISS 片段带行号）')

    # 明细附录（top 25 文件 × 前 60 条）
    lines.append('\n### MISS 明细（前 25 个最差文件）\n')
    for path, t, m, misses in rows[:25]:
        if not m:
            continue
        lines.append('\n**{}**（{}/{}）'.format(path, m, t))
        for i, f in misses[:60]:
            lines.append('- L{} `{}`'.format(i, f))
        if len(misses) > 60:
            lines.append('- …其余 {} 条见重跑'.format(len(misses) - 60))

    # ── 3 图版覆盖 ────────────────────────────────────────────────
    print('== [3] 图版覆盖')
    lines.append('\n## 三、图版覆盖\n')
    suspects = []
    seen = set()
    for pat in fcl.NOTE_GLOBS:
        for p in sorted(glob.glob(pat)):
            if p in seen:
                continue
            seen.add(p)
            talks = fcl.lesson_lint(p)
            if talks:
                suspects.append((p, talks[:4]))
    appx = []
    for b in books:
        h = fcl.book_appendix_probe(b)
        if h:
            appx.append((b, h))
    for p, t in suspects:
        print('  SUSPECT {} ← {}'.format(p, t))
        lines.append('- SUSPECT: {} ← {}'.format(p, t))
    for b, pages in appx:
        print('  尾区待抽检 {} ← 页 {}'.format(b, pages))
        lines.append('- 尾区待抽检: {} ← 页 {}'.format(b, pages))
    if not suspects and not appx:
        print('  通过')
        lines.append('通过。\n')

    # ── 4 卡片覆盖 ────────────────────────────────────────────────
    print('== [4] 卡片覆盖（松匹配，信息级）')
    lines.append('\n## 四、卡片覆盖（松匹配，信息级）\n')
    card_texts = {p: card_header(p) for p in glob.glob('cards/*.md')}
    uncovered = []
    for b in books:
        if not glob.glob(os.path.join('books', b, '精读-*.md')):
            continue
        toks = book_tokens(b)
        if any(any(tok in txt for tok in toks) for txt in card_texts.values()):
            continue
        uncovered.append(b)
        print('  需裁决: {}（无卡文件名/来源头行命中其名）'.format(b))
        lines.append('- 需人工裁决: {}'.format(b))
    if not uncovered:
        print('  全部有精读的书都能对到卡片')
        lines.append('全部有精读的书都能对到卡片（松匹配；卡片散装于合集文件的以来源头行为准）。\n')

    # ── 写报告 ────────────────────────────────────────────────────
    import time
    out_path = out_path or '/tmp/audit-library-{}.md'.format(
        time.strftime('%Y%m%d-%H%M%S'))
    open(out_path, 'w').write('\n'.join(lines) + '\n')
    print('\n报告 → {}'.format(out_path))
    return n_src_issues, grand_m, len(suspects) + len(appx), len(uncovered)


def main():
    args = sys.argv[1:]
    out = args[args.index('--out') + 1] if '--out' in args else None
    strict = '--strict' in args
    n_src, n_miss, n_fig, n_card = run(out)
    findings = bool(n_src or n_miss or n_fig)
    if strict and findings:
        print('strict: 存在未处置项（源 {} / 引文未命中 {} / 图版 {}），exit 1'
              .format(n_src, n_miss, n_fig))
        sys.exit(1)
    if strict and n_card:
        print('strict: 卡片覆盖有 {} 本需人工裁决（信息级，不拦 exit）'.format(n_card))


if __name__ == '__main__':
    main()

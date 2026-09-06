#!/usr/bin/env python3
r"""课页/笔记图版覆盖 linter —— 防「提图不嵌图」类持续漏检（fs1-04 第四案后立）。

事故链（真实，四层审查全部放行）：讲义通篇数图（「外形132图／门前64图」）却
零嵌图；「全覆盖」结论靠 图N题注连续性＋章节页码窗整页扫描 得出——而图版实际
住在附录、挂的是表内编号（表号 26/701 而非图N），在章节窗之外；嵌图引用的
存在性检查在引用数为 0 时恒过（存在性≠覆盖性）。

本 linter 的触发器是**语义信号**而非句式：凡笔记文本含图版指涉
（`\d+图｜见图｜图版｜图样｜图诀｜插图`）而该文件嵌图为 0 → SUSPECT。
SUSPECT 不是判决：源书确无图版的文件属合法，但豁免必须带人工确认注记
（须含「已核」，如「源无图版·已核」）——缺席性结论不得无条件冻结。

另附书级附录探测：OCR 尾区（末 25% 页）出现 图样/吉凶表/附图/图解 词汇
而该书图录无尾区条目 → 列「附录区待视觉抽检」清单。

用法：python3 tools/fig_coverage_lint.py            # 全库（在库根目录跑）
      python3 tools/fig_coverage_lint.py <书目录名>  # 单书
exit 1 = 有 SUSPECT 待处理（或待加确认注记）。
"""
import glob
import json
import os
import re
import sys

NOTE_GLOBS = [
    'books/*/lesson-*.md', 'books/*/*/lesson-*.md',
    'books/*/精读-*.md', 'books/*/摘要-*.md',
    'books/*/deep-*.md', 'books/*/summary-*.md',
]
FIG_TALK = re.compile(r'\d+\s*[图圖]|见图|見圖|图版|圖版|图样|圖樣|图诀|圖訣|插图|插圖')
IMG = re.compile(r'!\[[^\]]*\]\((?:img/|\.\./img/)[^)]+\)')
NOTE_OK = re.compile(r'已核')          # 豁免必须带人工确认字样
XREF = re.compile(r'[A-Za-z]{2}\d+(?:-\d+)?[^。；\n]{0,12}?[图圖]')  # 跨课引用（fs6-01 图版）
APPENDIX_WORDS = re.compile(r'图样|圖樣|吉凶表|附图|附圖|图解|圖解')


def lesson_lint(path):
    text = open(path, errors='ignore').read()
    if IMG.findall(text):
        return None
    text = XREF.sub('', text)          # 剥跨文件图指涉
    talks = FIG_TALK.findall(text)
    if not talks or NOTE_OK.search(text):
        return None
    return talks


def book_appendix_probe(book):
    """OCR 尾区含图样类词汇而图录无尾区条目 → 待抽检。"""
    ocr = os.path.join('books', book, 'ocr', 'full.txt')
    man = os.path.join('books', book, 'img', '图录.json')
    if not os.path.exists(ocr) or not os.path.exists(man):
        return None
    pages = re.split(r'=====\s*(?:PDF|EPUB)第(\d+)页[^=]*=====',
                     open(ocr, errors='ignore').read())
    if len(pages) < 3:
        return None
    nums = [int(pages[i]) for i in range(1, len(pages), 2)]
    bodies = [pages[i] for i in range(2, len(pages), 2)]
    if not nums:
        return None
    tail_from = max(nums) * 0.75
    hits = [n for n, b in zip(nums, bodies)
            if n >= tail_from and APPENDIX_WORDS.search(b)]
    if not hits:
        return None
    figs = json.load(open(man))
    if not figs:
        return hits[:5]
    if all(f.get('page') == 0 and 'epub' in str(f.get('pdf', '')).lower()
           for f in figs):
        return None                     # EPUB 全媒体收割：内嵌插图整包落库，无页码语义，尾区探测不适用
    if any(isinstance(f.get('page'), int) and f['page'] >= tail_from for f in figs):
        return None                     # 尾区已有收割条目
    return hits[:5]


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    suspects = []
    seen = set()
    for pat in NOTE_GLOBS:
        for path in sorted(glob.glob(pat)):
            if path in seen:
                continue
            seen.add(path)
            book = path.replace('\\', os.sep).split(os.sep)[1]
            if only and only != book:
                continue
            talks = lesson_lint(path)
            if talks:
                suspects.append((path, talks[:4]))
    appx = []
    # 书名=路径第二段（basename 会取到 'ocr'——books/<书>/ocr/full.txt）
    books = [p.split('/')[1] for p in glob.glob('books/*/ocr/full.txt')]
    for book in sorted(books):
        if only and only != book:
            continue
        h = book_appendix_probe(book)
        if h:
            appx.append((book, h))
    print('== SUSPECT（提图零嵌图：需补嵌，或经人核后加「…无图版·已核」注记）')
    print('  （无）' if not suspects else '')
    for p, t in suspects:
        print('  {} ← {}'.format(p, t))
    print('== 附录区待视觉抽检（OCR 尾区有图样词而图录无尾区条目）')
    print('  （无）' if not appx else '')
    for b, pages in appx:
        print('  {} ← OCR 尾区命中页 {}'.format(b, pages))
    if suspects or appx:
        sys.exit(1)


if __name__ == '__main__':
    main()

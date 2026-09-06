#!/usr/bin/env python3
"""书籍全文缓存流水线：PDF / EPUB 统一处理
文字层检测 → 直抽（秒级） 或 RapidOCR 逐页识别 → 逐页txt + full.txt + toc.txt + 质量报告

用法：
  python3 tools/run_ocr.py <书名> <书路径：.pdf 或 .epub> [--force-ocr] [--pages A-B]
  示例：python3 tools/run_ocr.py 我的书名 sources/我的书.pdf
        python3 tools/run_ocr.py 合刊中的一本 "books/某合集/某书.pdf" --force-ocr --pages 244-284

可选参数：
  --force-ocr      跳过文字层检测，强制走 RapidOCR（内嵌文本层是旧OCR垃圾、直抽不可读时用；
                   注意断点续跑按 pages/pNNN.txt 是否存在判断，改走 OCR 前先删掉直抽产物）
  --pages A-B      只处理 1 基闭区间 [A,B] 的页（合刊 PDF 只吃其中一书时用）；
                   页标记与 pNNN.txt 仍用原 PDF 物理页码，引用不漂移；未处理页在 full.txt 中留空占位
  --vertical       竖排（古籍）阅读顺序：按 x 中心聚"列"，列从右到左（x 降序），列内从上到下；
                   默认横排顺序（y 聚行、行内 x 升序）。仅影响 OCR 路径的行序，不改识别本身

格式与页标记（full.txt / pages/ 的引用单位）：
  .pdf  → ===== PDF第N页 =====                    （N = PDF 物理页码）
  .epub → ===== EPUB第N页 · 章节名 =====           （N = pymupdf 合成页码，每本固定可复现；
           章节名取自 EPUB 目录（TOC），无目录或页在首章前则省略 · 章节 部分）
  笔记引用两者皆可：书+页（合成页可复现）或 书+章节。
  其他格式（.mobi/.azw3/.djvu…）不支持：先转 epub/pdf 再入库。

文字层检测：抽样前10页，内嵌文本非空页过半 → 直接抽取（秒级完成）；
否则走 RapidOCR 逐页识别（约8秒/页）。

大书建议分块跑（后台任务约10分钟会被系统终止；断点续跑自动跳过已完成页）：
  timeout 480 python3 tools/run_ocr.py <书名> <源文件>   # 重复执行直到输出 DONE

产物（books/<书名>/ocr/）：
  pages/pNNN.txt          逐页文本
  full.txt                全文合并（带页标记，EPUB 带章节名）
  toc.txt                 目录（章节→起始页，供②定纲直接用；无目录的书不产生）
  quality_report.txt      低置信页清单（仅OCR路径产生；直抽路径无此文件）
                          —— 这些页是"需要视觉复核"的候选页
"""
import sys, os, re, time
import pymupdf

BOOK = sys.argv[1] if len(sys.argv) > 1 else ''
SRC = sys.argv[2] if len(sys.argv) > 2 else ''
if not BOOK or not SRC or not os.path.exists(SRC):
    sys.exit(__doc__)

# 可选参数（第3位起）：--force-ocr / --pages A-B（或 --pages=A-B）/ --vertical
FORCE_OCR = False
RANGE = None
VERTICAL = False
_i = 3
while _i < len(sys.argv):
    _a = sys.argv[_i]
    if _a == '--force-ocr':
        FORCE_OCR = True
    elif _a == '--vertical':
        VERTICAL = True
    elif _a == '--pages' or _a.startswith('--pages='):
        _v = _a.split('=', 1)[1] if '=' in _a else (sys.argv[_i + 1] if _i + 1 < len(sys.argv) else '')
        _m = re.fullmatch(r'(\d+)-(\d+)', _v.strip())
        if not _m:
            sys.exit('--pages 用法：--pages 244-284 或 --pages=244-284（1基闭区间）')
        RANGE = (int(_m.group(1)), int(_m.group(2)))
        if '=' not in _a:
            _i += 1
    _i += 1

ext = os.path.splitext(SRC)[1].lower()
FT = {'.pdf': 'pdf', '.epub': 'epub'}.get(ext)
if FT is None:
    sys.exit(f'[不支持] {ext or SRC}：目前支持 .pdf / .epub。\n'
             f'  mobi/azw3 → 先转 epub（calibre：ebook-convert 书.azw3 书.epub）；djvu/其他 → 转 PDF。')

# 压掉 MuPDF 对 EPUB 内嵌 CSS 的海量无害告警（版本差异，能力可选）
try:
    pymupdf.TOOLS.mupdf_display_errors(False)
except AttributeError:
    pass

OUT = f'books/{BOOK}/ocr'
PAGES_DIR = f'{OUT}/pages'
LOW_CONF = 0.8   # 低于此置信度的文本行记入质量报告
os.makedirs(PAGES_DIR, exist_ok=True)

doc = pymupdf.open(SRC) if FT == 'pdf' else pymupdf.open(SRC, filetype='epub')
total = len(doc)

# 待处理页（0基索引）：--pages A-B 截取，页标记/文件名仍按原物理页码
todo = list(range(max(0, RANGE[0] - 1), min(total, RANGE[1]))) if RANGE else list(range(total))
if not todo:
    sys.exit(f'[不支持] --pages {RANGE[0]}-{RANGE[1]} 超出本书页码范围 1-{total}')
rng_note = f'（--pages {RANGE[0]}-{RANGE[1]}，仅此区间）' if RANGE else ''

# ---------- 目录（章节→起始页）：页标记与 toc.txt 的数据源 ----------
def clean_title(t):
    t = re.sub(r'\s+', ' ', t).strip()
    return t[:40] + ('…' if len(t) > 40 else '')

toc = []
try:
    raw_toc = doc.get_toc()
except Exception:
    raw_toc = []
for lvl, title, pg in raw_toc:
    t = clean_title(title)
    if t:
        toc.append((lvl, t, pg))

# 垃圾目录识别：书签大量重复同一标题（如全是"Blank Page"）不是真章节结构，
# 保留会让页标记与笔记引用挂上误导性章节名 → 整体弃用
if len(toc) > 1:
    from collections import Counter
    if Counter(t for _, t, _ in toc).most_common(1)[0][1] > len(toc) / 3:
        toc = []

if toc:
    with open(f'{OUT}/toc.txt', 'w') as f:
        for lvl, t, pg in toc:
            f.write(f'{"  " * (lvl - 1)}- {t}  （{FT.upper()}第{pg}页起）\n')

# 页 → 当前章节名（起始页<=N 的最后一条目录项；线性扫描一次性预计算）
chapter = [''] * (total + 1)
cur = ''
ti = 0
for i in range(1, total + 1):
    while ti < len(toc) and toc[ti][2] <= i:
        cur = toc[ti][1]
        ti += 1
    chapter[i] = cur

def page_marker(i):
    m = f'===== {FT.upper()}第{i}页'
    if chapter[i]:
        m += f' · {chapter[i]}'
    return m + ' ====='

def read_page_txt(n):
    # --pages 模式下未处理页无 pNNN.txt，合并时留空占位（页标记仍在，引用位置可寻）
    p = f'{PAGES_DIR}/p{n:03d}.txt'
    if not os.path.exists(p):
        return ''
    with open(p) as f:
        return f.read()

# ---------- 文字层检测 ----------
sample = min(10, total)
text_pages = sum(1 for i in range(sample) if doc[i].get_text().strip())
HAS_TEXT_LAYER = text_pages > sample // 2

if HAS_TEXT_LAYER and not FORCE_OCR:
    # 直抽路径：内嵌文本层逐页抽取，秒级完成
    for i in todo:
        page_txt = f'{PAGES_DIR}/p{i+1:03d}.txt'
        if os.path.exists(page_txt) and os.path.getsize(page_txt) > 0:
            continue
        with open(page_txt, 'w') as f:
            f.write(doc[i].get_text().strip())
        if (i+1) % 50 == 0 or i == todo[-1]:
            print(f'[直抽 {i+1}/{total}]', flush=True)
    with open(f'{OUT}/full.txt', 'w') as full:
        for i in range(total):
            full.write(f'\n{page_marker(i+1)}\n')
            full.write(read_page_txt(i+1))
    extra = f'，toc {len(toc)} 条章节' if toc else ''
    print(f'DONE 文字层直抽 {total}页{rng_note} -> {OUT}/full.txt{extra}（无 quality_report，文字层无需置信度复核；版式复杂页仍按需视觉复核）')
    sys.exit(0)

# ---------- OCR 路径 ----------
from rapidocr_onnxruntime import RapidOCR

ocr = RapidOCR()
t0 = time.time()
suspects = []   # (页码, [可疑行...])

for i in todo:
    page_txt = f'{PAGES_DIR}/p{i+1:03d}.txt'
    if os.path.exists(page_txt) and os.path.getsize(page_txt) > 0:
        continue  # 断点续跑（注意：跳过的页不进本次质量报告）
    pix = doc[i].get_pixmap(dpi=150)
    png = f'{OUT}/_tmp_render.png'
    pix.save(png)
    result, _ = ocr(png)
    lines = []
    if result:
        # 收集几何信息（y中心/x中心/上沿/左沿）→ 按阅读顺序组行
        blocks = []
        for box, text, score in result:
            ys = [p[1] for p in box]; xs = [p[0] for p in box]
            blocks.append({'yc': sum(ys)/len(ys), 'xc': sum(xs)/len(xs),
                           'y0': min(ys), 'x0': min(xs), 't': text, 's': score})
        if VERTICAL:
            # 竖排（古籍）：每框≈一列。列从右到左（x中心降序，近x归同列），列内从上到下
            cols = []
            for b in sorted(blocks, key=lambda b: -b['xc']):
                if cols and abs(b['xc'] - cols[-1][0]) < 40:
                    cols[-1][1].append(b)
                else:
                    cols.append([b['xc'], [b]])
            for _, col in cols:
                col.sort(key=lambda b: b['y0'])
                lines.append(''.join(b['t'] for b in col))
        else:
            # 横排：y中心聚行（竖直差<12px），行内按x升序
            blocks.sort(key=lambda b: (b['yc'], b['x0']))
            merged = []
            for b in blocks:
                if merged and abs(b['yc'] - merged[-1][0]) < 12:
                    merged[-1][1].append(b)
                else:
                    merged.append([b['yc'], [b]])
            for _, row in merged:
                row.sort(key=lambda x: x['x0'])
                lines.append(''.join(x['t'] for x in row))
        # 低置信行收集（复核候选）
        low = [b['t'] for b in blocks if b['s'] < LOW_CONF]
        if low:
            suspects.append((i+1, low))
    with open(page_txt, 'w') as f:
        f.write('\n'.join(lines))
    if (i+1) % 20 == 0 or i == todo[-1]:
        print(f'[{i+1}/{total}] 累计{time.time()-t0:.0f}s', flush=True)

# 合并全文
with open(f'{OUT}/full.txt', 'w') as full:
    for i in range(total):
        full.write(f'\n{page_marker(i+1)}\n')
        full.write(read_page_txt(i+1))

# 质量报告（仅覆盖本次运行的页）
with open(f'{OUT}/quality_report.txt', 'w') as f:
    f.write(f'# OCR 质量报告（低置信<{LOW_CONF}的页，本次运行 {time.strftime('%Y-%m-%d %H:%M')}）\n')
    f.write(f'# 用途：这些页是视觉/大模型复核的候选页；正文页一般很少，表格图多页会集中出现\n\n')
    for pg, low in suspects:
        f.write(f'== {FT.upper()}第{pg}页 ==\n')
        for s in low:
            f.write(f'  ? {s}\n')
print(f'DONE 全书{total}页{rng_note} -> {OUT}/full.txt（低置信页 {len(suspects)} 个，详见 quality_report.txt）')

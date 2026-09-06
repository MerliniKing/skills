#!/usr/bin/env python3
r"""book_parse —— 多模态直读逐页解析流水线（固化的原子能力；固定单一正典 PROMPT，无多轮对比，不依赖 OCR）。

把一本书的全量扫描页交给 GLM 直读（每页产出：有没有图/表 + bbox% + 文字全文），
脚本负责其中一切可测量环节：渲染、分片 prompt 生成、分片回收校验合并、对账报告。
视觉阅读由 Claude Code 会话派 Agent 执行（prompts 子命令输出即派工文本）；
"测量优先于叙述"：页况结论以 roundX-all.jsonl 数据为准，不采信口报。

子命令：
  render  <书> [--pdf 路径] [--dpi 100] [--workdir /tmp/book_parse_<slug>]
          渲染全书页码图（单一进程串行，遵守低占铁律）
  prompts <书> [--workdir ...] [--shard 45] [--round A] [--out 目录]
          按正典 PROMPT 打印各分片派工文本（含页区间与交付文件名）
  merge   <书> --round A [--dir /tmp/book_parse] [--cropdpi 150] [--no-crop]
          合并分片 → pages.jsonl（页况档案）；随后按书页号对齐目录条目，
          组装章节目录树：book-parse/chapters/<序>-<章名>/chapter.md（正文＋图/表 md 引用）
          ＋ imgs/（按 regions 裁剪；--no-crop 跳过裁图只出链接占位）
          （自动修复行内直引号；校验行数/连续性/字段完整性）
  chapters <书> [--offset N]  从档案解析目录→章名/起止页（merge 后自动跑；--offset 手动校正）
  crop    <书> --round A [--dir 目录] [--force] [--dpi 150]
          合并前逐页裁剪：分片 regions → book-parse/imgs/p<页>-<序>.jpg（幂等，已存在跳过）
  distill <书>
          打印每章精读提炼的派工文本（每页都要提炼，无跳过；笔记落 精读/）
  timing  <书> [--outlier 1800]
          汇总各环节逐页/逐章计时 → 打印报表＋落 book-parse/timing/report.json
          （render/crop 为逐页实测；直读来自分片 ts 差分；精读来自笔记 t0/t1 印）
  sample  <书> [--ratio 0.10] [--seed N] [--dpi 300] [--check]
          裁后抽检（2026-08-31 用户定案，替代逐张目验）：随机抽裁图 10%（至少 3 张），
          按高分辨率重渲染抽中页原页 PNG → book-parse/verify/，打印抽检派工文本；
          agent 回填 verify/sample-report.jsonl 后跑 --check 验收，缺报/非 pass 即 exit 1
          页级漏报/误报（GT=图录有图页∪表页）＋区域 IoU（vs 图录 rect）
          抽验走 overlay 叠框图/人工抽页协议）

正典 PROMPT（2026-08-31 两次用户定案改版：
①逐页计时落盘＋增量交付抗中断，终报不再重贴全文，由 merge 行数/连续性校验兜底；
②regions 允许两界简写：图/表左右无环绕正文时只报 [y0,y1,type]（左右默认整页宽），
有环绕正文则仍报全四坐标；裁后验收由逐张目验改为 10% 随机抽检（sample 子命令），
crop 对两种坐标形双兼容）：
见 PROMPT 常量。改它须经用户确认。

用法示例（在库根目录）：
  python3 tools/book_parse.py render 今-汉宝德-风水与环境
  python3 tools/book_parse.py prompts 今-汉宝德-风水与环境 --round A
  python3 tools/book_parse.py merge 今-汉宝德-风水与环境 --round A
"""
import argparse, glob, json, math, os, random, re, sys, time

PROMPT = """你是书页解析员。{workdir}/ 目录下是某本书的逐页扫描图 pNNN.png。用 Read 工具逐张查看 {lo_png} 至 {hi_png}，为每页输出一行 JSON：
{{"page":N,"has_figure":布尔,"has_table":布尔,"regions":[[x0,y0,x1,y1,"figure"或"table"]],"text":"…"}}，并附加三个字段：
{{"page":N,"book_page":本页印刷页码或null,"is_toc":布尔,"toc":[{{"title":"章节名","book_page":起始书页}}],
 "has_figure":布尔,"has_table":布尔,"regions":[…],"text":"…"}}

示例——假如某页上半是一张带边框的「历代纪元表」（纵向 10%–40%，通栏两侧无环绕正文）、中间一段正文、下方一幅右侧带批注文字的山水示意图（纵 55%–82%、横 12%–88%），理想输出是：
{{"page":57,"has_figure":true,"has_table":true,"regions":[[10,40,"table"],[12,55,88,82,"figure"]],"text":"…正文自表格之后抄起…"}}
要点：表格框含边框整体；示意图连同它下方那行题注一起框；text 只抄正文文字，表格里和图里的字不抄。

新增字段规则：
0a. book_page：判断当前页面左下角/右下角是否印有图书页号（数字），有则输出该页号；没有则 null
0b. is_toc：本页是否为目录页（列出"章节名+起始书页"清单的页面）
0c. toc：仅当 is_toc=true 时输出结构化目录——按目录原顺序，每条 {{"title":"章节名原文","book_page":该章起始书页}}；is_toc=false 时为 []

判定规则：
1. has_table=true 当且仅当页面存在由边框线/行列分隔线构成的表格结构
2. has_figure=true 当页面存在正文文字排版之外的图形：插图、照片、地图、图表、示意图、手绘图皆算；纯装饰纹样、页眉页脚不算
3. regions：每个独立图表一个框。标准形 [x0,y0,x1,y1,"figure"或"table"]——页面百分比（x0左/y0上/x1右/y1下，0–100，原点左上）。
   简写：图/表**左右没有环绕正文**（两侧是页缘/留白/版心空白）时，可只报上下两界 [y0,y1,"figure"或"table"]，左右默认整页宽；
   左右有环绕正文/旁批/双栏文字则必须报全 4 坐标把图表单独框出。上下界必须把附属文字一起包入：题注、图内标注、紧邻图例（表格含边框整体，y0=边框上沿线 y1=边框下沿线/末行下缘）；无图表填 []
   ★ 表格内部嵌的小图不单独标注——一张表只给一组坐标；表格之外的独立图才单独框
4. text：忠实转写该页全部正文文字，按阅读顺序，含章节标题；表格与图内部文字不转写；空白页输出 ""；辨认不清的字写【不可辨】
5. 纪律：每页必须亲眼看过再判定；不跳页、不臆测；扫描污渍不是图

计时与交付（铁律）：
0. 动工前先用 Bash 跑 date +%s 记为 T0。若 {outfile} 已存在，先统计其中已有页行（grep -c '"page"'），
   从下一个未交付页续跑，已交付页不重读。
1. 每读完并转写完一页，立即用 Bash 把该页这行 JSONL 追加进 {outfile}（cat <<'EOF' 方式），
   对象内末尾固定加字段 "ts":<unix秒>，ts 取自同一条命令里的 $(date +%s)。逐页落盘，绝不攒批。
2. {n} 页全部追加完，再用 Bash 向 {outfile} 末尾追加一行：# end $(date +%s)
3. 最终回复固定一句话：「分片完成：{outfile} 共 {n} 行」。不要在回复里重贴 JSONL，不要任何解释。"""

def _root():
    """仓库根自动探测：向上找含 sources/ 的目录（流水线可在根或 book-content/ 下执行）。"""
    base = os.getcwd()
    for _ in range(3):
        if os.path.isdir(os.path.join(base, 'sources')):
            return base
        base = os.path.dirname(base)
    sys.exit('未找到仓库根（含 sources/）——请在库根或 book-content/ 下执行')

def book_root(book):
    root = _root()
    for cand in (os.path.join(root, 'book-content', 'books', book),
                 os.path.join(root, 'books', book)):
        if os.path.isdir(cand):
            os.makedirs(cand, exist_ok=True)
            return cand
    os.makedirs(os.path.join(root, 'book-content', 'books', book), exist_ok=True)
    return os.path.join(root, 'book-content', 'books', book)

def find_pdf(book, override):
    if override:
        return override
    root = _root()
    hits = []
    for d, _, fs in os.walk(os.path.join(root, 'sources')):
        for fn in fs:
            if fn.lower().endswith(('.pdf', '.epub')) and book.split('-')[-1] in fn:
                hits.append(os.path.join(d, fn))
    if len(hits) != 1:
        sys.exit('PDF 不唯一/未找到，用 --pdf 指定: ' + '; '.join(hits))
    return hits[0]

def npages(pdf):
    import fitz
    doc = fitz.open(pdf)
    n = len(doc); doc.close()
    return n

def cmd_render_epub(a, epub):
    import zipfile, html.parser, json
    broot = book_root(a.book)
    outdir = os.path.join(broot, 'book-parse'); os.makedirs(outdir, exist_ok=True)
    mediadir = os.path.join(outdir, 'media'); os.makedirs(mediadir, exist_ok=True)
    class _P(html.parser.HTMLParser):
        def __init__(self):
            super().__init__(); self.txt=[]; self.title=''; self.media=[]; self._h=None
        def handle_starttag(self, tag, attrs):
            if tag in ('h1','h2','h3') and not self.title: self._h=tag
            if tag=='img':
                d=dict(attrs)
                if d.get('src'): self.media.append(os.path.basename(d['src']))
        def handle_endtag(self, tag):
            if tag==self._h: self._h=None
            if tag in ('p','div','h1','h2','h3'): self.txt.append('\n')
        def handle_data(self, d):
            d=d.strip()
            if d:
                if self._h and not self.title: self.title=d
                self.txt.append(d+' ')
    z=zipfile.ZipFile(epub)
    names=set(z.namelist())
    container=z.read('META-INF/container.xml').decode('utf-8','ignore')
    opf=re.search(r'full-path="([^"]+)"',container).group(1)
    opfdir=os.path.dirname(opf)
    opfxml=z.read(opf).decode('utf-8','ignore')
    man={}
    for tag in re.finditer(r'<item\b[^>]*/?>',opfxml):
        t=tag.group(0)
        gid=re.search(r'id="([^"]+)"',t); ghref=re.search(r'href="([^"]+)"',t); gmt=re.search(r'media-type="([^"]+)"',t)
        if gid and ghref: man[gid.group(1)]=(ghref.group(1), gmt.group(1) if gmt else '')
    spine=[m.group(1) for m in re.finditer(r'<itemref[^>]*idref="([^"]+)"',opfxml)]
    chapters=[]
    for i,idref in enumerate(spine,1):
        href,mt=man.get(idref,('',''))
        full=os.path.normpath(os.path.join(opfdir,href)).replace('\\','/')
        if mt and 'html' not in mt or full not in names: continue
        p=_P(); p.feed(z.read(full).decode('utf-8','ignore'))
        txt=re.sub(r'\n{3,}','\n\n',''.join(p.txt)).strip()
        chapters.append(dict(chapter=i,href=href,title=p.title or os.path.basename(href),text=txt,media=p.media))
    out=os.path.join(outdir,'chapters.jsonl')
    open(out,'w',encoding='utf8').write('\n'.join(json.dumps(c,ensure_ascii=False) for c in chapters)+'\n')
    media_all=sorted({m for c in chapters for m in c['media']})
    extracted=0
    for mname in media_all:
        full=[n for n in names if n.endswith(mname)]
        if full:
            open(os.path.join(mediadir,os.path.basename(mname)),'wb').write(z.read(full[0])); extracted+=1
    print('✓ EPUB 结构化解析：%d 章 → %s；媒体 %d 个 → %s（未登记图录；收割时用 crop --register-media 或明确指示）'
          % (len(chapters), out, extracted, mediadir))
    print('  章文本即档案文字；媒体无页码语义，按章节锚定（chapters.jsonl 的 media 字段）')

def cmd_render(a):
    pdf = find_pdf(a.book, a.pdf)
    if pdf.lower().endswith('.epub'):
        return cmd_render_epub(a, pdf)
    import fitz
    pdf = find_pdf(a.book, a.pdf)
    os.makedirs(a.workdir, exist_ok=True)
    tdir = os.path.join(book_root(a.book), 'book-parse', 'timing')
    os.makedirs(tdir, exist_ok=True)
    t0 = time.time()
    doc = fitz.open(pdf)
    with open(os.path.join(tdir, 'render.jsonl'), 'w', encoding='utf8') as tf:
        for i in range(len(doc)):
            t1 = time.time()
            doc[i].get_pixmap(dpi=a.dpi).save(os.path.join(a.workdir, 'p%03d.png' % (i + 1)))
            tf.write(json.dumps({'page': i + 1, 'sec': round(time.time() - t1, 2)}) + '\n')
            tf.flush()
    n = len(doc); doc.close()
    wall = time.time() - t0
    print('rendered %d pages -> %s（墙钟 %.1fs，均 %.2fs/页；逐页明细 %s）'
          % (n, a.workdir, wall, wall / n, os.path.join(tdir, 'render.jsonl')))

def cmd_prompts(a):
    pdf = find_pdf(a.book, a.pdf)
    n = npages(pdf)
    slug = re.sub(r'[^\w]', '', a.book.split('-')[-1])[:8] or 'book'
    a.workdir = a.workdir.rstrip('/')
    i = 1
    while i <= n:
        hi = min(i + a.shard - 1, n)
        name = 'round%s-pa-%s.jsonl' % (a.round, chr(ord('a') + (i - 1) // a.shard))
        out = os.path.join(a.out, name)
        print('=== 分片 %s（p%d–%d）→ 交付 %s' % (chr(ord('a') + (i - 1) // a.shard).upper(), i, hi, out))
        print(PROMPT.format(workdir=a.workdir, lo_png='p%03d.png' % i, hi_png='p%03d.png' % hi,
                            n=hi - i + 1, outfile=out))
        print()
        i = hi + 1

def _fix_line(line):
    m = re.match(r'^(\{"page":\d+,"has_figure":(?:true|false),"has_table":(?:true|false),'
                 r'"regions":\[(?:\[[^\]]*\],?)*\]),"text":"(.*)"\}$', line)
    if m:
        return m.group(1) + ',"text":"' + m.group(2).replace('\\', '\\\\').replace('"', '\\"') + '"}'
    json.loads(line)
    return line

def cmd_merge(a):
    broot = book_root(a.book)
    t0 = time.time()
    shards = [f for f in sorted(glob.glob(os.path.join(a.dir, 'round%s-*.jsonl' % a.round)))
              if '-all' not in os.path.basename(f)]
    if not shards:
        sys.exit('无分片: %s/round%s-*.jsonl' % (a.dir, a.round))
    rows = {}
    for sp in shards:
        if '.part' in sp:
            continue
        for line in open(sp, encoding='utf8'):
            line = line.strip()
            if not line or line.startswith('#'):    # '# end <ts>' 等计时注记行
                continue
            r = json.loads(_fix_line(line))
            rows[r['page']] = r
    pages = sorted(rows)
    gaps = [p for p in range(pages[0], pages[-1] + 1) if p not in rows]
    need = {'page', 'has_figure', 'has_table', 'regions', 'text'}
    bad = [p for p in pages if not need <= set(rows[p])]
    if gaps or bad:
        sys.exit('分片不完整: 缺页 %s 坏行 %s' % (gaps[:10], bad[:10]))
    outdir = os.path.join(broot, 'book-parse')
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, 'pages.jsonl')
    open(out, 'w', encoding='utf8').write(
        '\n'.join(json.dumps(rows[p], ensure_ascii=False) for p in pages) + '\n')
    nf = sum(rows[p]['has_figure'] for p in pages)
    nt = sum(rows[p]['has_table'] for p in pages)
    print('✓ %s（%d 页 %d-%d 连续）has_figure=%d has_table=%d' % (out, len(pages), pages[0], pages[-1], nf, nt))
    tdir = os.path.join(outdir, 'timing'); os.makedirs(tdir, exist_ok=True)
    json.dump({'pages': len(pages), 'total_sec': round(time.time() - t0, 1)},
              open(os.path.join(tdir, 'merge.json'), 'w'))
    # ── 组装器：以书页号为对齐键，汇总章节文本＋裁图＋md 引用 ──
    chapters_out = assemble(a, broot, outdir, rows)
    if chapters_out is not None:
        print('  ↳ 章节组装：%d 个子章节 → %s/chapters/' % (chapters_out, outdir))
        entries, off, unv = parse_chapters(rows, None)
        with open(os.path.join(outdir, 'chapters.jsonl'), 'w', encoding='utf8') as w:
            for e in entries:
                w.write(json.dumps(e, ensure_ascii=False) + '\n')
        print('  ↳ 章节表：%d 条（未确认 %d）' % (len(entries), len(unv)))

def cmd_distill(a):
    """每页精读提炼的派工文本：AI 逐章消化 chapter.md（原文+图表引用），产出精读笔记——无跳过、无定纲门。"""
    broot = book_root(a.book)
    cpath = os.path.join(broot, 'book-parse', 'chapters.jsonl')
    if not os.path.exists(cpath):
        sys.exit('章节表不存在: %s（先跑 merge）' % cpath)
    chs = [json.loads(l) for l in open(cpath, encoding='utf8') if l.strip()]
    brief = (
        '=== 精读提炼总纲（随分片派工文本一同下发）===\n'
        '任务：逐章精读提炼。对分配给你的每一章，读 chapter.md（原文逐页聚合＋图表引用），\n'
        '产出该章精读笔记 md：Write 到 精读/chapter-<章序>-<标题>.md。\n'
        '要求：①覆盖该章每一页——无跳过、无略字；②术语首现必释；③引文原样摘自 chapter.md 内的原文，不得改写；\n'
        '④每页至少一条提炼（要点/存疑/联想任一）；⑤图表引用原样保留并各配一句解读；\n'
        '⑥开头写明章名与书页区间。笔记正文不设上限，以不漏信息为准。\n'
        '计时：动工时先 Bash 取 date +%s 写进笔记首行 <!-- t0:<unix> -->；完稿后再取一次，写末行 <!-- t1:<unix> -->。')
    print(brief)
    for i, c in enumerate(chs, 1):
        print('--- 章节派工 %02d：chapters/%02d-%s/chapter.md → 精读/chapter-%02d-%s.md'
              % (i, i, _safe(c['title'])[:20], i, _safe(c['title'])[:20]))

def parse_chapters(rows, offset=None):
    """从档案解析目录页→章名/起止页。返回 entries 列表（含 pdf 换算与页眉校验）。"""
    toc_texts = []
    for p in sorted(rows):
        t = (rows[p].get('text') or '').strip()
        if not t:
            continue
        pairs = re.findall(r'([\u4e00-\u9fff《》〔〕][^0-9\n]{1,40}?)\s?(\d{1,3})(?=\s|$)', t)
        if re.search(r'目\s*录', t[:24]) or len(pairs) >= 6:
            toc_texts.append((p, t))
    entries = []
    for p, t in toc_texts:
        t = re.sub(r'^.*?目\s*录', '', t, count=1, flags=re.S) if re.search(r'目\s*录', t[:24]) else t
        for m in re.finditer(r'([\u4e00-\u9fff《》〔〕][^0-9\n]{1,40}?)\s?(\d{1,3})(?=\s|$)', t):
            title = re.sub(r'\s', '', m.group(1))
            if len(title) >= 2:
                entries.append({'title': title, 'print_page': int(m.group(2)), 'toc_page': p})
    # 去重（跨目录页重复项）并保持单调
    seen, mono = set(), []
    last = 0
    for e in entries:
        key = (e['title'], e['print_page'])
        if key in seen or e['print_page'] < last:
            continue
        seen.add(key); mono.append(e); last = e['print_page']
    entries = mono
    # 偏移自动探测：对 0..40 逐个试，取“章首页含章名前4字”的命中数最大者
    def score(off):
        hit = 0
        for e in entries:
            pg = e['print_page'] + off
            t = rows.get(pg, {}).get('text', '')
            if t and e['title'][:4] in t.replace(' ', ''):
                hit += 1
        return hit
    if offset is None:
        best = max(range(0, 41), key=score)
        if score(best) == 0:
            return entries, None, 0
        offset = best
    # 硬性确认：目录+偏移只是提议；章名必须出现在目标页（或±1页）的文字识别结果里
    #   ——命中即吸附到实际页；±1 窗口仍找不到则标 unverified（不参与边界推导）
    unverified = []
    for e in entries:
        want = re.sub(r'[\s·：:—－、.。]', '', e['title'])[:4]
        hit = None
        for dp in (0, -1, 1):
            pg = e['print_page'] + offset + dp
            t = re.sub(r'[\s·：:—－、.。]', '', rows.get(pg, {}).get('text', ''))
            if t and want in t:
                hit = pg; break
            if t and want[:2] in t:   # 二级宽松：页面用短题（如「内形：配置」vs 目录全称）
                hit = pg; e['loose'] = True; break
        e['pdf_page'] = hit if hit else e['print_page'] + offset
        e['verified'] = hit is not None
        if not e['verified']:
            unverified.append(e['title'])
    entries = [e for e in entries if e['verified']] or entries
    for i, e in enumerate(entries):
        nxt = entries[i + 1]['pdf_page'] if i + 1 < len(entries) else max(rows) + 1
        e['end_pdf_page'] = max(e['pdf_page'], nxt - 1)
    return entries, offset, unverified

def _safe(name):
    return re.sub(r'[\\/:*?"<>|\s]+', '', name)[:40] or 'untitled'

def assemble(a, broot, outdir, rows):
    """以书页号为对齐键：目录条目 → 章节区间 → 文本汇总 + regions 裁图 + 章节草稿 md。"""
    toc = []
    for p in sorted(rows):
        r = rows[p]
        if r.get('is_toc'):
            for e in r.get('toc') or []:
                if e.get('title') and isinstance(e.get('book_page'), int):
                    toc.append((p, e['title'], e['book_page']))
    bp = {p: r.get('book_page') for p, r in rows.items() if isinstance(r.get('book_page'), int)}
    aligned = None
    if len(toc) >= 2 and len(bp) >= 2:
        # 对齐校验：目录宣称的书页号应能在 bp 中找到（同号即对上）
        bps = set(bp.values())
        toc2 = [(tp, t, bp_) for tp, t, bp_ in toc if bp_ in bps]
        if len(toc2) >= 2:
            toc2 = sorted({(t, bp_) for _, t, bp_ in toc2}, key=lambda x: x[1])
            aligned = [(t, b_) for t, b_ in toc2]
    if aligned is None:                     # 旧档案无 book_page 字段 → 用目录解析的已校准 pdf 页
        entries, off, unv = parse_chapters(rows, None)
        if not entries:
            print('  ↳ 组装跳过：目录与书页号均不可用'); return None
        aligned = [(e['title'], e['pdf_page']) for e in entries if e['verified']]
        segs = []
        for i, (t, lo) in enumerate(aligned):
            hi = (aligned[i + 1][1] - 1) if i + 1 < len(aligned) else max(rows)
            segs.append((t, lo, hi))
        b2p = {}
        for i, (t, lo, hi) in enumerate(segs, 1):
            pass
    else:
        segs = []
        b2p = {}
        for p, b in sorted(bp.items()): b2p.setdefault(b, p)
        for i, (t, b) in enumerate(aligned):
            lo = b
            hi = (aligned[i + 1][1] - 1) if i + 1 < len(aligned) else max(bp)
            segs.append((t, lo, hi))
    # 按 书页区间 收 member 页（book_page 相等即归段；无书页页归前桶）
    os.makedirs(os.path.join(outdir, 'chapters'), exist_ok=True)
    made = 0
    used_pages = set()
    for i, (title, lo, hi) in enumerate(segs, 1):
        members = [p for p in sorted(rows) if p not in used_pages
                   and bp.get(p) is not None and lo <= bp[p] <= hi]
        if not members:
            members = [p for p in sorted(rows)
                       if p not in used_pages and (lo - 0) <= p <= hi]
        if members:
            used_pages |= set(members)
        d = os.path.join(outdir, 'chapters', '%02d-%s' % (i, _safe(title)))
        os.makedirs(os.path.join(d, 'imgs'), exist_ok=True)
        parts = ['# %s' % title, '', '书页 %d–%d · PDF p%s–p%s' % (lo, hi,
                 min(members) if members else '-', max(members) if members else '-'), '']
        figs = []
        for p in members:
            for k, rg in enumerate(rows[p].get('regions', []), 1):
                typ = rg[-1] if len(rg) in (3, 5) and isinstance(rg[-1], str) else 'figure'
                figs.append('![PDF p%d %s](../../imgs/p%03d-%d.jpg)' % (p, typ, p, k))
        for p in members:
            t = (rows[p].get('text') or '').replace('\\n', '\n')
            bp_ = bp.get(p)
            parts.append('<!-- PDF p%d · 书页 %s -->' % (p, bp_ if bp_ is not None else '?'))
            if t: parts.append(t)
            parts.append('')
        if figs:
            parts.append('## 图表')
            parts += [''] + figs + ['']
        open(os.path.join(d, 'chapter.md'), 'w', encoding='utf8').write('\n'.join(parts) + '\n')
        made += 1
    # 未归属页（前置/无书页）
    rest = [p for p in sorted(rows) if p not in used_pages]
    if rest:
        d = os.path.join(outdir, 'chapters', '00-前置与未归属')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'chapter.md'), 'w', encoding='utf8') as w:
            w.write('# 前置与未归属\n')
            for p in rest:
                w.write('\n<!-- PDF p%d -->\n%s\n' % (p, rows[p].get('text') or ''))
        print('  ↳ 未归属页 %d → 00-前置与未归属' % len(rest))
    return made


def cmd_chapters(a):
    broot = book_root(a.book)
    path = os.path.join(broot, 'book-parse', 'pages.jsonl')
    if not os.path.exists(path):
        sys.exit('档案不存在: %s（先跑 merge）' % path)
    rows = {r['page']: r for r in map(json.loads, filter(str.strip, open(path, encoding='utf8')))}
    entries, off, unv = parse_chapters(rows, a.offset)
    out = os.path.join(broot, 'book-parse', 'chapters.jsonl')
    open(out, 'w', encoding='utf8').write(
        '\n'.join(json.dumps(e, ensure_ascii=False) for e in entries) + '\n')
    ok = len(entries) - len(unv)
    print('✓ %s（%d 章；目标页文字比对确认 %d，未确认 %d：%s）'
          % (out, len(entries), ok, len(unv), '、'.join(unv[:6])))
    for e in entries:
        mark = '✓' if e['verified'] else '?未确认'
        print('  p%-4d-%-4d %s %s' % (e['pdf_page'], e['end_pdf_page'], mark, e['title']))


def cmd_crop(a):
    import fitz
    """合并前的逐页裁剪：按分片档案的 regions 把每页图/表裁到 book-parse/imgs/（p<页>-<序>.jpg）。"
    merge 组装章节时直接以相对路径引用这些文件；pages.jsonl 的 regions 就是清单，无需登记册。"""
    broot = book_root(a.book)
    shards = [f for f in sorted(glob.glob(os.path.join(a.dir, 'round%s-*.jsonl' % a.round)))
              if '-all' not in os.path.basename(f)]
    if not shards:
        sys.exit('无分片: %s/round%s-*.jsonl' % (a.dir, a.round))
    rows = {}
    for sp in shards:
        for line in open(sp, encoding='utf8'):
            line = line.strip()
            if line and not line.startswith('#'):   # '# end <ts>' 等计时注记行
                r = json.loads(line); rows[r['page']] = r
    pdf = find_pdf(a.book, a.pdf)
    doc = fitz.open(pdf)
    outdir = os.path.join(broot, 'book-parse', 'imgs')
    os.makedirs(outdir, exist_ok=True)
    tdir = os.path.join(broot, 'book-parse', 'timing'); os.makedirs(tdir, exist_ok=True)
    made = skipped = 0
    with open(os.path.join(tdir, 'crop.jsonl'), 'w', encoding='utf8') as tf:
        for p in sorted(rows):
            regs = rows[p].get('regions') or []
            if not regs:
                continue
            t1 = time.time()
            pw, ph = doc[p - 1].rect.width, doc[p - 1].rect.height
            for k, rg in enumerate(regs, 1):
                fn = os.path.join(outdir, 'p%03d-%d.jpg' % (p, k))
                if os.path.exists(fn) and not a.force:
                    skipped += 1; continue
                if len(rg) >= 4:    # 旧版四坐标 [x0,y0,x1,y1,(type)]
                    x0, y0, x1, y1 = rg[0], rg[1], rg[2], rg[3]
                else:               # 2026-08-31 版两界 [y0,y1,type] → 整页宽（左右不带偏）
                    x0, y0, x1, y1 = 0.0, rg[0], 100.0, rg[1]
                clip = fitz.Rect(x0 / 100 * pw, y0 / 100 * ph, x1 / 100 * pw, y1 / 100 * ph)
                pix = doc[p - 1].get_pixmap(clip=clip, dpi=a.dpi, colorspace=fitz.csGRAY)
                pix.save(fn, jpg_quality=80)
                made += 1
            tf.write(json.dumps({'page': p, 'figs': len(regs), 'sec': round(time.time() - t1, 2)}) + '\n')
    doc.close()
    print('✓ 逐页裁剪 %d 张（跳过已存在 %d）→ %s；逐页明细 %s/crop.jsonl' % (made, skipped, outdir, tdir))

def _stats(xs):
    """秒数列表 → n/均值/中位/最快/最慢/p90；空列表返回 None。"""
    if not xs:
        return None
    xs = sorted(xs)
    return {'n': len(xs), 'avg': round(sum(xs) / len(xs), 1), 'med': xs[len(xs) // 2],
            'min': xs[0], 'max': xs[-1], 'p90': xs[min(len(xs) - 1, int(len(xs) * 0.9))]}

def cmd_timing(a):
    """汇总各环节计时：render/crop 逐页实测；直读取 pages.jsonl 的 ts 差分（跨分片跳变剔除）；精读取笔记 t0/t1。"""
    broot = book_root(a.book)
    tdir = os.path.join(broot, 'book-parse', 'timing')
    os.makedirs(tdir, exist_ok=True)
    rep = {}
    # render / crop：逐页实测明细
    for key, fn, unit in (('render', 'render.jsonl', '秒/页'), ('crop', 'crop.jsonl', '秒/图页')):
        p = os.path.join(tdir, fn)
        if os.path.exists(p):
            xs = [json.loads(l)['sec'] for l in open(p, encoding='utf8') if l.strip()]
            rep[key] = {'unit': unit, 'total_sec': round(sum(xs), 1), 'per': _stats(xs)}
    # merge：整体墙钟
    p = os.path.join(tdir, 'merge.json')
    if os.path.exists(p):
        rep['merge'] = {'unit': '秒/整体', **json.load(open(p, encoding='utf8'))}
    # 直读：ts 差分（分片并发时跨分片相邻页差分为负/异常大，剔除）
    ppath = os.path.join(broot, 'book-parse', 'pages.jsonl')
    if os.path.exists(ppath):
        rows = [json.loads(l) for l in open(ppath, encoding='utf8') if l.strip()]
        ts = {r['page']: r['ts'] for r in rows if isinstance(r.get('ts'), int)}
        ds, prev_pg = [], None
        for pg in sorted(ts):
            if prev_pg is not None and pg == prev_pg + 1:      # 仅同分片内相邻页可差分
                d = ts[pg] - ts[prev_pg]
                if 0 < d < a.outlier:
                    ds.append(d)
            prev_pg = pg
        if ds:
            rep['直读'] = {'unit': '秒/页', 'per': _stats(ds),
                           'note': 'ts 差分（含逐页落盘往返）；跳变>%ds 或非同分片相邻页不计' % a.outlier}
    # 精读：笔记首尾 t0/t1 印 → 秒/章
    jd = os.path.join(broot, 'book-parse', '精读')
    if os.path.isdir(jd):
        ch = []
        for fn in sorted(os.listdir(jd)):
            if not fn.endswith('.md'):
                continue
            txt = open(os.path.join(jd, fn), encoding='utf8').read()
            m0, m1 = re.search(r't0:(\d+)', txt), re.search(r't1:(\d+)', txt)
            if m0 and m1:
                ch.append(int(m1.group(1)) - int(m0.group(1)))
        if ch:
            rep['精读'] = {'unit': '秒/章', 'per': _stats(ch), 'total_sec': sum(ch)}
    out = os.path.join(tdir, 'report.json')
    json.dump(rep, open(out, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    print('=== 计时报表 → %s' % out)
    if not rep:
        print('  （无计时数据：2026-08-31 前的旧档案无 ts/t0-t1 印，render/crop 未重跑）')
    for k, v in rep.items():
        line = '  %-6s 合计 %ss' % (k, v.get('total_sec', '—'))
        if v.get('per'):
            s = v['per']
            line += '；%s n=%d 均 %s%s 中位 %s 最快 %s 最慢 %s p90 %s' % (
                'per', s['n'], s['avg'], v['unit'], s['med'], s['min'], s['max'], s['p90'])
        print(line)
        if v.get('note'):
            print('         └ %s' % v['note'])

SAMPLE_BRIEF = """=== 裁图抽检派工（{ratio:.0%} 随机抽样 {n}/{total} 张；清单 {samples}）===
你是裁图抽检员。对下面每一项：
①Read {vdir}/pNNN.png（原页整页图，按页号对号入座）
②Read {imgs}/pNNN-k.jpg（从该页裁出的图/表）
然后只回答三个报告题（不要给「看起来完整」这类整体判断，只报具体内容）：
1. what  裁图里装的是什么：表格→报行列数与首行/末行内容；整页图版→报子图数与各局名/编号；插图→念出题注原文
2. edges 对照原页：裁图上缘、下缘处原内容是否被切断（如「上缘完整；下缘切断，被切的是表格末行」）
3. annex 附属文字（题注/图例/编号说明）原页上有哪些、裁图包进了哪些、缺了哪些
每项输出一行 JSONL：
{{"page":页号,"k":序号,"what":"…","edges":"…","annex":"…","verdict":"pass|切上缘|切下缘|缺附属|内容不符|存疑"}}
verdict 仅当 1–3 全无缺失才判 pass；任何缺失/切断/不符用对应标签，拿不准写「存疑」。
全部 {n} 行 JSONL 用 Write 写入 {report}，最终回复只写一句：「抽检完成：共 {n} 行，非 pass N 条（N＝verdict≠pass 的行数，自数）」。"""

def cmd_sample(a):
    """裁后抽检（2026-08-31 用户定案，替代逐张目验/全量终验）：从 book-parse/imgs/ 随机抽
    ratio 比例（至少 3 张），按高分辨率重渲染抽中页原页 PNG 到 book-parse/verify/，
    打印抽检派工文本；agent 回填 sample-report.jsonl 后用 --check 校验，缺报/非 pass 即 exit 1。"""
    broot = book_root(a.book)
    imgs = os.path.join(broot, 'book-parse', 'imgs')
    vdir = os.path.join(broot, 'book-parse', 'verify')
    os.makedirs(vdir, exist_ok=True)
    samples_path = os.path.join(vdir, 'samples.json')
    report_path = os.path.join(vdir, 'sample-report.jsonl')
    if a.check:
        if not os.path.exists(samples_path):
            sys.exit('抽样清单不存在: %s（先跑 sample 生成抽样）' % samples_path)
        meta = json.load(open(samples_path, encoding='utf8'))
        picks = [(s['page'], s['k']) for s in meta['sampled']]
        if not os.path.exists(report_path):
            sys.exit('抽检报告不存在: %s' % report_path)
        got = {}
        for line in open(report_path, encoding='utf8'):
            line = line.strip()
            if line and not line.startswith('#'):
                r = json.loads(line)
                got[(r['page'], r['k'])] = r
        missing = [t for t in picks if t not in got]
        bad = [(t, got[t].get('verdict', '?')) for t in picks if t in got and got[t].get('verdict') != 'pass']
        print('抽检 %d/%d 张：pass %d ｜ 非pass %d ｜ 缺报 %d'
              % (len(picks), meta['n_crops'], len(picks) - len(missing) - len(bad), len(bad), len(missing)))
        for (p, k), v in bad:
            print('  ✗ p%03d-%d verdict=%s' % (p, k, v))
        if missing:
            print('  ✗ 未覆盖: %s' % ', '.join('p%03d-%d' % t for t in missing[:10]))
        if missing or bad:
            sys.exit(1)
        print('✓ 抽检通过')
        return
    crops = []
    for fn in sorted(os.listdir(imgs)) if os.path.isdir(imgs) else []:
        m = re.match(r'^p(\d+)-(\d+)\.jpg$', fn)
        if m:
            crops.append((int(m.group(1)), int(m.group(2))))
    if not crops:
        sys.exit('无裁图: %s（先跑 crop）' % imgs)
    n = min(len(crops), max(3, math.ceil(len(crops) * a.ratio)))
    picks = sorted(random.Random(a.seed).sample(crops, n))
    json.dump({'seed': a.seed, 'ratio': a.ratio, 'n_crops': len(crops),
               'sampled': [{'page': p, 'k': k} for p, k in picks]},
              open(samples_path, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    # 原页按高分辨率重渲染（审计教训：高分辨率整页 > 缩略蒙太奇，缩略会幻觉「无切边」）
    dpi = 300 if a.dpi == 100 else a.dpi      # 未显式给 --dpi 时抽检用 300（render 的默认 100 不够看）
    import fitz
    doc = fitz.open(find_pdf(a.book, a.pdf))
    for pg in sorted({p for p, _ in picks}):
        out = os.path.join(vdir, 'p%03d.png' % pg)
        if os.path.exists(out):
            continue
        doc[pg - 1].get_pixmap(dpi=dpi, colorspace=fitz.csGRAY).save(out)
    doc.close()
    print(SAMPLE_BRIEF.format(ratio=a.ratio, n=n, total=len(crops), vdir=vdir, imgs=imgs,
                              samples=samples_path, report=report_path))
    print('抽样明细：%s' % ', '.join('p%03d-%d' % t for t in picks))

def main():
    ap = argparse.ArgumentParser(description=__doc__.split('子命令：')[0])
    ap.add_argument('cmd', choices=['render', 'prompts', 'merge', 'chapters', 'crop', 'distill', 'timing', 'sample'])
    ap.add_argument('book')
    ap.add_argument('--pdf'); ap.add_argument('--dpi', type=int, default=100)
    ap.add_argument('--workdir', default=None)
    ap.add_argument('--shard', type=int, default=45)
    ap.add_argument('--round', default='A')
    ap.add_argument('--out', default='/tmp/book_parse')
    ap.add_argument('--dir', default='/tmp/book_parse')
    ap.add_argument('--pages', default=None)
    ap.add_argument('--offset', type=int, default=None)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--outlier', type=int, default=1800)
    ap.add_argument('--ratio', type=float, default=0.10)
    ap.add_argument('--seed', type=int, default=None)
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    if a.workdir is None:
        a.workdir = '/tmp/book_parse_' + re.sub(r'[^\w]', '', a.book)
    {'render': cmd_render, 'prompts': cmd_prompts, 'merge': cmd_merge,
     'chapters': cmd_chapters, 'crop': cmd_crop, 'distill': cmd_distill,
     'timing': cmd_timing, 'sample': cmd_sample}[a.cmd](a)

if __name__ == '__main__':
    main()

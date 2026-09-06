#!/usr/bin/env python3
r"""逐页页况探测：判断扫描书每一页是 空白/纯文字/有表格框/有插图 —— 防止只认「图N」引用而漏收无编号图版（fs1 附录案后立）。

物理特征（不依赖任何文字理解）：
  · 表格框 = 同页存在 ≥2 条贯通横向长直线 且 ≥2 条纵向长直线
  · 插图   = 出现高度超过正文行高的"厚墨带"（连续多行高密度墨迹）或超大墨块占比区
  · 空白   = 全页墨迹 < 1.5%
输出 books/<书>/img/pages.jsonl（每页一行）＋摘要 stdout。
拿不准（有框但少、或墨带临界）标 needs_eye=true 交人工/视觉复核。

用法: python3 pages_probe.py <书目录名> [--pdf 路径] [--dpi 80]
"""
import sys, os, json, argparse
import numpy as np
import fitz

def longest_run(mask):
    best=cur=0
    for v in mask:
        cur=cur+1 if v else 0
        best=max(best,cur)
    return best

def probe_page(pix):
    g=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width)
    H,W=g.shape
    ink=g<135
    total=float(ink.mean())
    hl=sum(1 for y in range(H) if longest_run(ink[y])>=W*0.30)
    vl=sum(1 for x in range(W) if longest_run(ink[:,x])>=H*0.12)
    # 厚墨带：行墨量>30% 的连续段，段高>行高两倍视为图形特征
    rowd=ink.mean(axis=1)
    thr=0.30
    bands=[]; s=None
    for y in range(H):
        if rowd[y]>thr and s is None: s=y
        elif rowd[y]<=thr and s is not None:
            bands.append(y-s); s=None
    if s is not None: bands.append(H-s)
    big=[b for b in bands if b>4]
    med=big[len(big)//2] if big else 0
    thick=[b for b in bands if b>max(18,med*2.2)]
    return dict(ink_pct=round(total*100,2), rules_h=hl, rules_v=vl,
                max_band=grande if (grande:=max(bands,default=0)) else 0,
                n_thick=len(thick))

def classify(f):
    if f['ink_pct']<1.5: return 'blank',''
    conf=[]
    if f['rules_h']>=2 and f['rules_v']>=2: conf.append('table')
    if f['n_thick']>=1: conf.append('figure')
    if len(conf)==1: return conf[0],''
    if not conf:
        return ('suspect-text','needs_eye') if f['rules_h']+f['rules_v']>0 else ('text','')
    return '+'.join(conf),''

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('book'); ap.add_argument('--pdf'); ap.add_argument('--dpi',type=int,default=80)
    a=ap.parse_args()
    root='/home/breathinglife/code/xuanxue'
    bdir=os.path.join(root,'books',a.book)
    pdf=a.pdf
    if not pdf:
        src=os.path.join(bdir,'sources')
        cands=[]
        for d,_,fs in os.walk(os.path.join(root,'sources')):
            for fn in fs:
                if fn.lower().endswith('.pdf') and any(k in fn for k in (a.book.split('-')[-1],)):
                    cands.append(os.path.join(d,fn))
        if len(cands)!=1:
            print('无法唯一定位 PDF，用 --pdf 指定。候选:',cands); sys.exit(2)
        pdf=cands[0]
    doc=fitz.open(pdf)
    outp=os.path.join(bdir,'img','pages.jsonl')
    stats={}
    with open(outp,'w') as w:
        for i in range(len(doc)):
            pix=doc[i].get_pixmap(dpi=a.dpi, colorspace=fitz.csGRAY)
            f=probe_page(pix)
            cls,note=classify(f)
            f.update(page=i+1,cls=cls,needs_eye=(note=='needs_eye'))
            w.write(json.dumps(f,ensure_ascii=False)+'\n')
            stats[cls]=stats.get(cls,0)+1
    doc.close()
    print('→',outp)
    for k,v in sorted(stats.items(),key=lambda x:-x[1]): print(f'  {k:14s} {v}')
if __name__=='__main__':
    main()

"""Export reviewed private slides and calibrated, uniquely assigned source speech."""
from pathlib import Path
import argparse, json, os, hashlib, html, re, base64

def clock(t):
    t=int(t);return f'{t//3600:02}:{t//60%60:02}:{t%60:02}'

def export(root):
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reader_primitives import p, styles
    os.umask(0o077)
    status=json.loads((root/'status.json').read_text())
    slides=json.loads((root/'slides.reviewed.json').read_text())['pages']
    transcript=json.loads((root/'transcript.reviewed.json').read_text())
    segments=transcript['segments']
    if not slides or not segments:raise ValueError('缺少已核对的PPT或报告文字')
    title=status['title'];who=status['speaker'];prefix=f'《{title}》_{who}'
    if any(ch in prefix for ch in '/\\\x00') or title in ('.','..') or who in ('.','..'):
        raise ValueError('报告标题和姓名不能含路径分隔符')
    ppt=root/(prefix+'_PPT.pdf');notes=root/(prefix+'_图文纪要.pdf')
    text=root/(prefix+'_音频文本.txt');srt=root/(prefix+'_音频字幕.srt')
    a=canvas.Canvas(str(ppt));a.setTitle(title);a.setAuthor(who)
    for item in slides:
        im=ImageReader(item['image']);w,h=im.getSize();a.setPageSize((w,h))
        a.drawImage(im,0,0,w,h);a.bookmarkPage('slide-'+str(item['page']))
        a.addOutlineEntry(item.get('title') or f'PPT {item["page"]}', 'slide-'+str(item['page']),0);a.showPage()
    a.save()
    used=[];pages=[]
    for i,item in enumerate(slides):
        end=item['end']
        intervals=item.get('intervals', [[item['start'], end]])
        ids=[s['id'] for s in segments if s.get('section','report')=='report'
             and any(a <= (s['start']+s['end'])/2 < b for a,b in intervals)]
        used.extend(ids);pages.append({**item,'end':end,'segment_ids':ids})
    assert len(used)==len(set(used))
    by={s['id']:s for s in segments}
    a=canvas.Canvas(str(notes));a.setTitle(title);a.setAuthor(who)
    for item in pages:
        W,H=420*mm,236.25*mm
        texts=[by[i]['text'] for i in item['segment_ids']]
        for size in [12,11.5,11,10.5,10,9.5]:
            styles['private']=styles['body'].clone('private',fontSize=size,leading=size*1.55)
            flow=[p(t,'private') for t in texts]
            tw=(W-28*mm)*.25
            total=sum(x.wrap(tw,H-20*mm)[1] for x in flow)+max(0,len(flow)-1)*6
            if total<=H-20*mm:break
        for _ in range(15):
            available=H-20*mm;pw=(W-28*mm)*.75;tw=(W-28*mm)*.25
            heights=[x.wrap(tw,available)[1] for x in flow]
            total=sum(heights)+max(0,len(flow)-1)*6
            if total<=available:break
            W*=1.10;H*=1.10
        assert total<=available
        a.setPageSize((W,H));im=ImageReader(item['image']);iw,ih=im.getSize()
        scale=min(pw/iw,available/ih);dw,dh=iw*scale,ih*scale
        a.drawImage(im,10*mm+(pw-dw)/2,10*mm+(available-dh)/2,dw,dh)
        right=10*mm+pw+8*mm;y=H-10*mm
        for para,height in zip(flow,heights):para.drawOn(a,right,y-height);y-=height+6
        a.bookmarkPage('slide-'+str(item['page']));a.addOutlineEntry(item.get('title') or f'PPT {item["page"]}','slide-'+str(item['page']),0);a.showPage()
    a.save()
    text.write_text('\n\n'.join(f'[{clock(s["start"])}—{clock(s["end"])}] '+s['text'] for s in segments)+'\n')
    def stamp(t):
        ms=round(t*1000);return clock(ms//1000)+f',{ms%1000:03}'
    srt.write_text('\n\n'.join(f'{i+1}\n{stamp(s["start"])} --> {stamp(s["end"])}\n{s["text"]}' for i,s in enumerate(segments))+'\n')
    alignment={'title':title,'speaker':who,'pages':pages,'segments':segments,
               'unassigned_segment_ids':[s['id'] for s in segments if s['id'] not in set(used)],
               'time_precision':'本地ASR段级时码；按时间中点主归属，一段讲述只配一次；未作词级对齐',
               'cloud_api_calls':False,'full_listening_verified':False}
    (root/'alignment.json').write_text(json.dumps(alignment,ensure_ascii=False,indent=2)+'\n')
    audio=next(root.glob('*_音频.m4a'))
    body=[]
    for page in pages:
        uri='data:image/jpeg;base64,'+base64.b64encode(Path(page['image']).read_bytes()).decode()
        paras=''.join(f'<p data-time="{by[i]["start"]}">{html.escape(by[i]["text"])}</p>' for i in page['segment_ids'])
        edit='\n\n'.join(by[i]['text'] for i in page['segment_ids'])
        ranges=html.escape(json.dumps(page.get('intervals',[[page['start'],page['end']]])),quote=True)
        body.append(f'<section data-start="{page["start"]}" data-end="{page["end"]}" data-intervals="{ranges}" id="p{page["page"]}"><img src="{uri}" alt="PPT {page["page"]}"><div><article>{paras}</article><textarea hidden>{html.escape(edit)}</textarea></div></section>')
    htmlfile=root/(prefix+'_图文纪要.html')
    css='''*{box-sizing:border-box}body{margin:0;background:#e8edf1;font-family:system-ui,sans-serif;padding:65px 16px 110px}header,footer{position:fixed;left:0;right:0;background:white;padding:12px 20px;z-index:5}header{top:0;display:flex;gap:12px;align-items:center}footer{bottom:0}audio{width:100%}section{display:grid;grid-template-columns:3fr 1fr;gap:24px;background:white;padding:22px;margin:18px auto;max-width:1600px;scroll-margin-top:70px}section img{width:100%;height:auto;position:sticky;top:80px}article{line-height:1.8;font-size:16px}p{cursor:pointer}textarea{width:100%;min-height:420px;font:inherit;line-height:1.8}button{padding:8px 12px}small{color:#555}@media(max-width:650px){body{padding:80px 8px 110px}section{display:block;padding:10px}section img{position:static}header{flex-wrap:wrap;font-size:13px}}@media print{header,footer{display:none}body{padding:0;background:white}section{break-before:page;margin:0}section img{position:static}}'''
    js='''const audio=document.querySelector('audio'),sections=[...document.querySelectorAll('section')];const key='private-reader-'+document.title;let editing=false;const saved=JSON.parse(localStorage.getItem(key)||'null');if(saved)sections.forEach((s,i)=>{if(typeof saved[i]==='string'){s.querySelector('textarea').value=saved[i];s.querySelector('article').textContent=saved[i]}});document.querySelector('#edit').onclick=()=>{editing=!editing;sections.forEach(s=>{s.querySelector('textarea').hidden=!editing;s.querySelector('article').hidden=editing});document.querySelector('#edit').textContent=editing?'结束编辑':'编辑文字'};sections.forEach(s=>{const t=s.querySelector('textarea');t.oninput=()=>{localStorage.setItem(key,JSON.stringify(sections.map(x=>x.querySelector('textarea').value)));s.querySelector('article').textContent=t.value}});document.querySelectorAll('p[data-time]').forEach(p=>p.onclick=()=>{audio.currentTime=Number(p.dataset.time);audio.pause()});let last=null;audio.ontimeupdate=()=>{if(editing||!document.querySelector('#follow').checked)return;const s=sections.find(s=>JSON.parse(s.dataset.intervals).some(([a,b])=>audio.currentTime>=a&&audio.currentTime<b));if(s&&s!==last){last=s;s.scrollIntoView({behavior:'smooth',block:'start'})}};document.querySelector('#download').onclick=()=>{const str=sections.map(s=>s.querySelector('textarea').value).join('\\n\\n');const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([str],{type:'text/plain;charset=utf-8'}));a.download=document.title+'_人工修改.txt';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};'''
    htmlfile.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+'_'+who+'</title><style>'+css+'</style><header><button id="edit">编辑文字</button><button id="download">导出修改文字</button><label><input id="follow" type="checkbox" checked>跟随音频翻页</label><small>本地阅读 · 修改仅保存于此浏览器 · 原音频需与HTML放在同目录</small></header>'+''.join(body)+'<footer><audio controls preload="metadata" src="'+html.escape(audio.name,quote=True)+'"></audio></footer><script>'+js+'</script></html>')
    deliverables=[ppt,notes,text,srt,htmlfile,audio]
    manifest={'title':title,'speaker':who,'confidential':True,'publicly_published':False,
              'files':[{'file':str(f),'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'bytes':f.stat().st_size} for f in deliverables],
              'ppt_pages':len(pages),'speech_segments':len(segments),'cloud_api_calls':False,
              'full_listening_verified':False,'reading_text_review':transcript.get('review')}
    (root/'delivery.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print('私密导出完成',len(pages),'页，',len(segments),'段文本',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path);a=p.parse_args();export(a.root)

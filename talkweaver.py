"""Agent-first TalkWeaver command interface. Private processing; no publishing."""
import argparse, hashlib, importlib.util, json, os, shutil, subprocess, sys
from pathlib import Path

SOURCE=Path(__file__).resolve().parent

def read(p):return json.loads(Path(p).read_text())
def save(p,d):
    p=Path(p);q=p.with_suffix(p.suffix+'.tmp');q.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');q.chmod(0o600);q.replace(p)
def digest(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()
def tools_python():
    local=SOURCE/'.venv/bin/python'
    return os.environ.get('TALKWEAVER_TOOLS_PYTHON',str(local) if local.exists() else sys.executable)
def call(script,args,tools=False):
    subprocess.run([tools_python() if tools else sys.executable,str(SOURCE/script),*map(str,args)],check=True,stdout=sys.stderr)

def initialize(args):
    root=args.root.resolve();media=args.media.resolve()
    if not media.is_file():raise ValueError('输入视频不存在')
    if root.exists() and any(root.iterdir()):raise ValueError('任务目录必须为空，已有任务用status或run接续')
    if root==media.parent or root in media.parents:raise ValueError('任务目录与输入目录需分开')
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(media)]))
    if not {'video','audio'}<={s['codec_type'] for s in probe['streams']}:raise ValueError('输入必须包含画面和音轨')
    root.mkdir(parents=True,exist_ok=True,mode=0o700);root.chmod(0o700)
    (root/'work').mkdir(mode=0o700)
    status={'input':str(media),'input_sha256':digest(media),'probe':probe,'title':args.title,
            'speaker':args.speaker,'language':args.language,'confidential':True,'cloud_api_calls':False,'state':'initialized',
            'asr_model':str(args.asr_model.resolve()) if args.asr_model else None,
            'text_model':str(args.text_model.resolve()) if args.text_model else None,
            'tessdata':str(args.tessdata.resolve()) if args.tessdata else None}
    save(root/'status.json',status)
    return {'state':'initialized','root':str(root),'next_action':'transcribe; then write plan.json with report_start/report_end, ppt_start/ppt_end and pixel roi [x,y,width,height]'}

def stage(root,action):
    s=read(root/'status.json');base=['--root',root]
    if action=='transcribe':
        if not s.get('asr_model'):raise ValueError('任务缺少本地asr_model配置')
        call('local_report_asr.py',base+['--model',s['asr_model']])
    elif action=='scan':
        p=read(root/'plan.json')
        call('local_report_slides.py',['scan',*base,'--start',p['ppt_start'],'--end',p['ppt_end'],'--roi',*p['roi']],True)
    elif action=='ocr':
        extra=['--tessdata',s['tessdata']] if s.get('tessdata') else []
        call('local_report_slides.py',['ocr',*base,*extra],True)
    elif action=='punctuate':
        if not s.get('text_model'):raise ValueError('任务缺少本地text_model配置；Agent可先人工校订prepared为reviewed并记录依据')
        if (root/'transcript.reviewed.json').exists():raise ValueError('已存在校订稿，拒绝覆盖；请新建修订任务')
        call('local_report_punctuation.py',base+['--model',s['text_model']])
    elif action=='export':
        if read(root/'transcript.reviewed.json').get('review',{}).get('state')!='reviewed':raise ValueError('需要Agent记录上下文校订，不能将补标点结果直接视为精校稿')
        if (root/'delivery.json').exists():raise ValueError('已有交付文件，拒绝覆盖；请新建修订任务')
        audio=root/'report_音频.m4a'
        if not audio.exists():
            tmp=audio.with_name('audio.tmp.m4a')
            subprocess.run(['ffmpeg','-v','error','-nostdin','-i',s['input'],'-vn','-c:a','aac','-b:a','128k','-movflags','+faststart','-y',str(tmp)],check=True)
            tmp.replace(audio)
        call('private_report_export.py',base)
    elif action=='verify':call('validate_private_report.py',base,True)
    return {'state':action+'_finished','root':str(root)}

def review_slides(root,decisions):
    if (root/'slides.reviewed.json').exists():raise ValueError('已有截图核对结果，请使用新修订任务')
    data=read(root/'work/slide-candidates.json');plan=read(root/'plan.json');decision=read(decisions)
    by={x['id']:x for x in data['items']};groups=decision['pages'];excluded=decision.get('excluded',[])
    all_ids=[i for g in groups for i in g['candidate_ids']]+[e['id'] for e in excluded]
    if len(all_ids)!=len(set(all_ids)) or set(all_ids)!=set(by):raise ValueError('必须逐个说明候选归属或排除原因，不能重复或遗漏')
    if not groups or any(not g.get('evidence') for g in groups) or any(not e.get('reason') for e in excluded):raise ValueError('缺少页面核对依据或排除理由')
    if [min(g['candidate_ids']) for g in groups]!=sorted(min(g['candidate_ids']) for g in groups):raise ValueError('页面必须按首次出现顺序排列')
    folder=root/'PPT图片';folder.mkdir(mode=0o700,exist_ok=True)
    result=[]
    for n,g in enumerate(groups,1):
        representative=g['selected_candidate'];members=g['candidate_ids']
        if representative not in members:raise ValueError('代表图必须来自该页成员')
        intervals=[]
        for member in sorted(members):
            idx=next(i for i,x in enumerate(data['items']) if x['id']==member)
            a=plan['report_start'] if idx==0 else by[member]['time']
            b=data['items'][idx+1]['time'] if idx+1<len(data['items']) else plan['report_end']
            a=max(a,plan['report_start']);b=min(b,plan['report_end'])
            if a<b:intervals.append([a,b])
        if not intervals:raise ValueError('页面在报告讲述区间外，请修订plan或明确排除')
        target=folder/f'{n:03}.jpg'
        if target.exists() and digest(target)!=digest(by[representative]['image']):raise ValueError('部分截图结果与新决策冲突，请建立修订任务')
        shutil.copyfile(by[representative]['image'],target);target.chmod(0o600)
        result.append({'page':n,'title':g.get('title',f'PPT {n}'),'image':str(target),
             'start':intervals[0][0],'end':intervals[-1][1],'intervals':intervals,
             'candidate_ids':members,'selected_candidate':representative,'review':g['evidence']})
    save(root/'slides.reviewed.json',{'pages':result,'excluded':excluded,'reviewer':'agent','cloud_api_calls':False})
    return {'state':'slides_reviewed','pages':len(result),'next_action':'prepare'}

def prepare(root):
    target=root/'transcript.prepared.json'
    if target.exists():raise ValueError('已有文字准备稿，拒绝覆盖Agent修订')
    raw=read(root/'transcript.raw.json');plan=read(root/'plan.json');pages=read(root/'slides.reviewed.json')['pages']
    start,end=plan['report_start'],plan['report_end']
    if not 0<=start<end<=raw['duration']+.1:raise ValueError('报告时段越界')
    selected=[s for s in raw['segments'] if start<=s['start']<end]
    if not selected:raise ValueError('报告时段没有识别文字，请检查音轨和边界')
    paragraphs=[];group=[];previous=None
    def owner(s):
        mid=(s['start']+s['end'])/2
        return next((p['page'] for p in pages if any(a<=mid<b for a,b in p['intervals'])),None)
    def append(g):
        paragraphs.append({'id':len(paragraphs),'start':g[0]['start'],'end':g[-1]['end'],
          'text':''.join(s['text'] for s in g),'raw_text':''.join(s['raw_text'] for s in g),
          'source_segment_ids':[s['id'] for s in g],'section':'report','ppt_page':owner(g[0]),
          'quality_flags':sorted({f for s in g for f in s.get('quality_flags',[])})})
    for s in selected:
        pg=owner(s)
        if group and (pg!=previous or sum(len(x['text']) for x in group)>=160 or s['start']-group[-1]['end']>1.6):append(group);group=[]
        group.append(s);previous=pg
    if group:append(group)
    save(target,{'segments':paragraphs,'report_start':start,'report_end':end,'duration':raw['duration'],
      'included_source_segment_ids':[s['id'] for s in selected],
      'review':{'state':'needs_contextual_review','full_listening_verified':False,'raw_asr_retained':True}})
    return {'state':'text_prepared','paragraphs':len(paragraphs),'next_action':'punctuate, then Agent reviews text against PPT; preserve source_segment_ids and audit edits'}

def run(root):
    if (root/'delivery.json').exists():
        return stage(root,'verify')
    if not (root/'transcript.raw.json').exists():stage(root,'transcribe')
    if not (root/'plan.json').exists():return {'state':'needs_report_review','next_action':'Agent inspects transcript and original frames, writes plan.json'}
    if not (root/'work/slide-candidates.json').exists():stage(root,'scan')
    if not (root/'slides.reviewed.json').exists():
        stage(root,'ocr');return {'state':'needs_slide_review','next_action':'Agent compares candidate images and OCR, writes decisions.json, calls review-slides'}
    if not (root/'transcript.prepared.json').exists():return prepare(root)
    if not (root/'transcript.reviewed.json').exists():return {'state':'needs_text_review','next_action':'Agent reviews prepared text or calls punctuate; writes transcript.reviewed.json with review.state=reviewed'}
    if read(root/'transcript.reviewed.json').get('review',{}).get('state')!='reviewed':return {'state':'needs_text_review','next_action':'Agent checks terms, omissions, repetitions and quality_flags; records edits and sets review.state=reviewed'}
    stage(root,'export');return stage(root,'verify')

def main():
    os.umask(0o077)
    p=argparse.ArgumentParser(description='TalkWeaver — agent-first video report processing')
    sub=p.add_subparsers(dest='action',required=True)
    sub.add_parser('doctor')
    a=sub.add_parser('init');a.add_argument('--root',type=Path,required=True);a.add_argument('--media',type=Path,required=True)
    a.add_argument('--title',required=True);a.add_argument('--speaker',required=True)
    a.add_argument('--language',default='zh',help='Whisper language code, or auto')
    for name in ['asr-model','text-model','tessdata']:a.add_argument('--'+name,type=Path)
    for name in ['status','run','transcribe','scan','ocr','prepare','punctuate','export','verify','review-slides']:
        a=sub.add_parser(name);a.add_argument('--root',type=Path,required=True)
        if name=='review-slides':a.add_argument('--decisions',type=Path,required=True)
    args=p.parse_args()
    task_lock=None
    try:
        if args.action not in ('doctor','init','status'):
            import fcntl
            task_lock=(args.root/'work/.talkweaver.lock').open('a')
            try:fcntl.flock(task_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('另一个Agent正在处理该任务，请读取status，不要并行修改同一任务')
        if args.action=='doctor':
            result={'python':sys.executable,'tools_python':tools_python(),'binaries':{x:shutil.which(x) for x in ['ffmpeg','ffprobe','tesseract']},
              'python_modules':{x:bool(importlib.util.find_spec(x)) for x in ['torch','transformers','soundfile','reportlab','cv2']},'network_ai_default':False}
        elif args.action=='init':result=initialize(args)
        else:
            root=args.root.resolve()
            if args.action=='status':result=read(root/'status.json')
            elif args.action=='run':result=run(root)
            elif args.action=='prepare':result=prepare(root)
            elif args.action=='review-slides':result=review_slides(root,args.decisions)
            else:result=stage(root,args.action)
        print(json.dumps(result,ensure_ascii=False));return 0
    except (ValueError,OSError,KeyError,subprocess.CalledProcessError) as e:
        print(json.dumps({'state':'error','error':str(e)},ensure_ascii=False));return 1
    finally:
        if task_lock:task_lock.close()

if __name__=='__main__':raise SystemExit(main())

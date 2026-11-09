"""Local-only slide candidate extraction for a reviewed fixed video layout."""
import argparse, os, json, subprocess, time, hashlib
from pathlib import Path
import cv2
import numpy as np

def save(p, d):
    q = p.with_suffix(p.suffix+'.tmp')
    q.write_text(json.dumps(d, ensure_ascii=False, indent=2)+'\n'); q.replace(p)

def scan(root, start, end, roi, fps=2):
    os.umask(0o077)
    assert (root/'transcript.raw.json').exists(), '先完成全音频转写再提取报告PPT'
    status=json.loads((root/'status.json').read_text())
    x,y,w,h=roi
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',status['input']]))
    video=next(s for s in probe['streams'] if s['codec_type']=='video')
    if not (0<=start<end<=float(probe['format']['duration'])+.1 and fps>0 and x>=0 and y>=0 and w>0 and h>0 and x+w<=video['width'] and y+h<=video['height']):
        raise ValueError('视频时段、采样率或PPT裁剪范围无效')
    identity={'input_sha256':hashlib.sha256(Path(status['input']).read_bytes()).hexdigest(),'start':start,'end':end,'roi':roi,'fps':fps}
    if identity['input_sha256']!=status['input_sha256']:raise ValueError('输入已变化，请创建新任务')
    prior=root/'work/slide-candidates.json'
    if prior.exists():
        old=json.loads(prior.read_text())
        if old.get('identity')!=identity:raise ValueError('截图缓存参数不同或身份不明，请使用新任务')
        if any(not Path(i['image']).is_file() for i in old['items']):raise ValueError('截图缓存缺失，请使用新任务')
        print('复用已完成的变化扫描',len(old['items']),'张');return
    folder=root/'work'/'slide-candidates';folder.mkdir(exist_ok=True,mode=0o700)
    command=['ffmpeg','-v','error','-nostdin','-threads','2','-ss',str(start),
             '-i',status['input'],'-t',str(end-start),'-vf',f'fps={fps},format=rgb24,crop={w}:{h}:{x}:{y}:exact=1',
             '-f','rawvideo','-pix_fmt','bgr24','pipe:1']
    items=[];previous=last=None;stable=0;last_saved=-100;n=0
    cv2.setNumThreads(1)
    with (root/'work'/'slides-decode.log').open('w') as log:
        proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=log)
        while True:
            raw=proc.stdout.read(w*h*3)
            if len(raw)!=w*h*3:break
            frame=np.frombuffer(raw,dtype=np.uint8).reshape(h,w,3)
            small=cv2.resize(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY),(320,180))
            if previous is not None:
                d=cv2.absdiff(small,previous)
                stable=stable+1 if (d>18).mean()<.012 and d.mean()<1.1 else 0
            previous=small.copy()
            delta=cv2.absdiff(small,last) if last is not None else None
            changed=last is None or ((delta>18).mean()>.012 and delta.mean()>1.2)
            if stable>=1 and changed and n-last_saved>=2:
                name=f'{len(items)+1:04d}_{start+n/fps:010.3f}.jpg'
                path=folder/name
                cv2.imwrite(str(path),frame,[cv2.IMWRITE_JPEG_QUALITY,98]);path.chmod(0o600)
                items.append({'id':len(items)+1,'time':round(start+n/fps,3),
                              'image':str(path),'review':'pending','roi':roi})
                last=small.copy();last_saved=n
            n+=1
            if n%120==0:
                save(root/'work'/'slide-scan-status.json',{'state':'scanning',
                     'seconds':start+n/fps,'candidates':len(items),'updated_at':time.time()})
        code=proc.wait()
    assert code==0
    if not items:raise ValueError('未提取到稳定画面；保留解码记录，请检查版式和时段')
    save(root/'work'/'slide-candidates.json',{'items':items,'start':start,'end':end,'identity':identity,
                 'fps':fps,'roi':roi,'decoded_frames':n,'cloud_api_calls':False})
    print('本地变化扫描完成',len(items),'张候选',flush=True)

def ocr(root,tessdata=None):
    from concurrent.futures import ThreadPoolExecutor
    data=json.loads((root/'work'/'slide-candidates.json').read_text())
    folder=root/'work'/'ocr';folder.mkdir(exist_ok=True,mode=0o700)
    tess=tessdata or os.environ.get('TESSDATA_PREFIX')
    extra=['--tessdata-dir',str(tess)] if tess else []
    def one(item):
        p=folder/f'{item["id"]:04}.json'
        identity=hashlib.sha256(Path(item['image']).read_bytes()).hexdigest()
        if p.exists():
            if json.loads(p.read_text()).get('image_sha256')!=identity:raise ValueError('OCR缓存图片已变化或缺少身份，请使用新任务')
            return
        img=cv2.imread(item['image']);h,w=img.shape[:2]
        env={**os.environ,'OMP_THREAD_LIMIT':'1'}
        text=subprocess.run(['tesseract',item['image'],'stdout',*extra,
                    '-l','chi_sim+eng','--psm','11'],capture_output=True,text=True,check=True,env=env).stdout
        # Unknown layouts do not have a universally valid page-number region.
        save(p,{'candidate':item['id'],'text':text,'footer_page':None,'image_sha256':identity})
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(one,data['items']))
    print('本地OCR完成',len(data['items']),'张',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['scan','ocr']);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--start',type=float);p.add_argument('--end',type=float);p.add_argument('--roi',nargs=4,type=int);p.add_argument('--tessdata')
    a=p.parse_args()
    if a.action=='scan':scan(a.root,a.start,a.end,a.roi)
    else:ocr(a.root,a.tessdata)

"""Restore punctuation locally while mechanically preserving approved source words."""
import os
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
from pathlib import Path
import argparse,json,re,difflib,time

PUNCT=set('，。！？；：、,.!?;:「」『』《》“”‘’"\'（）()…—\n\r\t ')
def parts(text):
    content=[];punct={}
    for ch in text:
        if ch in PUNCT:punct[len(content)]=punct.get(len(content),'')+ch
        else:content.append(ch)
    return ''.join(content),punct

def project(original,generated):
    a,old=parts(original);b,new=parts(generated)
    matcher=difflib.SequenceMatcher(None,a,b,autojunk=False)
    if matcher.ratio()<.85:return original+'。',False
    mapping={}
    for block in matcher.get_matching_blocks():
        for j in range(block.size):mapping[block.b+j]=block.a+j
    inserts={}
    for position,value in new.items():
        if position and position-1 in mapping:
            dest=mapping[position-1]+1
            value=value.strip().replace(',', '，').replace(';','；').replace('!','！').replace('?','？')
            if value and all(ch in '。，！？；：、“”《》（）' for ch in value):
                inserts[dest]=value
    for position,value in old.items():
        # Keep punctuation already present in the approved source, including decimal points.
        if value.strip():inserts[position]=value.strip()
        elif value==' ' and position>0 and position<len(a) and a[position-1].isascii() and a[position].isascii():
            inserts[position]=' '
    result=''.join(ch+inserts.get(i+1,'') for i,ch in enumerate(a))
    for left,right in [('“','”'),('《','》'),('（','）')]:
        if result.count(left)!=result.count(right):result=result.replace(left,'').replace(right,'')
    if result and result[-1] not in '。！？；：':result+='。'
    assert parts(result)[0]==a
    return result,True

def run(root, modeldir=None):
    import torch
    from transformers import AutoTokenizer,AutoModelForCausalLM
    os.umask(0o077)
    file=root/'transcript.prepared.json';data=json.loads(file.read_text());segments=data['segments']
    modeldir=modeldir or os.environ.get('TALKWEAVER_TEXT_MODEL')
    if not modeldir:raise ValueError('请通过--model或TALKWEAVER_TEXT_MODEL指定本地模型')
    device='cuda' if torch.cuda.is_available() else 'cpu'
    tok=AutoTokenizer.from_pretrained(modeldir,local_files_only=True,padding_side='left')
    model=AutoModelForCausalLM.from_pretrained(modeldir,local_files_only=True,dtype=torch.float16 if device=='cuda' else torch.float32,
                    attn_implementation='sdpa').to(device)
    cache=root/'work/punctuation-v2';cache.mkdir(exist_ok=True,mode=0o700)
    for j in range(0,len(segments),8):
        batch=segments[j:j+8];pending=[]
        for s in batch:
            path=cache/f'{s["id"]:04}.json'
            if path.exists():
                cached=json.loads(path.read_text())
                if cached['source']!=s['text'] or cached.get('model')!=str(modeldir):
                    raise ValueError('标点缓存的文字或模型已变化，请保留旧任务并新建修订任务')
            else:pending.append(s)
        if not pending:continue
        prompts=[tok.apply_chat_template([
            {'role':'system','content':'你负责恢复语音转写的标点。必须把长句断开，添加逗号、句号、问号和冒号，让文字自然易读。保留原文内容，不要摘要或解释。只输出补好标点的文字。'},
            {'role':'user','content':'大家好今天我们介绍一个模型我们先采集数据然后训练模型大家可能会问为什么这样做因为数据类型很多'},
            {'role':'assistant','content':'大家好，今天我们介绍一个模型。我们先采集数据，然后训练模型。大家可能会问，为什么这样做？因为数据类型很多。'},
            {'role':'user','content':s['text']}],tokenize=False,add_generation_prompt=True,enable_thinking=False) for s in pending]
        inputs=tok(prompts,return_tensors='pt',padding=True).to(device)
        with torch.inference_mode():
            out=model.generate(**inputs,max_new_tokens=440,do_sample=False,pad_token_id=tok.pad_token_id)
        decoded=tok.batch_decode(out[:,inputs.input_ids.shape[1]:],skip_special_tokens=True)
        for s,t in zip(pending,decoded):
            text,accepted=project(s['text'],t.strip())
            (cache/f'{s["id"]:04}.json').write_text(json.dumps({'id':s['id'],'source':s['text'],
                'generated':t,'text':text,'model':str(modeldir),'punctuation_projected':accepted,
                'approved_words_preserved':parts(s['text'])[0]==parts(text)[0]},ensure_ascii=False,indent=2))
        print('本地标点校对',min(j+8,len(segments)),'/',len(segments),flush=True)
    accepted=0
    for s in segments:
        p=json.loads((cache/f'{s["id"]:04}.json').read_text());assert p['source']==s['text']
        s['text_before_punctuation']=s['text'];s['text']=p['text'];accepted+=p['punctuation_projected']
    data['review']['punctuation']={'engine':'local Qwen3-1.7B','paragraphs':len(segments),
             'projected':accepted,'fallback':len(segments)-accepted,'approved_word_sequence_preserved':True}
    (root/'transcript.reviewed.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print('本地标点校对完成，原文字序核验通过',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--model');a=p.parse_args();run(a.root,a.model)

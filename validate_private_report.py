"""Validate private report exports without publishing or calling external services."""
from pathlib import Path
import argparse,json,hashlib,re,collections,subprocess,time
import pymupdf as fitz

def verify(root):
    d=json.loads((root/'delivery.json').read_text())
    a=json.loads((root/'alignment.json').read_text())
    source=json.loads((root/'transcript.raw.json').read_text())
    reviewed=json.loads((root/'transcript.reviewed.json').read_text())
    status=json.loads((root/'status.json').read_text())
    assert hashlib.sha256(Path(status['input']).read_bytes()).hexdigest()==status['input_sha256']
    assert d['confidential'] and not d['publicly_published'] and not d['cloud_api_calls']
    ids=[i for s in a['segments'] for i in s['source_segment_ids']]
    start=reviewed.get('report_start',min(s['start'] for s in a['segments']))
    end=reviewed.get('report_end',max(s['end'] for s in a['segments']))
    expected=reviewed.get('included_source_segment_ids')
    if expected is None:expected=[s['id'] for s in source['segments'] if start<=s['start']<end]
    assert len(expected)==len(set(expected)) and set(expected)<={s['id'] for s in source['segments']}
    assert sorted(ids)==expected and len(ids)==len(set(ids))
    used=[i for p in a['pages'] for i in p['segment_ids']]
    assert len(used)==len(set(used)) and set(used)<={s['id'] for s in a['segments']}
    assert set(a['unassigned_segment_ids'])=={s['id'] for s in a['segments']}-set(used)
    segments={s['id']:s for s in a['segments']}
    norm=lambda t:re.sub(r'\s+','',t)
    pdfs=[Path(f['file']) for f in d['files'] if f['file'].endswith('.pdf')]
    for file in pdfs:
        doc=fitz.open(file);assert len(doc)==len(a['pages'])>0 and len(doc.get_toc())==len(a['pages'])
        assert doc.embfile_count()==0
        is_notes=file.name.endswith('_图文纪要.pdf')
        for p,item in zip(doc,a['pages']):
            info=p.get_image_info(hashes=True);assert len(info)==1
            assert info[0]['digest']==hashlib.md5(fitz.Pixmap(item['image']).samples).digest()
            expected_text=''.join(segments[i]['text'] for i in item['segment_ids']) if is_notes else ''
            assert norm(p.get_text())==norm(expected_text),(file.name,item['page'])
            if is_notes:assert abs(p.rect.width/p.rect.height-16/9)<.001
            assert not p.get_links() and not list(p.annots() or [])
            if is_notes:
                assert info[0]['bbox'][2]<p.rect.width*.74
                for word in p.get_text('words'):
                    assert word[0]>p.rect.width*.74 and word[2]<p.rect.width-8
                    assert word[1]>=0 and word[3]<=p.rect.height
            p.get_pixmap(matrix=fitz.Matrix(.15,.15),alpha=False)
        for n in sorted({0,len(doc)//2,len(doc)-1}):
            if is_notes:doc[n].get_pixmap(matrix=fitz.Matrix(.9,.9),alpha=False).save(root/'work'/f'preview-{n+1}.png')
    for item in d['files']:
        p=Path(item['file']);assert hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']
    txt=next(Path(f['file']) for f in d['files'] if f['file'].endswith('_音频文本.txt'))
    text=txt.read_text();assert len(re.findall(r'^\[\d{2,}:\d{2}:\d{2}—',text,re.M))==len(a['segments'])
    assert not re.search(r'(.)\1{8,}',text) and '�' not in text
    h=next(Path(f['file']) for f in d['files'] if f['file'].endswith('.html')).read_text()
    assert h.count('<section ')==len(a['pages']) and h.count('<audio ')==1
    assert not re.search(r'(?:src|href)=[\"\']https?://',h)
    assert str(root) not in h
    audio=next(Path(f['file']) for f in d['files'] if f['file'].endswith('.m4a'))
    subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(audio),'-f','null','-'],check=True,capture_output=True)
    result={'at':time.time(),'ppt_pages':len(a['pages']),'notes_pages':len(a['pages']),'source_report_segments':len(expected),
       'reading_paragraphs':len(a['segments']),'source_segment_coverage_preserved_without_duplication':True,
       'unassigned_paragraphs_retained_in_full_transcript':len(a['unassigned_segment_ids']),
       'original_video_sha256_unchanged':True,'original_cropped_images_preserved':True,
       'all_pdf_pages_decode':True,'no_auxiliary_pdf_text':True,'files_hash_verified':True,
       'audio_complete_decode':True,'html_has_one_local_audio_player':True,
       'local_only':True,'publicly_published':False,'human_full_listening_verified':False}
    d['validation']=result;(root/'delivery.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
    status.update(state='complete',deliverables=str(root/'delivery.json'),validation=result,updated_at=time.time())
    (root/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path);verify(p.parse_args().root)

"""Synthetic regression checks; no private reports, model inference or network use."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path


class AgentFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='talkweaver-test-')
        cls.base=Path(cls.tmp.name);cls.media=cls.base/'input.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=white:s=640x480:r=10',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=16000','-t','2','-c:v','libx264',
            '-pix_fmt','yuv420p','-c:a','aac',str(cls.media)],check=True)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def cli(self,*args,ok=True):
        r=subprocess.run([sys.executable,'-m','talkweaver',*map(str,args)],capture_output=True,text=True)
        if ok:self.assertEqual(r.returncode,0,r.stderr+r.stdout)
        else:self.assertNotEqual(r.returncode,0,r.stderr+r.stdout)
        return json.loads(r.stdout)
    def test_agent_review_and_one_page_export(self):
        job=self.base/'job'
        self.cli('init','--root',job,'--media',self.media,'--title','Synthetic report','--speaker','Example','--language','en')
        raw={'duration':2,'segments':[
          {'id':0,'start':.6,'end':.9,'text':'The URL is https://example.test.','raw_text':'The URL is https://example.test.'},
          {'id':1,'start':1.2,'end':1.8,'text':'This includes [brackets].','raw_text':'This includes [brackets].'}]}
        (job/'transcript.raw.json').write_text(json.dumps(raw))
        self.assertEqual(self.cli('run','--root',job)['state'],'needs_report_review')
        plan={'report_start':0,'report_end':2,'ppt_start':0,'ppt_end':2,'roi':[0,0,321,241]}
        (job/'plan.json').write_text(json.dumps(plan))
        self.cli('scan','--root',job)
        data=json.loads((job/'work/slide-candidates.json').read_text());self.assertEqual(len(data['items']),1)
        self.cli('scan','--root',job)  # Same parameters reuse the completed cache.
        plan['roi']=[0,0,322,241];(job/'plan.json').write_text(json.dumps(plan))
        self.cli('scan','--root',job,ok=False)
        plan['roi']=[0,0,321,241];(job/'plan.json').write_text(json.dumps(plan))
        from PIL import Image
        with Image.open(data['items'][0]['image']) as image:self.assertEqual(image.size,(321,241))
        decisions={'pages':[{'candidate_ids':[1],'selected_candidate':1,'title':'Synthetic slide','evidence':'Synthetic constant frame checked'}],'excluded':[]}
        file=self.base/'decisions.json';file.write_text(json.dumps({'pages':[],'excluded':[]}))
        self.cli('review-slides','--root',job,'--decisions',file,ok=False)
        file.write_text(json.dumps(decisions))
        self.cli('review-slides','--root',job,'--decisions',file);self.cli('prepare','--root',job)
        prepared=json.loads((job/'transcript.prepared.json').read_text())
        (job/'transcript.reviewed.json').write_text(json.dumps(prepared))
        self.cli('export','--root',job,ok=False)
        prepared['review']['state']='reviewed';prepared['review']['evidence']='Synthetic text matches seeded input'
        (job/'transcript.reviewed.json').write_text(json.dumps(prepared))
        self.cli('export','--root',job);self.cli('verify','--root',job)
        delivered=json.loads((job/'delivery.json').read_text())
        self.assertEqual(delivered['validation']['ppt_pages'],1)
        self.assertEqual(delivered['validation']['source_report_segments'],2)
        self.cli('export','--root',job,ok=False)
        # A same-length source replacement must invalidate the existing output.
        changed=self.media.read_bytes();self.media.write_bytes(changed[:-1]+bytes([changed[-1]^1]))
        self.cli('verify','--root',job,ok=False);self.media.write_bytes(changed)
    def test_missing_candidate_and_invalid_roi(self):
        job=self.base/'bad-job'
        self.cli('init','--root',job,'--media',self.media,'--title','Other','--speaker','Example')
        self.cli('init','--root',job,'--media',self.media,'--title','Other','--speaker','Example',ok=False)
        (job/'transcript.raw.json').write_text(json.dumps({'duration':2,'segments':[]}))
        (job/'plan.json').write_text(json.dumps({'report_start':0,'report_end':2,'ppt_start':0,'ppt_end':2,'roi':[600,0,100,200]}))
        self.cli('scan','--root',job,ok=False)
    def test_punctuation_preserves_decimal_and_letters(self):
        from talkweaver.local_report_punctuation import project,parts
        original='准确率94.38%使用PID控制'
        result,_=project(original,'准确率是94.38%，使用PID控制。')
        self.assertEqual(parts(result)[0],parts(original)[0]);self.assertIn('94.38%',result)

if __name__=='__main__':unittest.main()

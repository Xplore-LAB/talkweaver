"""Resumable on-device ASR using pre-downloaded local weights; no uploads."""
import os
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
from pathlib import Path
import argparse, json, time, subprocess, hashlib

def save(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)

def run(root, model_dir, chunk_seconds=180):
    import numpy as np
    import soundfile as sf
    import torch
    from transformers import AutoProcessor, AutoModelForSpeechSeq2Seq, pipeline
    os.umask(0o077)
    root = Path(root)
    work = root / 'work'
    work.mkdir(exist_ok=True, mode=0o700)
    status = json.loads((root / 'status.json').read_text())
    language=status.get('language','zh')
    actual=hashlib.sha256(Path(status['input']).read_bytes()).hexdigest()
    if actual!=status['input_sha256']:raise ValueError('输入视频已变化，请创建新任务')
    identity={'input_sha256':actual,'model':str(Path(model_dir).resolve()),'chunk_seconds':chunk_seconds,'language':language,'decoder':'sequential-v1'}
    cache_meta=work/'asr-cache-identity.json'
    if cache_meta.exists() and json.loads(cache_meta.read_text())!=identity:
        raise ValueError('ASR缓存的输入或参数不同，请使用新任务目录')
    if not cache_meta.exists() and (work/'asr-sequential').exists():
        raise ValueError('旧ASR缓存缺少身份信息，保留旧任务并新建目录')
    save(cache_meta,identity)
    wav = work / 'speech-16k.wav'
    if not wav.exists():
        temporary=wav.with_name('speech-16k.tmp.wav')
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', status['input'],
                        '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', '-y', str(temporary)], check=True)
        temporary.replace(wav)
    status.update(state='loading_local_model', model=str(model_dir), cloud_api_calls=False)
    save(root / 'status.json', status)
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    model = AutoModelForSpeechSeq2Seq.from_pretrained(model_dir, local_files_only=True,
                dtype=dtype, use_safetensors=True, attn_implementation='sdpa')
    model.to('cuda:0' if torch.cuda.is_available() else 'cpu')
    processor = AutoProcessor.from_pretrained(model_dir, local_files_only=True)
    asr = pipeline('automatic-speech-recognition', model=model,
            tokenizer=processor.tokenizer, feature_extractor=processor.feature_extractor,
            device=0 if torch.cuda.is_available() else -1,
            batch_size=1)
    audio, sr = sf.read(wav, dtype='float32')
    assert sr == 16000 and audio.ndim == 1
    cache = work / 'asr-sequential'
    cache.mkdir(exist_ok=True, mode=0o700)
    total = (len(audio) + chunk_seconds * sr - 1) // (chunk_seconds * sr)
    for i in range(total):
        target = cache / f'{i:04}.json'
        start = i * chunk_seconds
        end = min(len(audio) / sr, start + chunk_seconds)
        if target.exists():
            continue
        status.update(state='local_transcribing', completed_chunks=i, total_chunks=total,
                      processed_seconds=start, updated_at=time.time())
        save(root / 'status.json', status)
        began = time.time()
        result = asr({'raw': audio[int(start*sr):int(end*sr)], 'sampling_rate': sr},
                     return_timestamps=True,
                     generate_kwargs={**({'language':language} if language!='auto' else {}), 'task': 'transcribe', 'num_beams': 1,
                                      'condition_on_prev_tokens': False})
        save(target, {'start': start, 'end': end, 'result': result,
                      'elapsed': time.time()-began, 'engine': 'local Whisper','model':str(model_dir)})
        print(f'本地转写 {i+1}/{total}；已处理 {end:.1f} 秒；本段耗时 {time.time()-began:.1f} 秒', flush=True)
    segments = []
    for i in range(total):
        item = json.loads((cache / f'{i:04}.json').read_text())
        for chunk in item['result'].get('chunks', []):
            a, b = chunk['timestamp']
            a = item['start'] + (a if a is not None else 0)
            b = item['start'] + (b if b is not None else item['end']-item['start'])
            if chunk['text'].strip():
                import re
                flags=[]
                if re.search(r'(.)\1{8,}',chunk['text']):flags.append('repeated_characters')
                if '\ufffd' in chunk['text']:flags.append('invalid_unicode')
                if None in chunk['timestamp'] or not item['start']<=a<min(b,item['end'])<=item['end']:flags.append('uncertain_timestamp')
                segments.append({'id': len(segments), 'start': a, 'end': min(b,item['end']),
                                 'text': chunk['text'].strip(), 'raw_text': chunk['text'].strip(),'quality_flags':flags})
    save(root / 'transcript.raw.json', {'segments': segments, 'duration': len(audio)/sr,
            'engine': 'local Whisper', 'model':str(model_dir),'language':language,'cloud_api_calls': False,
            'full_listening_verified': False, 'chunk_seconds': chunk_seconds})
    status.update(state='local_asr_complete', completed_chunks=total,
                  processed_seconds=len(audio)/sr, segment_count=len(segments), updated_at=time.time())
    save(root / 'status.json', status)
    print('本地全文转写完成', len(segments), '段', flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--model', required=True, type=Path)
    args = parser.parse_args()
    run(args.root, args.model)

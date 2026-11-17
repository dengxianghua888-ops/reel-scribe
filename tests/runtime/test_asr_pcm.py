"""Real PCM bytes and fake inference; not recognition-quality acceptance."""
import hashlib
import json
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import wave
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'runtime'))
import asr_ops
import numpy as np


def wav(path,rate=16000,channels=1,width=2):
    with wave.open(str(path),'wb') as w:
        w.setnchannels(channels);w.setsampwidth(width);w.setframerate(rate)
        w.writeframes(struct.pack('<hhhh',-32768,-1,0,32767))
    return ref(path)


def ref(path):
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def test_exact_pcm(tmp_path):
    result=asr_ops.recognition_pcm(wav(tmp_path/'input.wav'))
    assert result.dtype==np.float32 and result.ndim==1
    np.testing.assert_array_equal(result,np.array([-1,-1/32768,0,32767/32768],dtype=np.float32))


@pytest.mark.parametrize('kwargs',[{'rate':8000},{'channels':2},{'width':1}])
def test_bad_format(tmp_path,kwargs):
    with pytest.raises(ValueError,match='ASR_PCM_FORMAT_INVALID'):asr_ops.recognition_pcm(wav(tmp_path/'bad.wav',**kwargs))


def test_truncated_pcm_even_with_rehashed_file(tmp_path):
    p=tmp_path/'cut.wav';wav(p);data=p.read_bytes()[:-2]
    # Container is self-consistent but its data chunk still promises more frames.
    data=data[:4]+struct.pack('<I',len(data)-8)+data[8:];p.write_bytes(data)
    with pytest.raises(ValueError,match='FRAMES_INCOMPLETE'):asr_ops.recognition_pcm(ref(p))


def test_changed_bytes(tmp_path):
    p=tmp_path/'changed.wav';r=wav(p);p.write_bytes(p.read_bytes()[:-2])
    with pytest.raises(ValueError):asr_ops.recognition_pcm(r)


@pytest.mark.parametrize('mutate',[False,True])
def test_transcribe_passes_array_not_path(tmp_path,monkeypatch,mutate):
    source=tmp_path/'source.wav';source_ref=wav(source);out=tmp_path/'output';out.mkdir()
    monkeypatch.setattr(asr_ops,'verify_model',lambda r:(r,{'revision':'fixture'},tmp_path))
    monkeypatch.setattr(asr_ops,'verify_environment',lambda r:(r,{}))
    received=[]
    class Engine:
        def __init__(self,*a,**kw):assert kw['local_files_only'] is True
        def transcribe(self,audio,**kw):
            assert isinstance(audio,np.ndarray) and audio.dtype==np.float32
            np.testing.assert_array_equal(audio,[-1,-1/32768,0,32767/32768]);received.append(audio)
            assert kw['word_timestamps'] is True
            if mutate:(out/'recognition-input.wav').write_bytes(b'changed during inference')
            return iter([]),SimpleNamespace(language='zh')
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=Engine))
    class Tools:
        def probe(self,p):return {'duration':1,'streams':[{'index':0,'codec_type':'audio'}]}
        def ff(self,args):wav(Path(args[-1]))
    q={'operation':'speech-recognize','source':source_ref,'audio_stream':0,'start':0,'end':1,
       'model_lock':{},'environment_lock':{},'language':'zh','beam_size':1,'vad_filter':False,
       'condition_on_previous_text':False,'cpu_threads':1}
    if mutate:
        with pytest.raises(ValueError):asr_ops.transcribe(q,out,Tools())
        assert (out/'raw-observation.json').exists() and not (out/'asr-result.json').exists()
        return
    result=asr_ops.transcribe(q,out,Tools())
    assert received and result['state']=='NO_WORDS_DETECTED' and result['editorial_decisions']=='NONE'
    binding=json.loads((out/'input-binding.json').read_text())
    assert binding['audio']==ref(out/'recognition-input.wav')


def test_bytes_changed_between_hash_and_read(tmp_path,monkeypatch):
    p=tmp_path/'race.wav';r=wav(p);old=Path.read_bytes
    monkeypatch.setattr(Path,'read_bytes',lambda self:old(self)[:-2] if self==p else old(self))
    with pytest.raises(ValueError,match='ASR_PCM_IDENTITY_CHANGED'):asr_ops.recognition_pcm(r)


def test_declared_container_truncated(tmp_path):
    p=tmp_path/'cut.wav';wav(p);p.write_bytes(p.read_bytes()[:-1])
    with pytest.raises(ValueError,match='ASR_PCM_CONTAINER_INVALID'):asr_ops.recognition_pcm(ref(p))


def resized(data):
    return data[:4]+struct.pack('<I',len(data)-8)+data[8:]

@pytest.mark.parametrize('mutation',[
    lambda d:resized(d+b'garbage!'),
    lambda d:resized(d+b'data'+struct.pack('<I',2)+b'\x00\x00'),
    lambda d:d[:40]+struct.pack('<I',2)+d[44:],
    lambda d:d[:28]+struct.pack('<I',16000)+d[32:],
    lambda d:d[:32]+struct.pack('<H',4)+d[34:],
])
def test_complete_riff_validation(tmp_path,mutation):
    p=tmp_path/'bad.wav';wav(p);p.write_bytes(mutation(p.read_bytes()))
    with pytest.raises(ValueError):asr_ops.recognition_pcm(ref(p))


def test_odd_metadata_padding_is_preserved(tmp_path):
    p=tmp_path/'metadata.wav';wav(p);data=p.read_bytes()
    p.write_bytes(resized(data[:36]+b'JUNK'+struct.pack('<I',3)+b'abc\x00'+data[36:]))
    assert len(asr_ops.recognition_pcm(ref(p)))==4
    bad=p.read_bytes().replace(b'abc\x00',b'abc\x01');p.write_bytes(bad)
    with pytest.raises(ValueError,match='PADDING'):asr_ops.recognition_pcm(ref(p))

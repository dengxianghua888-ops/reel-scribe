"""Stdlib-only preflight tests. Stub probing is NOT real-host acceptance."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest

MODULE = Path(__file__).resolve().parents[2] / 'tools/editor-adapters/blender_cut_import.py'
spec = importlib.util.spec_from_file_location('adapter', MODULE)
a = importlib.util.module_from_spec(spec); spec.loader.exec_module(a)


def rt(n): return {'OTIO_SCHEMA': 'RationalTime.1', 'value': n, 'rate': 24}
def fixture(root):
    data = b'fake media for validation only'; h = hashlib.sha256(data).hexdigest()
    (root/'media').mkdir(); (root/'media/clip.mov').write_bytes(data)
    clip = {'OTIO_SCHEMA':'Clip.1','name':'one','enabled':True,'effects':[],'markers':[],
            'source_range':{'OTIO_SCHEMA':'TimeRange.1','start_time':rt(24),'duration':rt(48)},
            'metadata':{'recap':{'speed':1,'source_start':1,'duration':2,'target_start':0}},
            'media_reference':{'OTIO_SCHEMA':'ExternalReference.1','target_url':'media/clip.mov','metadata':{'recap':{'resource_id':'source','sha256':h}}}}
    timeline = {'OTIO_SCHEMA':'Timeline.1','global_start_time':rt(0),'metadata':{'recap':{'profile':{'fps':24,'width':160,'height':90}}},'tracks':{'OTIO_SCHEMA':'Stack.1','children':[{'OTIO_SCHEMA':'Track.1','kind':'Video','enabled':True,'children':[clip]}]}}
    resource = {'package_path':'media/clip.mov','sha256':h,'facts':{'start_time':0,'cfr':True,'fps':24,'width':160,'height':90,'frame_count':96,'sample_rate':48000,'duration_samples':192000}}
    for name, content in [('timeline.otio',timeline),('media-manifest.json',{'resources':{'source':resource}}),('caption-map.json',{'captions':[]})]: (root/name).write_text(json.dumps(content))
    (root/'captions.srt').write_text(''); seal(root)
    return timeline


def seal(root):
    rows = {p.relative_to(root).as_posix(): {'bytes':p.stat().st_size,'sha256':a.digest(p)} for p in root.rglob('*') if p.is_file() and p.name!='checksums.json'}
    (root/'checksums.json').write_text(json.dumps({'schema':'film-otio-export/1','completion_state':'COMPLETE','files':rows}))


def probe(_): return [{'codec_type':'video','avg_frame_rate':'24/1','r_frame_rate':'24/1','width':160,'height':90,'start_time':'0'}]


class Preflight(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.t=fixture(self.root)
    def check(self): return a.validate(self.root,probe)
    def mutate(self, fn):
        fn(self.t); (self.root/'timeline.otio').write_text(json.dumps(self.t)); seal(self.root)
    def test_valid(self): self.assertEqual(self.check()['clips'][0]['offset'],24)
    def test_tamper(self):
        (self.root/'media/clip.mov').write_bytes(b'x')
        with self.assertRaisesRegex(ValueError,'MEMBER_CHANGED'):self.check()
    def test_symlink(self):
        (self.root/'linked').symlink_to(self.root/'media/clip.mov')
        with self.assertRaisesRegex(ValueError,'SYMLINK'):self.check()
    def test_path(self):
        for path in ('../clip','/tmp/x','media/../clip','https://x','media\\clip','./media/clip'):
            with self.subTest(path=path),self.assertRaises(ValueError): a.safe_member(self.root,path)
    def test_duplicate_json(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):json.loads('{"x":1,"x":2}',object_pairs_hook=a.unique)
    def test_captions(self):
        (self.root/'captions.srt').write_text('subtitle');seal(self.root)
        with self.assertRaisesRegex(ValueError,'CAPTIONS'):self.check()
    def test_fractional(self):
        self.mutate(lambda t:t['metadata']['recap']['profile'].update(fps={'numerator':30000,'denominator':1001}))
        with self.assertRaisesRegex(ValueError,'FPS'):self.check()
    def test_subframe(self):
        self.mutate(lambda t:t['tracks']['children'][0]['children'][0]['source_range']['start_time'].update(value=.5))
        with self.assertRaisesRegex(ValueError,'SUBFRAME'):self.check()
    def test_effect(self):
        self.mutate(lambda t:t['tracks']['children'][0]['children'][0].update(effects=[{'fade':1}]))
        with self.assertRaisesRegex(ValueError,'EFFECT'):self.check()
    def test_unknown_field(self):
        self.mutate(lambda t:t.update(unrecognized=True))
        with self.assertRaisesRegex(ValueError,'FIELD'):self.check()
    def test_wrong_window(self):
        self.mutate(lambda t:t['tracks']['children'][0]['children'][0]['metadata']['recap'].update(target_start=1))
        with self.assertRaisesRegex(ValueError,'METADATA'):self.check()
    def test_overrun(self):
        self.mutate(lambda t:t['tracks']['children'][0]['children'][0]['source_range']['duration'].update(value=240))
        with self.assertRaisesRegex(ValueError,'OVERRUN'):self.check()
    def test_duplicate_id(self):
        self.mutate(lambda t:t['tracks']['children'][0]['children'].append(copy.deepcopy(t['tracks']['children'][0]['children'][0])))
        with self.assertRaisesRegex(ValueError,'DUPLICATE_CLIP'):self.check()
    def test_reject_before_host_mutation(self):
        # Host has no context/data attributes. Access would fail if validation mutated it.
        host=types.SimpleNamespace(app=types.SimpleNamespace(version=(4,3,2)))
        (self.root/'captions.srt').write_text('subtitle');seal(self.root)
        with self.assertRaisesRegex(ValueError,'CAPTIONS'):a.import_to_host(self.root,self.root/'new.blend',host)
        self.assertFalse((self.root/'new.blend').exists())
    def test_processing_metadata_rejected(self):
        for level in ('clip', 'track', 'stack'):
            for key, value in [('gain_db', -6), ('volume', .5), ('crop', {'left': 10}),
                               ('transform', {'scale': 2}), ('audio_processing', {'normalize': True}),
                               ('gain', 1)]:
                with self.subTest(level=level, key=key):
                    t=copy.deepcopy(self.t)
                    target=t['tracks'] if level=='stack' else t['tracks']['children'][0]
                    if level=='clip':target=target['children'][0]
                    target.setdefault('metadata', {}).setdefault('recap', {})[key]=value
                    (self.root/'timeline.otio').write_text(json.dumps(t));seal(self.root)
                    with self.assertRaisesRegex(ValueError,'METADATA'):self.check()
    def test_foreign_metadata_rejected(self):
        self.mutate(lambda t:t['tracks']['children'][0].update(metadata={'other_editor':{'volume':0}}))
        with self.assertRaisesRegex(ValueError,'METADATA'):self.check()
    def test_profile_processing_rejected(self):
        self.mutate(lambda t:t['metadata']['recap']['profile'].update(crop='fill'))
        with self.assertRaisesRegex(ValueError,'PROFILE'):self.check()
    def test_host_version(self):
        host=types.SimpleNamespace(app=types.SimpleNamespace(version=(4,4,0)))
        with self.assertRaisesRegex(ValueError,'HOST_VERSION'):a.import_to_host(self.root,self.root/'new.blend',host)

if __name__=='__main__':unittest.main()

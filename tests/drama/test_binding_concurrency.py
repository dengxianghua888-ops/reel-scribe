"""Real filesystem races on synthetic Work data, without provider/media input."""
from concurrent.futures import ThreadPoolExecutor
import errno
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'runtime'))
import drama_binding as binding
import editing_runtime as runtime
import work_ops


class PreparationConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.tools=runtime.Tools(shutil.which('ffmpeg'),shutil.which('ffprobe'))
        if not self.tools.ffmpeg or not self.tools.ffprobe:
            self.skipTest('Synthetic Work integration requires ffmpeg and ffprobe')
        media=self.root/'synthetic.mp4'
        subprocess.run([self.tools.ffmpeg,'-nostdin','-v','error','-n','-f','lavfi',
                        '-i','color=c=red:s=64x64:r=25:d=0.4','-c:v','libx264',
                        '-pix_fmt','yuv420p',str(media)],check=True)
        self.document={'schema':'work-document/1','plan':{
            'schema':'execution-plan/1','fps':'25','width':64,'height':64,'fit':'contain',
            'sources':{'source':{'path':str(media),'sha256':runtime.sha256(media)}},
            'clips':[{'id':'clip','source_id':'source','start':0,'end':0.4,'gain_db':0}]},
            'captions':{},'caption_style':None,'audio_tracks':{},'style_bindings':{},
            'notes':{'manual_note':'preserve'},'visual_layers':{}}
        self.store=self.root/'work.sqlite3'
        output=self.root/'init';output.mkdir()
        self.state=work_ops.work_version({'operation':'work-version','action':'init',
            'store':str(self.store),'work_id':'synthetic','document':self.document,
            'author':'agent','message':'synthetic test'},output,self.tools)
        self.package=ROOT/'workflows/raven-drama-production/examples/return-key/PACKAGE-MANIFEST.json'

    def prepare(self):
        return binding.prepare_attachment(self.package,self.store,self.state['version'])

    def test_concurrent_preparation_verifies_winning_directory(self):
        rename=Path.rename
        barrier=threading.Barrier(2)
        observed=[]
        def synchronized(source,target):
            if source.name.startswith('.preparing-'):
                barrier.wait(timeout=10)
                try:
                    return rename(source,target)
                except OSError as exc:
                    observed.append(exc.errno)
                    raise
            return rename(source,target)
        with patch.object(Path,'rename',synchronized),ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:self.prepare(),range(2)))
        self.assertEqual(['PREPARED','PREPARED'],[r['status'] for r in results])
        self.assertEqual(results[0]['reference'],results[1]['reference'])
        self.assertTrue(observed and set(observed)<={errno.EEXIST,errno.ENOTEMPTY})
        self.assertEqual('PASS',binding.verify_reference(results[0]['reference'])['status'])
        db=work_ops.connect(self.store)
        try:
            self.assertEqual(self.state['version'],work_ops.load(db)['version'])
        finally:
            db.close()

    def test_unrelated_rename_error_is_not_swallowed(self):
        with patch.object(Path,'rename',side_effect=OSError(errno.EACCES,'denied')):
            with self.assertRaises(OSError) as error:
                self.prepare()
        self.assertEqual(errno.EACCES,error.exception.errno)

    def test_existing_corrupt_winner_is_rejected(self):
        result=self.prepare()
        manifest=Path(result['reference']['manifest']['path'])
        manifest.write_text(json.dumps({'schema':'corrupt'}))
        with self.assertRaisesRegex(binding.DramaBindingError,'DRAMA_IDENTITY_CHANGED'):
            self.prepare()


if __name__=='__main__':
    unittest.main()

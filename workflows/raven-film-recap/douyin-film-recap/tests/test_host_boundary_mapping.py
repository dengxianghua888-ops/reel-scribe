"""Self-created color/sine media and explicitly synthetic evidence; not film QA."""
import pytest
from copy import deepcopy
from pathlib import Path
import json,sys,subprocess
from test_boundary_apply import apply_fixture
from douyin_film_recap import otio_exchange as x,otio_readback as r,workspace as w
from douyin_film_recap.boundary_apply import prepare_boundary_revision,collect_boundary_timebases
from douyin_film_recap.boundary import proposal_hash,candidate_revision
from douyin_film_recap.pipeline import FilmRecapPipeline
from douyin_film_recap.revision import freeze_revision
from douyin_film_recap.utils import write_json,content_fingerprint,fingerprint_json
from douyin_film_recap.host_boundary_mapping import apply_host_boundary

@pytest.fixture
def case(tmp_path):
 root=tmp_path
 source_path=root/'synthetic.mp4';voice=root/'voice.wav'
 if not source_path.exists():subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=32x32:rate=30:duration=60','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=60','-c:v','libx264','-c:a','aac','-shortest',str(source_path)],check=True)
 if not voice.exists():subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=660:sample_rate=48000:duration=20',str(voice)],check=True)
 p,kw=apply_fixture()
 for seg in kw['storyboard'].segments:
  for i,v in enumerate(seg.visuals):v.clip_instance_id=f'{seg.segment_id}-visual-{i}'
 source=kw['manifest'].sources[0];source.path=str(source_path);source.fingerprint=content_fingerprint(source_path)
 kw['storyboard'].sources=[source.model_copy(deep=True)]
 for key in ('highlights','transcript','scene_index'):kw[key].source_fingerprints={'s1':source.fingerprint}
 h=kw['highlights'].candidates[0];h.end=24;p.original_range.end=24;p.source_sha256=source.fingerprint
 kw['storyboard'].segments[0].visuals[0].end=24;kw['storyboard'].segments[0].planned_duration_sec=14
 kw['storyboard'].target_duration_sec=34;kw['plan'].target_duration_sec=34;kw['plan'].beats[0].target_duration_sec=34;kw['plan'].beats[0].target_original_sec=14
 kw['storyboard'].segments[1].audio_file=str(voice);kw['storyboard'].segments[1].audio_duration_sec=20
 kw['timebases']=collect_boundary_timebases(kw['manifest']);p.timebase=kw['timebases']['s1']
 for ref in p.ordered_evidence_units:ref.source_sha256=source.fingerprint;ref.timebase_hash=fingerprint_json(p.timebase.model_dump(mode='json'))
 p.candidate_revision=candidate_revision(h);p.original_highlight_hash=fingerprint_json(h.model_dump(mode='json'))
 pipeline=FilmRecapPipeline(input_path=source_path,work_dir=root/'work',config=kw['config']);work=pipeline.work_dir
 artifacts={'00_source_manifest.json':kw['manifest'],'01_transcript.json':kw['transcript'],'02_scene_index.json':kw['scene_index'],'03_scene_analysis.json':kw['scene_analysis'],'04_character_registry.json':kw['story'].character_registry,'05_story_graph.json':kw['story'].story_graph,'06_knowledge_timeline.json':kw['story'].knowledge_timeline,'07_highlight_candidates.json':kw['highlights'],'08_recap_plan.json':kw['plan'],'09_storyboard.json':kw['storyboard']}
 for name,val in artifacts.items():write_json(work/name,val)
 base=freeze_revision(work);p.base_artifact_hashes=base['artifact_hashes'];kw['current_artifact_hashes']=base['artifact_hashes'];p.proposal_content_hash=proposal_hash(p);p.approved_proposal_hash=p.proposal_content_hash
 prep=prepare_boundary_revision(p,**kw)
 facts=x.collect_media_facts(kw['storyboard'].model_dump(mode='json'))
 x.export_otio_package(work,root/'package',profile={'fps':30,'width':32,'height':32},media_facts=facts,captions=[])
 projection=json.loads((root/'package/projection.json').read_text());binding=json.loads((root/'package/export-binding.json').read_text());board=prep.artifacts['09_storyboard.json'];sha=x.digest(board)
 new=x.compile_cut_projection(board,storyboard_sha256=sha,authority={'storyboard_sha256':sha,'workspace_generation':base['generation']},profile=projection['profile'],media_facts={k:v['facts'] for k,v in projection['resources'].items()},identity_map=projection['identity_map'],captions=[])
 for key,value in new['resources'].items():value['package_path']=projection['resources'][key]['package_path']
 (root/'saved.otio').write_bytes(x.canonical(x.serialize_otio(new,binding['export_id'])))
 r.capture_saved_snapshot(root/'saved.otio',root/'snapshot',export_package=root/'package',media_root=root/'package')
 report=r.propose_saved_readback(root/'package',work,root/'snapshot');
 mapping={'schema':'film-host-boundary-mapping/1','snapshot_sha256':w.sha(root/'snapshot/checksums.json'),'export_package_sha256':w.sha(root/'package/checksums.json'),'boundary_proposal_hash':proposal_hash(p),'instance_ids':sorted({c['entity_id'] for c in report['changes'] if c['field']!='track_end'}),'track_ends':{c['entity_id']:{'before':c['current'],'after':c['host']} for c in report['changes'] if c['field']=='track_end'}}
 (root/'proposal.json').write_text(p.model_dump_json());(root/'mapping.json').write_bytes(x.canonical(mapping));(root/'base.json').write_bytes(x.canonical(base));(root/'report.json').write_bytes(x.canonical(report))
 return dict(work_dir=work,export_package=root/'package',saved_snapshot=root/'snapshot',base=base,proposal=p,mapping=mapping,config=kw['config'],timebases=kw['timebases'])

def test_exact_mapping_uses_original_generation(case):
 root=case['work_dir']; before=(root/'09_storyboard.json').read_bytes()
 result=apply_host_boundary(**case)
 assert result['status']=='ADOPTED'
 active=Path(result['active_dir'])
 receipt=w.read(active/'.receipts/boundary-adoption.json')
 assert receipt['additional_candidate_binding']['mapping']==case['mapping']
 assert w.read(active/'state.json')['stages']['pre_qc']['status']=='pending'
 assert (root/'09_storyboard.json').read_bytes()==before
 with pytest.raises(Exception):apply_host_boundary(**case)

@pytest.mark.parametrize('mutation',[
 lambda c:c['mapping'].update(instance_ids=[]),
 lambda c:c['mapping'].update(track_ends={}),
 lambda c:c['mapping'].update(boundary_proposal_hash='0'*64),
 lambda c:c['mapping'].update(snapshot_sha256='0'*64),
 lambda c:c['mapping'].update(export_package_sha256='0'*64),
 lambda c:setattr(c['proposal'],'editorial_decision','pending'),
 lambda c:c['base'].update(state_sha256='0'*64),
])
def test_invalid_binding_never_adopts(case,mutation):
 before=w.preflight(case['work_dir'])[1]
 mutation(case)
 with pytest.raises(Exception):apply_host_boundary(**case)
 assert w.preflight(case['work_dir'])[1]==before

def test_unselected_window_change_rejected(case):
 # A host change not in the approved boundary candidate cannot sneak through an acknowledged scope.
 import douyin_film_recap.host_boundary_mapping as m
 original=m.compare_projection
 def mismatch(candidate,host):
  host=deepcopy(host); row=next(iter(host['entities'].values()));row['source_start']={'numerator':999,'denominator':1}
  return original(candidate,host)
 from unittest.mock import patch
 with patch.object(m,'compare_projection',side_effect=mismatch):
  with pytest.raises(Exception,match='WINDOW_MISMATCH'):apply_host_boundary(**case)
 assert w.preflight(case['work_dir'])[1]==case['work_dir']

@pytest.mark.parametrize('key',['snapshot_sha256','export_package_sha256','boundary_proposal_hash'])
@pytest.mark.parametrize('bad',[None,False,'', 'A'*64, '0'*63])
def test_digest_schema_rejected_before_io(key,bad):
 mapping={'schema':'film-host-boundary-mapping/1','snapshot_sha256':'0'*64,'export_package_sha256':'1'*64,
          'boundary_proposal_hash':'2'*64,'instance_ids':['i'],'track_ends':{'t':{'before':{'numerator':1,'denominator':1},'after':{'numerator':2,'denominator':1}}}}
 mapping[key]=bad
 with pytest.raises(Exception,match='DIGEST_REQUIRED'):
  apply_host_boundary('/not-read',export_package='/not-read',saved_snapshot='/not-read',base={},proposal=None,mapping=mapping,config=None,timebases={})

@pytest.mark.parametrize('value',[{'numerator':1,'denominator':True},{'numerator':False,'denominator':1},
 {'numerator':1,'denominator':0},{'numerator':-1,'denominator':1},{'numerator':1.0,'denominator':1},None])
def test_rational_schema_rejected_before_io(value):
 mapping={'schema':'film-host-boundary-mapping/1','snapshot_sha256':'0'*64,'export_package_sha256':'1'*64,
          'boundary_proposal_hash':'2'*64,'instance_ids':['i'],'track_ends':{'t':{'before':value,'after':{'numerator':2,'denominator':1}}}}
 with pytest.raises(Exception,match='RATIONAL_REQUIRED'):
  apply_host_boundary('/not-read',export_package='/not-read',saved_snapshot='/not-read',base={},proposal=None,mapping=mapping,config=None,timebases={})

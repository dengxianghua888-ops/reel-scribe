"""Two declared mechanisms, not real style/semantic acceptance."""
import copy,json
from pathlib import Path
import pytest
from test_reference_transfer import narrative,work_case
import reference_transfer_ops as mod
import editing_runtime as rt
import work_ops

@pytest.fixture
def composition(narrative):
 q,out,tools,doc=narrative
 ref=out.parent/'second-reference.bin';ref.write_bytes(b'independent synthetic second reference')
 card=Path(__file__).resolve().parents[2]/'styles/software/readable-deliberate.md'
 scope={'clip_ids':[],'source_ids':[],'caption_ids':[],'audio_ids':[],'style_keys':['*'],'note_keys':[],'output_fields':[],'caption_style':True,'freeze_positions':['peek','full'],'freeze_duration':True}
 variants=[]
 for size in [12,14]:
  recipe={'schema':'style-recipe/1','id':str(size),'version':'1','style':{'family':'software','style_id':'readable-deliberate','version':'0.1.0','card':{'path':str(card),'sha256':rt.sha256(card)}},'parameters':{'caption_style':{'font_size':size}}}
  variants.append({'id':str(size),'recipe':recipe,'expected_recipe_sha256':rt.fingerprint(recipe),'capabilities':['caption-style'],'scope':copy.deepcopy(scope)})
 item={'id':'caption','axis':'audiovisual','mechanism':'caption-presentation','decision':'adapt','reason':'Synthetic explicit presentation only',
 'observation':{'status':'observed','start':0,'end':1,'method':'visual-review','evidence':{'path':str(ref),'sha256':rt.sha256(ref)},'description':'DO NOT COPY THIS REFERENCE TEXT'},'parameters':{'variants':variants}}
 final_scope=copy.deepcopy(q['items'][0]['parameters']['scope']);final_scope.update(style_keys=['*'],caption_style=True)
 request={'operation':'reference-transfer-prepare','composition':'result-first-then-caption','scene':'software','store':q['store'],'expected_version':q['expected_version'],
 'stages':[{'reference':q['reference'],'items':q['items']},{'reference':{'path':str(ref),'sha256':rt.sha256(ref)},'items':[item]}],
 'selected_caption_variant_id':'14','final_scope':final_scope}
 return request,out,tools,doc

def test_compiles_in_order_without_commit_or_dead_temporary_dependencies(composition):
 q,out,tools,doc=composition;r=mod.execute(q,out,tools)
 mid=json.loads((out/'intermediate-document.json').read_text());bundle=json.loads((out/'candidate.json').read_text());final=bundle['document']
 assert final['caption_style']['font_size']==14
 assert final['captions']==mid['captions'] and 'DO NOT COPY' not in json.dumps(final['captions'])
 assert final['plan']['clips'][1:]==doc['plan']['clips']
 assert final['plan']==mid['plan'] and final['notes']==mid['notes']
 assert r['stages'][1]['input_document_sha256']==rt.fingerprint(mid)
 assert bundle['base_version']==q['expected_version']
 assert bundle['base_document_sha256']==rt.fingerprint(doc)
 assert not r['rendered'] and not r['committed']
 assert 'reference_media_inserted_by_composition' not in r
 assert not r['external_reference_sources_imported']
 assert r['reference_source_matches_in_target'][0][0]['id']=='s'
 assert r['reference_source_matches_in_candidate'][0][0]['id']=='s'
 assert r['reference_output_presence']=='NOT_EVALUATED'
 assert 'reference-composition-' not in json.dumps(r)
 assert not (out/'prepared-request.json').exists()
 with work_ops.connect(q['store']) as db:s=work_ops.load(db)
 assert s['document']==doc and s['version']==q['expected_version']

@pytest.mark.parametrize('mutate,error',[
 (lambda q:q.update(composition='anything'),'COMPOSITION_UNSUPPORTED'),
 (lambda q:q.update(scene='speech'),'SOFTWARE_ONLY'),
 (lambda q:q['stages'].reverse(),'ORDER_OR_DECISION'),
 (lambda q:q['stages'].append(copy.deepcopy(q['stages'][0])),'TWO_STAGES'),
 (lambda q:q['stages'][1].update(reference=q['stages'][0]['reference']),'DISTINCT_MEDIA'),
 (lambda q:q['stages'][1]['items'][0].update(decision='adopt'),'ORDER_OR_DECISION'),
 (lambda q:q['stages'][1]['items'][0].update(observation={'status':'unobserved'}),'UNOBSERVED_TRANSFER'),
 (lambda q:q.update(selected_caption_variant_id='missing'),'SELECTED_VARIANT_UNKNOWN'),
 (lambda q:q['final_scope'].update(caption_style=False),'CAPTION_STYLE_FROZEN'),
 (lambda q:q['final_scope'].update(style_keys=[]),'OUTSIDE_SCOPE: style_bindings'),
 (lambda q:q['final_scope'].update(freeze_duration=True),'DURATION_FROZEN'),
 (lambda q:q['stages'][1]['items'][0]['parameters']['variants'][0]['scope'].update(freeze_positions=['full']),'POSITIONS_NOT_FROZEN'),
 (lambda q:q.update(expected_version='0'*64),'WORK_VERSION_CONFLICT'),
])
def test_rejects_without_final_candidate(composition,mutate,error):
 q,out,tools,_=composition;mutate(q)
 with pytest.raises(rt.ContractError,match=error):mod.execute(q,out,tools)
 assert not (out/'candidate.json').exists()

def test_audio_parameter_cannot_be_smuggled(composition):
 q,out,tools,_=composition;v=q['stages'][1]['items'][0]['parameters']['variants'][0]
 v['recipe']['parameters']['audio_gain_db']={'x':-10};v['expected_recipe_sha256']=rt.fingerprint(v['recipe'])
 with pytest.raises(rt.ContractError,match='CAPTION_ONLY_PARAMETERS'):mod.execute(q,out,tools)

def test_changed_reference_after_second_compile_rejected(composition,monkeypatch):
 import style_recipe_ops
 q,out,tools,_=composition;original=style_recipe_ops.execute
 def tamper(*args,**kwargs):
  result=original(*args,**kwargs);Path(q['stages'][0]['reference']['path']).write_bytes(b'changed');return result
 monkeypatch.setattr(style_recipe_ops,'execute',tamper)
 with pytest.raises(rt.ContractError,match='SOURCE_HASH_MISMATCH'):mod.execute(q,out,tools)
 assert not (out/'candidate.json').exists()

def test_final_head_race_rejected(composition,monkeypatch):
 import style_recipe_ops
 q,out,tools,_=composition;original=style_recipe_ops.execute;old_load=work_ops.load;late=[]
 def changed(db):
  state=old_load(db)
  if late:state['version']='0'*64
  return state
 monkeypatch.setattr(work_ops,'load',changed)
 def tamper(*args,**kwargs):
  result=original(*args,**kwargs);late.append(True);return result
 monkeypatch.setattr(style_recipe_ops,'execute',tamper)
 with pytest.raises(rt.ContractError,match='WORK_VERSION_CONFLICT'):mod.execute(q,out,tools)
 assert not (out/'candidate.json').exists()

@pytest.mark.parametrize('final_mapping',[True,False])
def test_protection_preserved_and_final_scope_not_inferred(composition,work_case,final_mapping):
 from test_result_preview import protected_case
 doc=protected_case(work_case);q,out,tools,_=composition
 q.update(store=work_case[0]['store'],expected_version=work_case[0]['expected_version'])
 q['stages'][0]['items'][0]['parameters']['scope']['evidence_mapping']=True
 q['final_scope']['evidence_mapping']=final_mapping
 if not final_mapping:
  with pytest.raises(rt.ContractError,match='EVIDENCE_MAPPING'):mod.execute(q,out,tools)
  assert not (out/'candidate.json').exists();return
 r=mod.execute(q,out,tools)
 candidate=json.loads((out/'candidate.json').read_text())['document']
 assert candidate['evidence_protection']==doc['evidence_protection']
 assert r['stages'][0]['result']['protection_shift']['original_carriers_preserved']
 with work_ops.connect(q['store']) as db:assert work_ops.load(db)['document']==doc

@pytest.mark.parametrize('field',['captions','plan','notes','audio_tracks'])
def test_second_compiler_cannot_mutate_content(composition,monkeypatch,field):
 import style_recipe_ops
 q,out,tools,_=composition;original=style_recipe_ops.execute
 def rogue(request,directory,tools):
  r=original(request,directory,tools);p=directory/'candidate.json';b=json.loads(p.read_text());b['document'][field]['INJECTED']='forbidden';p.write_text(json.dumps(b));return r
 monkeypatch.setattr(style_recipe_ops,'execute',rogue)
 with pytest.raises(rt.ContractError,match='COMPOSITION_CONTENT_CHANGED'):mod.execute(q,out,tools)
 assert not (out/'candidate.json').exists()

def test_actual_libass_layout_evidence_survives_temporary_workspace(composition,monkeypatch):
 import caption_layout
 q,out,tools,doc=composition
 font=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
 if not font.is_file():
  fonts=list(Path('/usr/share/fonts').rglob('NotoSansCJK-Regular.ttc'));assert fonts,'CJK font required';font=fonts[0]
 doc=copy.deepcopy(doc);doc['plan'].update(width=960,height=636)
 doc['caption_style'].update(font={'path':str(font),'sha256':rt.sha256(font)},font_family='Noto Sans CJK SC',font_size=24,margin_v=8)
 init=out.parent/'layout-init';init.mkdir();store=out.parent/'layout.sqlite'
 s=work_ops.work_version({'operation':'work-version','action':'init','store':str(store),'work_id':'layout-real','document':doc,'author':'agent','message':'Synthetic media with actual libass masks'},init,tools)
 q.update(store=str(store),expected_version=s['version'])
 for v in q['stages'][1]['items'][0]['parameters']['variants']:
  v['recipe']['parameters']['caption_style']['font_size']=24
  v['recipe']['layout_constraints']={'schema':'caption-layout/1','canvas':{'width':960,'height':636},'subtitle_band':{'x':0,'y':592,'width':960,'height':44},'protected_regions':[{'id':'screen','rect':{'x':0,'y':48,'width':960,'height':540}}]}
  v['expected_recipe_sha256']=rt.fingerprint(v['recipe'])
 original=caption_layout.check
 real_tools=rt.Tools();real_tools.probe=tools.probe;real_tools.selected_video_clock=tools.selected_video_clock
 monkeypatch.setattr(caption_layout,'check',lambda document,constraints,directory,_tools:original(document,constraints,directory,real_tools))
 r=mod.execute(q,out,tools)
 assert '/tmp/reference-composition-' not in json.dumps(r)
 layout=r['stages'][1]['result']['caption_layout'];assert layout['status']=='STATIC_GLYPH_COVERAGE_VERIFIED'
 for row in layout['observations']:
  for key in ['mask','ass','padded_mask','padded_ass']:
   artifact=row[key];p=Path(artifact['path']);assert p.is_relative_to(out/'stage-b-evidence') and p.is_file()
   assert rt.sha256(p)==artifact['sha256']

@pytest.mark.parametrize('mode',['source-symlink','destination-symlink','existing-target','wrong-digest'])
def test_generated_evidence_copy_fail_closed(composition,monkeypatch,mode):
 import style_recipe_ops
 q,out,tools,_=composition;original=style_recipe_ops.execute
 if mode in ['destination-symlink','existing-target']:
  target=out/'stage-b-evidence/layout/cue-0000';target.mkdir(parents=True)
  if mode=='destination-symlink':
   target.rmdir();target.symlink_to(out.parent,target_is_directory=True)
  else:(target/'original.png').write_bytes(b'KEEP')
 def injected(request,directory,tools):
  result=original(request,directory,tools);folder=directory/'layout/cue-0000';folder.mkdir(parents=True);(directory/'layout/fonts').mkdir()
  for name in ['original.png','original.ass','padded.png','padded.ass']:(folder/name).write_bytes(b'copy-safety fixture, not actual alpha')
  if mode=='source-symlink':
   (folder/'original.png').unlink();(folder/'original.png').symlink_to(folder/'padded.png')
  result['caption_layout']={'status':'STATIC_GLYPH_COVERAGE_VERIFIED','observations':[{'mask':{'path':str(folder/'original.png'),'sha256':rt.sha256(folder/'original.png') if mode!='wrong-digest' else '0'*64},'ass':{'path':str(folder/'original.ass'),'sha256':rt.sha256(folder/'original.ass')},'padded_mask_sha256':rt.sha256(folder/'padded.png')}]}
  return result
 monkeypatch.setattr(style_recipe_ops,'execute',injected)
 with pytest.raises((rt.ContractError,FileExistsError)):mod.execute(q,out,tools)
 assert not (out/'candidate.json').exists() and not (out/'reference-composition.json').exists()
 if mode=='existing-target':assert (out/'stage-b-evidence/layout/cue-0000/original.png').read_bytes()==b'KEEP'

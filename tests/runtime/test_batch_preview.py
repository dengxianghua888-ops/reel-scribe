"""Actual short synthetic renders; reuse is identity validation, not content QA."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_source_binding import tools, media, plan  # noqa: F401
import editing_runtime as runtime
import batch_ops
import work_ops


@pytest.fixture
def case(tmp_path, tools, media):
    store=tmp_path/'work.sqlite'
    document={'schema':'work-document/1','plan':plan(media['red'],mute=True),
              'captions':{},'caption_style':None,'audio_tracks':{},'style_bindings':{},'notes':{}}
    init=tmp_path/'init';init.mkdir()
    state=work_ops.work_version({'operation':'work-version','action':'init','store':str(store),
        'work_id':'preview-test','document':document,'author':'agent','message':'test'},init,tools)
    scope={'clip_ids':[],'source_ids':[],'caption_ids':[],'audio_ids':[],'style_keys':[],
        'note_keys':['variant'],'output_fields':[],'caption_style':False,
        'freeze_positions':['one'],'freeze_duration':True}
    candidates=[]
    for index in range(2):
        candidate=copy.deepcopy(document);candidate['notes']['variant']=str(index)
        bundle={'schema':'work-candidate/1','base_version':state['version'],
                'base_document_sha256':state['document_sha256'],'document':candidate,'scope':scope}
        path=tmp_path/f'candidate-{index}.json';runtime.write_json(path,bundle)
        candidates.append({'path':str(path),'sha256':runtime.sha256(path)})
    return {'root':tmp_path,'tools':tools,'state':state,'store':store,'document':document,
            'candidates':candidates,'source':media['red']}


def prepare(case, count=1, candidates=None):
    refs=candidates or case['candidates'][:count]
    jobs=[{'id':str(i),'store':str(case['store']),'expected_version':case['state']['version'],
        'preview_candidate':ref} for i,ref in enumerate(refs)]
    output=case['root']/'prepare';output.mkdir()
    result=batch_ops.batch_render({'operation':'work-batch-render','action':'prepare',
        'batch_dir':str(case['root']/'batch'),'batch_id':'preview','jobs':jobs},output,case['tools'])
    case['manifest_sha256']=result['manifest_sha256'];case['ids']=[j['id'] for j in jobs]
    return result


def run(case, name, retry=False):
    output=case['root']/name;output.mkdir()
    return batch_ops.batch_render({'operation':'work-batch-render','action':'run',
        'batch_dir':str(case['root']/'batch'),'manifest_sha256':case['manifest_sha256'],
        'job_ids':case['ids'],'retry_failed':retry},output,case['tools'])


def test_distinct_previews_share_base_but_repeated_jobs_do_not_render(case):
    prepare(case,2)
    first=run(case,'first')
    assert first['status']=='RENDERED'
    assert [e['action'] for e in first['events']]==['RENDER_ATTEMPT','RENDER_ATTEMPT']
    with patch.object(runtime,'run',side_effect=AssertionError('must reuse verified render')):
        second=run(case,'second')
    assert [e['action'] for e in second['events']]==['REUSED_VERIFIED','REUSED_VERIFIED']
    db=work_ops.connect(str(case['store']))
    try:assert work_ops.load(db)['version']==case['state']['version']
    finally:db.close()
    receipts=[json.loads((case['root']/f'batch/jobs/{i}/attempt-0001/receipt.json').read_text()) for i in range(2)]
    assert receipts[0]['result']['document_sha256']!=receipts[1]['result']['document_sha256']


def test_duplicate_preview_identity_rejected_before_queue(case):
    with pytest.raises(ValueError,match='BATCH_DUPLICATE_WORK_VERSION'):
        prepare(case,candidates=[case['candidates'][0]]*2)
    assert not (case['root']/'batch').exists()


@pytest.mark.parametrize('when', ['before-prepare','before-run','before-reuse'])
def test_same_path_candidate_replacement_never_reused(case,when):
    if when!='before-prepare':prepare(case)
    if when=='before-reuse':run(case,'first')
    path=Path(case['candidates'][0]['path'])
    path.write_bytes(Path(case['candidates'][1]['path']).read_bytes())
    if when=='before-prepare':
        with pytest.raises(ValueError,match='SOURCE_HASH_MISMATCH'):prepare(case)
    else:
        with patch.object(runtime,'run',side_effect=AssertionError('must not render invalid candidate')):
            result=run(case,'after-change',True)
        assert result['events'][0]['action']=='PREVIEW_VALIDATION_FAILED'
        assert result['jobs'][0]['status']==('INVALID_OUTPUT' if when=='before-reuse' else 'FAILED')


def test_completed_receipt_recovers_without_encoding(case):
    prepare(case);run(case,'first')
    with sqlite3.connect(case['root']/'batch/queue.sqlite') as db:
        db.execute("UPDATE jobs SET status='RUNNING',receipt=NULL,receipt_sha256=NULL")
        db.execute("UPDATE attempts SET status='RUNNING'")
    with patch.object(runtime,'run',side_effect=AssertionError('must recover final receipt')):
        result=run(case,'recover')
    assert result['events'][0]['action']=='RECOVERED_RECEIPT'
    assert result['status']=='RENDERED'


def test_changed_head_rejects_old_candidate_even_after_success(case):
    prepare(case);run(case,'first')
    commit=case['root']/'commit';commit.mkdir()
    work_ops.work_version({'operation':'work-version','action':'commit','store':str(case['store']),
        'expected_version':case['state']['version'],'candidate':case['candidates'][1],
        'author':'agent','message':'new head'},commit,case['tools'])
    with patch.object(runtime,'run',side_effect=AssertionError('old preview must not render')):
        result=run(case,'old-head',True)
    assert result['events'][0]['action']=='PREVIEW_VALIDATION_FAILED'
    assert 'BATCH_WORK_VERSION_CONFLICT' in result['events'][0]['error']


def test_output_corruption_is_not_a_hit(case):
    prepare(case);run(case,'first')
    receipt=case['root']/'batch/jobs/0/attempt-0001/receipt.json'
    result=json.loads(receipt.read_text())
    Path(result['result']['video']['path']).write_bytes(b'corrupt')
    with patch.object(runtime,'run',side_effect=AssertionError('retry is not authorized')):
        state=run(case,'corrupt')
    assert state['events'][0]['action']=='FAILED_LEFT_UNCHANGED'
    assert state['jobs'][0]['status']=='INVALID_OUTPUT'


def test_forged_candidate_result_identity_fails_receipt_check(case):
    prepare(case);run(case,'first')
    root=case['root']/'batch'
    manifest=json.loads((root/'manifest.json').read_text())
    receipt=root/'jobs/0/attempt-0001/receipt.json'
    result=json.loads(receipt.read_text());result['result']['candidate_document_sha256']='0'*64
    receipt.write_text(json.dumps(result))
    with pytest.raises(ValueError,match='BATCH_PREVIEW_RESULT_MISMATCH'):
        batch_ops.check_receipt(receipt,manifest['jobs'][0],manifest['environment'],case['tools'])


def test_interrupted_attempt_without_receipt_gets_fresh_attempt(case):
    prepare(case)
    folder=case['root']/'batch'
    attempt=folder/'jobs/0/attempt-0001';attempt.mkdir(parents=True)
    (attempt/'partial.mp4').write_bytes(b'not a completed render')
    with sqlite3.connect(folder/'queue.sqlite') as db:
        db.execute("UPDATE jobs SET status='RUNNING',attempt=1")
        db.execute('INSERT INTO attempts VALUES(?,?,?,?,?)',('0',1,'RUNNING',str(attempt),None))
    result=run(case,'recover-partial')
    assert [e['action'] for e in result['events']]==['INTERRUPTED_ATTEMPT_PRESERVED','RENDER_ATTEMPT']
    assert result['jobs'][0]['attempt']==2 and result['status']=='RENDERED'
    assert (attempt/'partial.mp4').read_bytes()==b'not a completed render'


def test_scope_violation_rejected_at_prepare(case):
    ref=case['candidates'][0];path=Path(ref['path']);bundle=json.loads(path.read_text())
    bundle['scope']['note_keys']=[];path.write_text(json.dumps(bundle));ref['sha256']=runtime.sha256(path)
    with pytest.raises(ValueError,match='OUTSIDE_SCOPE'):prepare(case)
    assert not (case['root']/'batch').exists()


def test_candidate_source_change_rejected_not_reused(case):
    prepare(case);run(case,'first')
    case['source'].write_bytes(b'different content at same path')
    with patch.object(runtime,'run',side_effect=AssertionError('invalid source must not render')):
        result=run(case,'changed-source',True)
    assert result['events'][0]['action']=='PREVIEW_VALIDATION_FAILED'
    assert 'SOURCE_HASH_MISMATCH' in result['events'][0]['error']


def test_status_remains_read_only_after_candidate_invalid_before_first_attempt(case):
    prepare(case)
    Path(case['candidates'][0]['path']).write_text('{}')
    run(case,'invalid')
    output=case['root']/'status';output.mkdir()
    with sqlite3.connect(case['root']/'batch/queue.sqlite') as db:
        before=db.execute('SELECT * FROM jobs').fetchall()
    result=batch_ops.batch_render({'operation':'work-batch-render','action':'status',
        'batch_dir':str(case['root']/'batch'),'manifest_sha256':case['manifest_sha256']},output,case['tools'])
    with sqlite3.connect(case['root']/'batch/queue.sqlite') as db:
        assert db.execute('SELECT * FROM jobs').fetchall()==before
    assert result['artifact_integrity']=='NOT_RECHECKED_STATUS_ONLY'

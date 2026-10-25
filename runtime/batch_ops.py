"""Explicit scoped variants and restartable local render batches; no creative decisions."""
import copy,json,os,re,sqlite3
from pathlib import Path
from contextlib import contextmanager
import fcntl


def work_state(store):
    from work_ops import connect,load
    db=connect(store)
    try:return load(db)
    finally:db.close()


def variant_create(q,directory,tools):
    from editing_runtime import exact_keys,require,source,run,write_json
    from work_ops import revision_diff
    keys=['operation','parent_store','expected_parent_version','target_store','variant_id','candidate','message','author']
    exact_keys(q,keys,keys)
    parent=work_state(q['parent_store'])
    require(parent['version']==q['expected_parent_version'],'PARENT_VERSION_CONFLICT')
    target=Path(q['target_store']);require(target.is_absolute(),'ABSOLUTE_STORE_PATH_REQUIRED')
    require(target.resolve()!=Path(q['parent_store']).resolve(),'VARIANT_CANNOT_OVERWRITE_PARENT')
    require(not target.exists(),'VARIANT_STORE_EXISTS')
    require(isinstance(q['variant_id'],str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',q['variant_id']),'VARIANT_ID_INVALID')
    candidate=source(q['candidate']);bundle=json.loads(Path(candidate['path']).read_text())
    bk=['schema','base_version','base_document_sha256','document','scope'];exact_keys(bundle,bk,bk)
    require(bundle['schema']=='work-candidate/1','CANDIDATE_SCHEMA_UNSUPPORTED')
    require(bundle['base_version']==parent['version'] and bundle['base_document_sha256']==parent['document_sha256'],'CANDIDATE_BASE_CONFLICT')
    diff=revision_diff(parent['document'],bundle['document'],bundle['scope'],tools)
    doc=copy.deepcopy(bundle['document'])
    inherited=parent['document']['notes'].get('variant_lineage')
    require(inherited is None or (isinstance(inherited,dict) and inherited.get('schema')=='work-variant/1'),'VARIANT_LINEAGE_KEY_COLLISION')
    require(doc['notes'].get('variant_lineage')==inherited,'VARIANT_LINEAGE_CALLER_CHANGE')
    lineage={'schema':'work-variant/1','variant_id':q['variant_id'],'parent_store':str(Path(q['parent_store']).resolve()),'parent_work_id':parent['work_id'],'parent_version':parent['version'],'parent_sequence':parent['sequence'],'parent_document_sha256':parent['document_sha256'],'candidate':q['candidate'],'inherited_lineage':inherited}
    doc['notes']['variant_lineage']=lineage
    # Store commit is authoritative if an outer receipt is interrupted afterwards.
    drama_inheritance=({'drama_inheritance':{'store':str(Path(q['parent_store']).resolve()),
                        'expected_version':parent['version']}}
                       if 'drama_domain_ref' in doc['notes'] else {})
    rr=run({'operation':'work-version','action':'init','store':str(target),'work_id':q['variant_id'],
            'document':doc,'message':q['message'],'author':q['author'],**drama_inheritance},directory/'initialize',tools)
    require(rr['status']=='SUCCEEDED','VARIANT_INITIALIZE_FAILED: '+rr.get('error','unknown'))
    state=rr['result'];latest=work_state(q['parent_store'])
    result={'variant':state,'lineage':lineage,'diff':diff,'parent_current_at_finish':latest['version']==parent['version'],'parent_version_at_finish':latest['version'],'scope':'New editable variant from an exact parent revision; no parent mutation, no automatic inheritance of future edits, no native editor claim'}
    write_json(directory/'variant-binding.json',result);return result


def environment(tools):
    from editing_runtime import sha256
    return {'runtime_files':{p.name:sha256(p) for p in sorted(Path(__file__).parent.glob('*.py'))},'tools':tools.doctor()}


@contextmanager
def exclusive(batch):
    from editing_runtime import ContractError,SUBPROCESS_LOCK_FDS
    # This inode is never replaced/deleted. Child tools inherit the open lock FD.
    fd=os.open(batch/'worker.lock',os.O_CREAT|os.O_RDWR,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise ContractError('BATCH_BUSY') from exc
        token=SUBPROCESS_LOCK_FDS.set(SUBPROCESS_LOCK_FDS.get()+(fd,))
        try:yield
        finally:SUBPROCESS_LOCK_FDS.reset(token)
    finally:os.close(fd)


def database(batch):
    from editing_runtime import require
    p=batch/'queue.sqlite';require(p.is_file(),'BATCH_STORE_NOT_FOUND')
    db=sqlite3.connect(p.as_uri()+'?mode=rw',uri=True,timeout=0);db.row_factory=sqlite3.Row
    try:require(db.execute('PRAGMA user_version').fetchone()[0]==1,'BATCH_SCHEMA_UNSUPPORTED')
    except Exception:
        db.close();raise
    return db


def snapshot(db,manifest):
    rows=[dict(r) for r in db.execute('SELECT * FROM jobs ORDER BY ordinal')]
    for row in rows:
        spec=next(j for j in manifest['jobs'] if j['id']==row['id'])
        try:row['current_version_matches']=work_state(spec['store'])['version']==spec['expected_version']
        except (ValueError,OSError,sqlite3.Error):row['current_version_matches']=False
    states=[r['status'] for r in rows]
    status='RENDERED' if all(s=='RENDERED' for s in states) else 'PARTIAL' if 'RENDERED' in states else 'PENDING_OR_FAILED'
    if status=='RENDERED' and not all(r['current_version_matches'] for r in rows):status='RENDERED_HISTORICAL'
    return {'schema':'batch-state/1','batch_id':manifest['batch_id'],'status':status,'jobs':rows,'attempts':[dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY job_id,number')],'creative_quality':'NOT_RUN','native_editor':'NOT_RUN','scope':'Local explicit work exports. RENDERED is not semantic, listening, publishing or platform acceptance.'}


def render_request(spec):
    from editing_runtime import require
    from source_binding import selection
    request={'operation':'work-render','store':spec['store'],'expected_version':spec['expected_version']}
    if 'audio_backend' in spec:
        require(isinstance(spec['audio_backend'],dict),'BATCH_AUDIO_BACKEND_OBJECT_REQUIRED')
        # Preserve the selected renderer's request without certifying its
        # capabilities at queue preparation. work-render validates it at run.
        request['audio_backend']=copy.deepcopy(spec['audio_backend'])
    if 'source_consumption' in spec:
        selection(spec['source_consumption'])
        request['source_consumption']=copy.deepcopy(spec['source_consumption'])
    return request


def check_receipt(path,spec,env):
    from editing_runtime import require,sha256,fingerprint,source
    from source_binding import selection
    require(path.is_file(),'BATCH_RECEIPT_MISSING')
    rr=json.loads(path.read_text());folder=path.parent
    expected=render_request(spec)
    require(rr['request_sha256']==fingerprint(expected),'BATCH_REQUEST_MISMATCH')
    require(json.loads((folder/'request.json').read_text())==expected,'BATCH_REQUEST_FILE_MISMATCH')
    require(rr['runtime_files']==env['runtime_files'] and rr['tools']==env['tools'],'BATCH_RECEIPT_ENVIRONMENT_CHANGED')
    for a in rr['artifacts']:
        p=folder/a['path'];require(not Path(a['path']).is_absolute() and p.resolve().is_relative_to(folder.resolve()),'BATCH_ARTIFACT_PATH_INVALID')
        require(p.is_file() and p.stat().st_size==a['bytes'] and sha256(p)==a['sha256'],'BATCH_ARTIFACT_CHANGED')
    if rr['status']=='SUCCEEDED':
        require(rr['result']['version']==spec['expected_version'],'BATCH_OUTPUT_VERSION_MISMATCH')
        output=Path(rr['result']['video']['path']);require(output.resolve().is_relative_to(folder.resolve()),'BATCH_OUTPUT_PATH_INVALID')
        require(sha256(output)==rr['result']['video']['sha256'],'BATCH_OUTPUT_CHANGED')
        actual_consumption=rr['result'].get('source_consumption',{})
        require(rr['result'].get('source_consumption_request')==spec.get('source_consumption') and
                rr['result'].get('source_consumption_request_sha256')==fingerprint(spec.get('source_consumption')),
                'BATCH_SOURCE_CONSUMPTION_REQUEST_MISMATCH')
        require(actual_consumption.get('selection')==selection(spec.get('source_consumption')) and
                actual_consumption.get('status')=='VERIFIED' and actual_consumption.get('adoptable') is True,
                'BATCH_SOURCE_CONSUMPTION_UNVERIFIED')
        binding_ref=actual_consumption.get('binding',{})
        require(Path(binding_ref.get('path','')).resolve()==folder/'source-binding.json',
                'BATCH_SOURCE_BINDING_PATH_INVALID')
        source(binding_ref)
        binding=json.loads((folder/'source-binding.json').read_text())
        require(binding.get('selection')==actual_consumption['selection'] and binding.get('status')=='VERIFIED' and
                binding.get('adoptable') is True,'BATCH_SOURCE_BINDING_UNVERIFIED')
        for bound_source in binding['sources']:
            for logical in bound_source['logical_paths']:
                current=source({'path':logical,'sha256':bound_source['sha256']})
                require(current['path']==bound_source['path'],'BATCH_SOURCE_PATH_CHANGED')
        if 'audio_backend' in spec:
            require(rr['result'].get('audio_backend_request')==spec['audio_backend'] and
                    rr['result'].get('audio_backend_request_sha256')==fingerprint(spec['audio_backend']),
                    'BATCH_AUDIO_BACKEND_REQUEST_MISMATCH')
        timeline=folder/'timeline'/'receipt.json'
        # Old unselected-backend receipts retain their shape. New explicit
        # requests must bind the actual timeline selection as an artifact.
        if 'audio_backend' in spec or timeline.is_file():
            require(any(a['path']=='timeline/receipt.json' for a in rr['artifacts']),
                    'BATCH_AUDIO_BACKEND_RECEIPT_UNBOUND')
            child=json.loads(timeline.read_text())
            require(child['status']=='SUCCEEDED','BATCH_TIMELINE_RECEIPT_FAILED')
            consumption=child.get('result',{}).get('source_consumption',{})
            require(consumption.get('selection')==actual_consumption['selection'] and
                    consumption.get('status')=='VERIFIED' and consumption.get('adoptable') is True,
                    'BATCH_TIMELINE_SOURCE_CONSUMPTION_MISMATCH')
            actual=child.get('result',{}).get('audio_backend')
            if 'audio_backend' in spec:
                require(isinstance(actual,dict) and actual.get('kind')==spec['audio_backend'].get('kind'),
                        'BATCH_AUDIO_BACKEND_SELECTION_MISMATCH')
            if isinstance(actual,dict) and actual.get('helper') is not None:
                helper=actual['helper']
                source({'path':helper['path'],'sha256':helper['sha256']})
                selected=spec.get('audio_backend',{}).get('helper')
                if selected is not None:
                    require(Path(selected['path']).resolve()==Path(helper['path']).resolve() and
                            selected['sha256']==helper['sha256'],'BATCH_AUDIO_BACKEND_HELPER_MISMATCH')
    return rr


def batch_render(q,directory,tools):
    from editing_runtime import exact_keys,require,write_json,fingerprint,sha256,run,ContractError
    from work_ops import validate_document
    action=q.get('action');base=['operation','action','batch_dir']
    extra={'prepare':['batch_id','jobs'],'status':['manifest_sha256'],'run':['manifest_sha256','job_ids','retry_failed']}
    require(action in extra,'BATCH_ACTION_UNSUPPORTED');exact_keys(q,base+extra[action],base+extra[action])
    batch=Path(q['batch_dir']);require(batch.is_absolute(),'ABSOLUTE_BATCH_PATH_REQUIRED');batch=batch.resolve()
    require(not batch.is_relative_to(directory) and not directory.is_relative_to(batch),'BATCH_AND_RECEIPT_DIRS_MUST_BE_SEPARATE')
    if action=='prepare':
        require(isinstance(q['batch_id'],str) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}',q['batch_id']),'BATCH_ID_INVALID')
        require(isinstance(q['jobs'],list) and q['jobs'],'BATCH_JOBS_REQUIRED')
        jobs=[];ids=set();identities=set()
        for spec in q['jobs']:
            keys=['id','store','expected_version'];exact_keys(spec,keys+['audio_backend','source_consumption'],keys)
            render_request(spec)
            jid=spec['id'];require(isinstance(jid,str) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}',jid) and jid not in ids,'BATCH_JOB_ID_INVALID_OR_DUPLICATE');ids.add(jid)
            state=work_state(spec['store']);require(state['version']==spec['expected_version'],'BATCH_WORK_VERSION_CONFLICT')
            validate_document(state['document'],tools)
            store=str(Path(spec['store']).resolve());identity=(store,spec['expected_version'])
            require(identity not in identities,'BATCH_DUPLICATE_WORK_VERSION');identities.add(identity)
            job={'id':jid,'store':store,'expected_version':state['version'],'document_sha256':state['document_sha256']}
            if 'audio_backend' in spec:job['audio_backend']=copy.deepcopy(spec['audio_backend'])
            if 'source_consumption' in spec:job['source_consumption']=copy.deepcopy(spec['source_consumption'])
            jobs.append(job)
        env=environment(tools);require(all('sha256' in info for info in env['tools'].values()),'BATCH_TOOL_UNAVAILABLE')
        manifest={'schema':'local-render-batch/1','batch_id':q['batch_id'],'jobs':jobs,'environment':env}
        batch.mkdir(parents=False,exist_ok=False)
        write_json(batch/'manifest.json',manifest)
        with exclusive(batch):
            db=sqlite3.connect(batch/'queue.sqlite');db.row_factory=sqlite3.Row
            try:
                with db:
                    db.execute('PRAGMA user_version=1')
                    db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
                    db.execute('INSERT INTO metadata VALUES(?,?)',('manifest_sha256',sha256(batch/'manifest.json')))
                    db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,ordinal INTEGER,status TEXT,attempt INTEGER,receipt TEXT,receipt_sha256 TEXT,error TEXT)')
                    db.execute('CREATE TABLE attempts(job_id TEXT,number INTEGER,status TEXT,path TEXT,error TEXT,PRIMARY KEY(job_id,number))')
                    db.executemany('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)',[(j['id'],i,'PENDING',0,None,None,None) for i,j in enumerate(jobs)])
                result=snapshot(db,manifest)
            finally:db.close()
        result['manifest_sha256']=sha256(batch/'manifest.json');write_json(directory/'batch-state.json',result);return result
    require(batch.is_dir(),'BATCH_NOT_FOUND')
    require(sha256(batch/'manifest.json')==q['manifest_sha256'],'BATCH_MANIFEST_CHANGED')
    manifest=json.loads((batch/'manifest.json').read_text());require(manifest['schema']=='local-render-batch/1','BATCH_MANIFEST_SCHEMA')
    def open_bound():
        db=database(batch)
        try:
            binding=db.execute('SELECT value FROM metadata WHERE key=?',('manifest_sha256',)).fetchone()
            require(binding is not None and binding[0]==q['manifest_sha256'],'BATCH_MANIFEST_DATABASE_MISMATCH')
            rows=[dict(r) for r in db.execute('SELECT * FROM jobs ORDER BY ordinal')]
            require([(r['id'],r['ordinal']) for r in rows]==[(j['id'],i) for i,j in enumerate(manifest['jobs'])],'BATCH_JOB_INDEX_MISMATCH')
            for row in rows:
                require(row['status'] in ['PENDING','RUNNING','RENDERED','FAILED','INVALID_OUTPUT'] and type(row['attempt']) is int and row['attempt']>=0,'BATCH_JOB_STATE_INVALID')
                attempts=[dict(r) for r in db.execute('SELECT * FROM attempts WHERE job_id=? ORDER BY number',(row['id'],))]
                require([a['number'] for a in attempts]==list(range(1,row['attempt']+1)),'BATCH_ATTEMPT_INDEX_MISMATCH')
                for a in attempts:
                    require(Path(a['path']).resolve()==batch/'jobs'/row['id']/f"attempt-{a['number']:04d}",'BATCH_ATTEMPT_PATH_INVALID')
                require(row['status'] not in ['RUNNING','RENDERED','INVALID_OUTPUT'] or row['attempt']>0,'BATCH_ATTEMPT_INDEX_MISMATCH')
                if row['status']=='RENDERED':require(row['receipt']==str(batch/'jobs'/row['id']/f"attempt-{row['attempt']:04d}"/'receipt.json') and isinstance(row['receipt_sha256'],str),'BATCH_RECEIPT_INDEX_INVALID')
            return db
        except Exception:
            db.close();raise
    if action=='status':
        db=open_bound()
        try:result=snapshot(db,manifest)
        finally:db.close()
        result['artifact_integrity']='NOT_RECHECKED_STATUS_ONLY';write_json(directory/'batch-state.json',result);return result
    require(isinstance(q['job_ids'],list) and q['job_ids'] and all(isinstance(x,str) for x in q['job_ids']) and len(q['job_ids'])==len(set(q['job_ids'])),'BATCH_JOB_SELECTION_INVALID')
    specs={j['id']:j for j in manifest['jobs']};require(set(q['job_ids'])<=set(specs),'BATCH_JOB_UNKNOWN')
    require(type(q['retry_failed']) is bool,'BATCH_RETRY_BOOLEAN_REQUIRED')
    env=environment(tools);require(env==manifest['environment'],'BATCH_ENVIRONMENT_CHANGED_CREATE_NEW_BATCH')
    events=[]
    with exclusive(batch):
        db=open_bound()
        try:
            def finish(jid,attempt,path,rr):
                status='RENDERED' if rr['status']=='SUCCEEDED' else 'FAILED';error=rr.get('error')
                with db:
                    db.execute('UPDATE jobs SET status=?,receipt=?,receipt_sha256=?,error=? WHERE id=?',(status,str(path),sha256(path),error,jid))
                    db.execute('UPDATE attempts SET status=?,error=? WHERE job_id=? AND number=?',(status,error,jid,attempt))
            for jid in q['job_ids']:
                spec=specs[jid];row=dict(db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
                if row['status']=='RENDERED':
                    try:
                        require(sha256(Path(row['receipt']))==row['receipt_sha256'],'BATCH_RECEIPT_CHANGED')
                        check_receipt(Path(row['receipt']),spec,env)
                        events.append({'job_id':jid,'action':'REUSED_VERIFIED','attempt':row['attempt']});continue
                    except (ValueError,OSError,KeyError) as exc:
                        with db:db.execute('UPDATE jobs SET status=?,error=? WHERE id=?',('INVALID_OUTPUT',str(exc),jid))
                        row['status']='INVALID_OUTPUT'
                if row['status']=='RUNNING':
                    last=db.execute('SELECT * FROM attempts WHERE job_id=? AND number=?',(jid,row['attempt'])).fetchone();receipt=Path(last['path'])/'receipt.json'
                    if receipt.exists():
                        try:
                            rr=check_receipt(receipt,spec,env);finish(jid,row['attempt'],receipt,rr)
                            events.append({'job_id':jid,'action':'RECOVERED_RECEIPT','status':rr['status']});continue
                        except (ValueError,OSError,KeyError) as exc:
                            with db:db.execute('UPDATE jobs SET status=?,error=? WHERE id=?',('INVALID_OUTPUT',str(exc),jid))
                            row['status']='INVALID_OUTPUT'
                    else:
                        # Exclusive lock acquired: no controller or inherited tool child still owns it.
                        with db:
                            db.execute('UPDATE attempts SET status=?,error=? WHERE job_id=? AND number=?',('INTERRUPTED','lock released and no final receipt',jid,row['attempt']))
                            db.execute('UPDATE jobs SET status=? WHERE id=?',('PENDING',jid))
                        row['status']='PENDING';events.append({'job_id':jid,'action':'INTERRUPTED_ATTEMPT_PRESERVED'})
                if row['status'] in ['FAILED','INVALID_OUTPUT'] and not q['retry_failed']:
                    events.append({'job_id':jid,'action':'FAILED_LEFT_UNCHANGED'});continue
                try:state=work_state(spec['store'])
                except (ValueError,OSError,sqlite3.Error) as exc:
                    with db:db.execute('UPDATE jobs SET status=?,error=? WHERE id=?',('FAILED',str(exc),jid))
                    events.append({'job_id':jid,'action':'WORK_UNAVAILABLE'});continue
                # A changed version is a new render request, never an implicit overwrite.
                if state['version']!=spec['expected_version'] or state['document_sha256']!=spec['document_sha256']:
                    with db:db.execute('UPDATE jobs SET status=?,error=? WHERE id=?',('FAILED','BATCH_WORK_VERSION_CONFLICT',jid))
                    events.append({'job_id':jid,'action':'VERSION_CONFLICT'});continue
                attempt=row['attempt']+1;path=batch/'jobs'/jid/f'attempt-{attempt:04d}'
                require(not path.exists(),'BATCH_ATTEMPT_PATH_EXISTS')
                with db:
                    db.execute('INSERT INTO attempts VALUES(?,?,?,?,?)',(jid,attempt,'RUNNING',str(path),None))
                    db.execute('UPDATE jobs SET status=?,attempt=?,error=? WHERE id=?',('RUNNING',attempt,None,jid))
                rr=run(render_request(spec),path,tools)
                check_receipt(path/'receipt.json',spec,env);finish(jid,attempt,path/'receipt.json',rr)
                events.append({'job_id':jid,'action':'RENDER_ATTEMPT','attempt':attempt,'status':rr['status']})
            result=snapshot(db,manifest);result['events']=events;result['artifact_integrity']='SELECTED_COMPLETED_JOBS_VERIFIED'
        finally:db.close()
    write_json(directory/'batch-state.json',result);return result


def execute(q,directory,tools):
    from editing_runtime import ContractError
    try:return {'work-variant-create':variant_create,'work-batch-render':batch_render}[q['operation']](q,directory,tools)
    except sqlite3.Error as exc:raise ContractError('BATCH_STORE_ERROR: '+str(exc)) from exc

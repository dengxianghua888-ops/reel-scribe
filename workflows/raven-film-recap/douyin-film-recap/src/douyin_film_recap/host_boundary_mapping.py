"""Bind saved-host windows to the existing approved boundary transaction only."""
from copy import deepcopy
from pathlib import Path
import re
from . import otio_exchange as x, otio_readback as r, workspace as w
from .boundary import proposal_hash
from .boundary_apply import apply_boundary_proposal, BOARD
from .revision import assert_revision_base


def require(ok, code):
    if not ok:
        raise x.ExchangeError(code)


def compare_projection(candidate, host):
    entities=r._entities(candidate)
    require(set(entities)==set(host['entities']), 'HOST_MAPPING_INSTANCE_SET_MISMATCH')
    for iid, entity in entities.items():
        require(all(entity[k]==host['entities'][iid][k] for k in (*r.FIELDS,'track_role','track_kind')), 'HOST_MAPPING_WINDOW_MISMATCH')
    ends={t['track_id']:x.rational(max((x.fraction(c['target_start'])+x.fraction(c['duration']) for c in t['clips']),default=0))
          for t in candidate['tracks'] if t['clips']}
    require(ends==host['track_ends'], 'HOST_MAPPING_TRACK_END_MISMATCH')


def apply_host_boundary(work_dir, *, export_package, saved_snapshot, base, proposal,
                        mapping, config, timebases, raw_cards=None, evidence_root=None):
    """Explicit exact scope never substitutes for editorial/boundary approval."""
    require(isinstance(mapping,dict) and set(mapping)=={
        'schema','snapshot_sha256','export_package_sha256','boundary_proposal_hash',
        'instance_ids','track_ends'}, 'HOST_MAPPING_FIELDS_REQUIRED')
    mapping=deepcopy(mapping)
    for key in ('snapshot_sha256','export_package_sha256','boundary_proposal_hash'):
        require(isinstance(mapping[key],str) and re.fullmatch('[0-9a-f]{64}',mapping[key]) is not None,
                'HOST_MAPPING_DIGEST_REQUIRED')
    require(isinstance(mapping['track_ends'],dict) and bool(mapping['track_ends']), 'HOST_MAPPING_TRACK_SCOPE')
    for tid, change in mapping['track_ends'].items():
        require(isinstance(tid,str) and bool(tid) and isinstance(change,dict) and set(change)=={'before','after'},
                'HOST_MAPPING_TRACK_SCOPE')
        for value in change.values():
            require(isinstance(value,dict) and set(value)=={'numerator','denominator'} and
                    type(value['numerator']) is int and type(value['denominator']) is int and
                    value['numerator']>=0 and value['denominator']>0,'HOST_MAPPING_RATIONAL_REQUIRED')
    require(mapping['schema']=='film-host-boundary-mapping/1', 'HOST_MAPPING_SCHEMA')
    require(mapping['boundary_proposal_hash']==proposal_hash(proposal),'HOST_MAPPING_PROPOSAL_HASH')
    require(proposal.editorial_decision=='approved' and proposal.approved_proposal_hash==proposal_hash(proposal),'HOST_MAPPING_APPROVED_PROPOSAL_REQUIRED')
    require(isinstance(mapping['instance_ids'],list) and all(isinstance(i,str) and bool(i) for i in mapping['instance_ids']) and
            len(mapping['instance_ids'])==len(set(mapping['instance_ids'])), 'HOST_MAPPING_INSTANCE_SCOPE')
    def check_scope():
        r._verified_package(Path(export_package),mapping['export_package_sha256'])
        r._verified_snapshot(saved_snapshot,mapping['snapshot_sha256'])
        initial=r.propose_saved_readback(export_package,work_dir,saved_snapshot)
        require(initial['current_revision_base']==base,'HOST_MAPPING_STALE_CURRENT')
        require(not initial['opaque'],'HOST_MAPPING_OPAQUE_UNSUPPORTED')
        require(all(c['code']=='HOST_TRACK_END_REQUIRES_EXPLICIT_MAPPING' for c in initial['conflicts']), 'HOST_MAPPING_UNRESOLVED_CONFLICT')
        require(all(c['classification']=='host_only' for c in initial['changes']), 'HOST_MAPPING_CURRENT_BRANCH_CHANGED')
        instances={c['entity_id'] for c in initial['changes'] if c['field']!='track_end'}
        ends={c['entity_id']:{'before':c['current'],'after':c['host']} for c in initial['changes'] if c['field']=='track_end'}
        require(instances and instances==set(mapping['instance_ids']) and ends==mapping['track_ends'], 'HOST_MAPPING_EXACT_SCOPE_REQUIRED')
        r._verified_package(Path(export_package),mapping['export_package_sha256'])
        r._verified_snapshot(saved_snapshot,mapping['snapshot_sha256'])
    check_scope()
    package=Path(export_package)

    def check(active, artifacts):
        assert_revision_base(work_dir,base)
        check_scope()
        seal,package_sha=r._verified_package(package,mapping['export_package_sha256'])
        manifest,_,snapshot_sha=r._verified_snapshot(saved_snapshot,mapping['snapshot_sha256'])
        binding=x._json(r._sealed_member(package,seal,'export-binding.json','PACKAGE_MEMBER_HASH_MISMATCH'))
        original=x._json(r._sealed_member(package,seal,'projection.json','PACKAGE_MEMBER_HASH_MISMATCH'))
        require(manifest['base_binding_sha256']==w.sha(package/'export-binding.json') and manifest['export_id']==binding['export_id'],'HOST_MAPPING_EXPORT_BINDING')
        require(r.observe_saved_origin(manifest)['state']=='UNCHANGED_SAVED_FILE','HOST_MAPPING_SAVED_ORIGIN_CHANGED')
        host=r.parse_snapshot(saved_snapshot,original,binding,expected_seal_sha256=snapshot_sha)
        require(not host['problems'] and not host['opaque'] and not original['captions'], 'HOST_MAPPING_UNSUPPORTED_DEPENDENCY')
        board=artifacts[BOARD];sha=x.digest(board)
        projected=x.compile_cut_projection(board,storyboard_sha256=sha,
            authority={'storyboard_sha256':sha,'workspace_generation':base['generation']},
            profile=original['profile'],media_facts={k:deepcopy(v['facts']) for k,v in original['resources'].items()},
            identity_map=original['identity_map'],captions=[])
        require({k:v['sha256'] for k,v in projected['resources'].items()}==binding['source_bindings'], 'HOST_MAPPING_RESOURCE_SET_MISMATCH')
        compare_projection(projected,host)
        r._verified_package(package,package_sha);r._verified_snapshot(saved_snapshot,snapshot_sha)
        require(r.observe_saved_origin(manifest)['state']=='UNCHANGED_SAVED_FILE','HOST_MAPPING_SAVED_ORIGIN_CHANGED')
        return {'schema':'host-boundary-binding/1','mapping':deepcopy(mapping),'mapping_sha256':x.digest(mapping),
                'current_revision_base_sha256':x.digest(base)}
    result=apply_boundary_proposal(work_dir,proposal=proposal,base=base,config=config,timebases=timebases,
        raw_cards=raw_cards,evidence_root=evidence_root,candidate_check=check)
    return {**result,'host_mapping':mapping,'qc_status':'NOT_RUN','semantic_and_av_review_inherited':False}

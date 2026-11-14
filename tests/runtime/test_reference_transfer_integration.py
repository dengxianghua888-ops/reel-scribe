"""Cross-operation handoff; declared fixture observations are not visual acceptance."""
import copy
import json
from pathlib import Path
import sys
import pytest
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'runtime'),str(Path(__file__).resolve().parent)]
from test_creation_brief import case,work_case,caption_case
from test_reference_transfer import reference
import editing_runtime as rt
import work_ops


def test_registered_reference_request_compiles_only_target_presentation(reference):
    request,out,tools,doc=reference
    result=rt.execute(request,out,tools)
    prepared=json.loads((out/'prepared-request.json').read_bytes())
    assert rt.fingerprint(prepared)==result['prepared_request_sha256']
    for variant in prepared['variants']:
        dest=out/variant['id'];dest.mkdir()
        compiled=rt.execute({'operation':'style-recipe-compile','document':doc,
            'expected_document_sha256':rt.fingerprint(doc),'base_version':request['expected_version'],
            **{k:copy.deepcopy(variant[k]) for k in ['recipe','expected_recipe_sha256','capabilities','scope']}},dest,tools)
        candidate=json.loads((dest/'candidate.json').read_bytes())['document']
        assert candidate['plan']==doc['plan']
        assert candidate['captions']==doc['captions']
        assert candidate['audio_tracks']==doc['audio_tracks']
        assert compiled['document_sha256']==rt.fingerprint(candidate)
    with work_ops.connect(request['store']) as db:state=work_ops.load(db)
    assert state['document']==doc and state['version']==request['expected_version']
    assert prepared['operation']=='style-recipe-preview' and 'reference' not in prepared


def test_registered_reference_dependency_profile_has_no_network_provider():
    from dependency_discovery import ATOMIC_REQUIREMENTS
    assert ATOMIC_REQUIREMENTS['reference-transfer-prepare']==('sqlite','ffprobe')
    assert ATOMIC_REQUIREMENTS['creation-recommendation']==('sqlite',)

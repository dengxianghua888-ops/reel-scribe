"""Explicit local caption selection in a preparation-only brief."""
import copy,json
import pytest
from test_creation_brief import case,caption_case,work_case
import creation_brief_ops as mod
import editing_runtime as rt

def local(case):
 q,out,tools=caption_case(case)
 for v in q['parameters']['variants']:
  size=v['recipe']['parameters']['caption_style']['font_size'];v['recipe']['parameters']={'caption_overrides':{'old':{'font_size':size}}};v['expected_recipe_sha256']=rt.fingerprint(v['recipe']);v['capabilities']=['caption-cue-style'];v['scope'].update(caption_ids=['old'],caption_style=False)
 return q,out,tools

def test_prepares_only_explicit_cues(case):
 q,out,tools=local(case);r=mod.execute(q,out,tools);assert not r['executed'];d=json.loads((out/'prepared-request.json').read_bytes());assert all(v['scope']['caption_ids']==['old'] and not v['scope']['caption_style'] for v in d['variants'])

@pytest.mark.parametrize('mutation,error',[
 (lambda v:v['scope'].update(caption_ids=[]),'SCOPE_REQUIRED'),
 (lambda v:v['scope'].update(caption_ids=['old','unknown']),'SCOPE_REQUIRED'),
 (lambda v:v['scope'].update(caption_style=True),'GLOBAL_SCOPE_FORBIDDEN'),
 (lambda v:v.update(capabilities=['caption-style']),'CAPABILITY_REQUIRED'),
 (lambda v:v['scope'].update(clip_ids=['full']),'SCOPE_TOO_BROAD'),
])
def test_rejects_unselected_or_expanded_scope(case,mutation,error):
 q,out,tools=local(case);mutation(q['parameters']['variants'][0])
 with pytest.raises(ValueError,match=error):mod.execute(q,out,tools)
 assert not (out/'prepared-request.json').exists()

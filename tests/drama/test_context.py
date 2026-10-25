import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'runtime'))
from drama_domain import assemble_context


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.doc=json.loads((Path(__file__).parent/'fixtures/return-key.json').read_text())
        self.resources={self.doc['style_ref']['path']:'# 风格规范\n低饱和度；保留动作与环境声。\n'}

    def context(self, budget, source_sha256=None):
        return assemble_context(self.doc,'SC02',budget,source_sha256,self.resources)

    def test_complete_scene_context_has_protected_state_and_causes(self):
        before=copy.deepcopy(self.doc)
        result=self.context(32000,source_sha256='a'*64)
        self.assertEqual(result['status'],'PASS',result['findings'])
        self.assertTrue(result['sendable'])
        payload=result['payload']
        self.assertEqual(payload['task']['preserve'],self.doc['task']['preserve'])
        self.assertEqual(payload['pre_state']['snapshot_id'],'ST01')
        self.assertEqual(payload['planned_post_state']['snapshot_id'],'ST02')
        self.assertEqual({x['entity_id'] for x in payload['entities']},{'C01','C02','P01','L01','L02'})
        self.assertIn('E02',{x['event_id'] for x in payload['events']})
        self.assertIn('BG01',{x['background_id'] for x in payload['background']})
        self.assertEqual(payload['pre_state']['foreshadow'][0]['foreshadow_id'],'F01')
        self.assertEqual(result['source']['sha256_kind'],'caller_supplied_file_bytes_unverified')
        self.assertTrue(result['ready_for_generation'])
        self.assertEqual(result['external_resources'][0]['status'],'LOADED_UTF8_TEXT')
        self.assertEqual(payload['style_document']['text'],self.resources[self.doc['style_ref']['path']])
        self.assertEqual(payload['style_document']['encoding'],'utf-8')
        self.assertEqual(before,self.doc)
        result['payload']['task']['title']='changed'
        self.assertEqual(self.doc['task']['title'],'归还钥匙')

    def test_D20_budget_overflow_preserves_full_payload_and_refuses_send(self):
        complete=self.context(32000)
        result=self.context(complete['budget']['actual']-1)
        self.assertEqual(result['status'],'FAIL')
        self.assertFalse(result['sendable'])
        self.assertEqual(result['payload'],complete['payload'])
        self.assertFalse(result['budget']['truncated'])
        self.assertEqual(result['findings'][0]['rule_id'],'CONTEXT_BUDGET_EXCEEDED')
        self.assertEqual(result['findings'][0]['evidence']['excess_chars'],1)

    def test_budget_exact_boundary_and_unit(self):
        result=self.context(32000)
        expected=len(json.dumps(result['payload'],ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False))
        self.assertEqual(result['budget']['actual'],expected)
        self.assertEqual(self.context(expected)['status'],'PASS')
        self.assertEqual(result['budget']['unit'],'unicode_codepoints_compact_sorted_json')

    def test_external_style_path_alone_is_incomplete(self):
        result=assemble_context(self.doc,'SC02',32000)
        self.assertEqual(result['status'],'UNCERTAIN')
        self.assertFalse(result['sendable'])
        self.assertFalse(result['ready_for_generation'])
        self.assertEqual(result['needs_external_resources'],[self.doc['style_ref']['path']])

    def test_explicit_required_event_is_loaded_not_excluded(self):
        self.doc['scenes'][1]['context_refs'].append('E09')
        result=self.context(100000)
        self.assertEqual(result['status'],'PASS',result['findings'])
        self.assertIn('E09',{e['event_id'] for e in result['payload']['events']})
        self.assertNotIn('E09',{e['object_ref'] for e in result['excluded']})
        self.assertIn('E09',result['required_refs'])

    def test_required_cross_scene_shot_is_rejected_until_supported(self):
        self.doc['scenes'][1]['context_refs'].append('SH01')
        result=self.context(100000)
        self.assertEqual(result['status'],'FAIL')
        self.assertFalse(result['sendable'])
        self.assertIsNone(result['payload'])
        self.assertEqual(result['unsupported_required_refs'],['SH01'])
        self.assertEqual(result['excluded'],[])

    def test_explicit_event_causes_are_included(self):
        self.doc['scenes'][0]['context_refs'].append('E09')
        self.doc['events'][-1]['causes']=['E08']
        result=assemble_context(self.doc,'SC01',100000,resources=self.resources)
        self.assertEqual(result['status'],'PASS',result['findings'])
        self.assertTrue({'E08','E09'} <= {e['event_id'] for e in result['payload']['events']})

    def test_loaded_proposition_basis_recursively_loads_its_background(self):
        self.doc['background'].extend([
            {'background_id':'BG99','text':'补充依据','basis':{'kind':'authored','reference':'BG98'}},
            {'background_id':'BG98','text':'更早依据','basis':{'kind':'authored'}}])
        self.doc['propositions'][0]['basis']['reference']='BG99'
        result=self.context(100000)
        self.assertEqual(result['status'],'PASS',result['findings'])
        self.assertTrue({'BG98','BG99'} <= {b['background_id'] for b in result['payload']['background']})
        self.assertNotIn('BG99',{b['object_ref'] for b in result['excluded']})

    def test_unsupported_nested_basis_cannot_be_silently_dropped(self):
        self.doc['propositions'][0]['basis']['reference']='SH01'
        result=self.context(100000)
        self.assertEqual(result['status'],'FAIL')
        self.assertIsNone(result['payload'])
        self.assertFalse(result['sendable'])

    def test_missing_scene_or_bad_budget_or_hash(self):
        for scene,budget,sha in [('unknown',100,None),('SC02',-1,None),('SC02',True,None),('SC02',32000,'bad')]:
            with self.subTest(scene=scene,budget=budget,sha=sha):
                result=assemble_context(self.doc,scene,budget,sha)
                self.assertEqual(result['status'],'FAIL');self.assertFalse(result['sendable'])


if __name__=='__main__': unittest.main()

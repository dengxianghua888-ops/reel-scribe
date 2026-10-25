import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'runtime'))
from drama_domain import validate_variant


class VariantTests(unittest.TestCase):
    def setUp(self):
        fixtures=Path(__file__).parent/'fixtures'
        self.doc=json.loads((fixtures/'return-key.json').read_text())
        self.variant=json.loads((fixtures/'return-key-flashback.json').read_text())

    def assert_rule(self,rule):
        report=validate_variant(self.doc,self.variant)
        self.assertEqual(report['status'],'FAIL',report['findings'])
        self.assertIn(rule,{f['rule_id'] for f in report['findings']})

    def test_D10_valid_local_flashback_has_17_leaves_150_seconds(self):
        before=copy.deepcopy((self.doc,self.variant))
        report=validate_variant(self.doc,self.variant)
        self.assertEqual(report['status'],'PASS',report['findings'])
        self.assertEqual(report['active_leaf_count'],17)
        self.assertEqual(report['estimated_duration_sec'],150)
        self.assertFalse(report['source_group_counted'])
        self.assertEqual(report['state_coverage'],'NAMED_PARTIAL_FIELDS_ONLY')
        self.assertEqual(report['media_review'],'NOT_RUN')
        self.assertEqual(before,(self.doc,self.variant))

    def test_D11_past_state_cannot_replace_current_state(self):
        state=copy.deepcopy(self.variant['boundary_states'][0])
        state['snapshot_id']='ST-RETURN-WRONG'
        state['entity_state']['P01']['custodian']='C01'
        self.variant['boundary_states'].append(state)
        self.variant['leaf_shots'][-1]['boundary_state_ref']=state['snapshot_id']
        self.assert_rule('RECALL_CONTAMINATES_CURRENT_STATE')

    def test_past_boundary_cannot_be_used_by_present_leaf(self):
        self.variant['leaf_shots'][-1]['boundary_state_ref']='ST-FB01-PAST'
        self.assert_rule('BOUNDARY_LAYER')

    def test_shared_current_boundary_cannot_lie_about_base_state(self):
        self.variant['boundary_states'][0]['entity_state']['P01']['custodian']='C01'
        self.assert_rule('BOUNDARY_CURRENT_BASE_MISMATCH')

    def test_parent_duration_cannot_be_counted_twice(self):
        self.variant['edit']['count_source_group_duration']=True
        self.assert_rule('VARIANT_DOUBLE_COUNT')

    def test_stale_content_revision_rejected(self):
        self.variant['base_content_revision']='older-content'
        self.assert_rule('VARIANT_BASE_CONFLICT')

    def test_rebinding_cannot_change_speaker(self):
        self.variant['dialogue_rebindings'][0]['speaker_id']='C01'
        self.assert_rule('DIALOGUE_IDENTITY_CHANGED')

    def test_rebinding_must_remove_parent_reference(self):
        self.variant['dialogue_rebindings'][0]['to_shot_refs']=['SH08','SH08-A']
        self.assert_rule('DIALOGUE_REBINDING_TARGET')

    def test_new_recall_event_cannot_have_current_physical_delta(self):
        self.variant['new_events'][0]['current_physical_delta']=[{'target':'P01.custodian','after':'C01'}]
        self.assert_rule('RECALL_CONTAMINATES_CURRENT_STATE')

    def test_required_beat_not_lost_in_replacement(self):
        self.variant['leaf_shots'][1]['beat_refs']=[]
        self.assert_rule('REQUIRED_BEAT_UNCOVERED')

    def test_range_and_duration_consistency(self):
        self.variant['leaf_shots'][1]['estimated_duration_sec']=5
        self.assert_rule('VARIANT_DURATION')

    def test_malformed_variant_fails_without_exception(self):
        for value in (None,[],{}, {'schema':[]}, {'schema':'drama-variant/0.1'}):
            self.assertEqual(validate_variant(self.doc,value)['status'],'FAIL')
        for mutate in (
            lambda v:v['edit'].update(replaces_shot_ref=[]),
            lambda v:v['dialogue_rebindings'][0].update(dialogue_id=[]),
            lambda v:v['new_beats'][0].update(event_refs=[{}]),
        ):
            v=copy.deepcopy(self.variant);mutate(v)
            self.assertEqual(validate_variant(self.doc,v)['status'],'FAIL')

    def test_variant_asset_cannot_promote_planned_path_to_actual(self):
        self.variant['new_assets'][0].update(status='reference_available',path='/tmp/fake.png')
        self.assert_rule('ASSET_BINDING_REQUIRED')

    def test_uncertain_main_plan_is_not_promoted_by_valid_variant(self):
        next(d for d in self.doc['dialogues'] if d['dialogue_id']=='D08')['estimated_speech_sec']=18
        report=validate_variant(self.doc,self.variant)
        self.assertEqual(report['status'],'UNCERTAIN')
        self.assertIn('SPEECH_PLAN_CAPACITY',{f['rule_id'] for f in report['findings']})

    def test_historical_partial_state_checks_entity_and_variant_references(self):
        for field,value,rule in [('custodian','C99','BOUNDARY_ENTITY_REFERENCE'),
                                 ('custodian','L01','BOUNDARY_ENTITY_REFERENCE'),
                                 ('location_id','C01','BOUNDARY_ENTITY_REFERENCE'),
                                 ('variant_id','C01-V01','VARIANT_OWNER')]:
            with self.subTest(field=field,value=value):
                variant=copy.deepcopy(self.variant)
                variant['boundary_states'][1]['entity_state']['P01'][field]=value
                report=validate_variant(self.doc,variant)
                self.assertEqual(report['status'],'FAIL')
                self.assertIn(rule,{f['rule_id'] for f in report['findings']})

    def test_new_asset_cannot_collide_with_character_id(self):
        self.variant['new_assets'][0]['asset_id']='C01'
        self.variant['leaf_shots'][1]['asset_refs']=['C01']
        self.assert_rule('VARIANT_GLOBAL_ID_COLLISION')

    def test_new_beat_and_event_require_valid_source_scene(self):
        for table in ('new_beats','new_events'):
            v=copy.deepcopy(self.variant)
            v[table][0]['scene_id']='SC99'
            result=validate_variant(self.doc,v)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('VARIANT_SCENE',{f['rule_id'] for f in result['findings']})

    def test_new_event_basis_must_resolve(self):
        self.variant['new_events'][0]['basis']['reference']='BG99'
        self.assert_rule('DANGLING_REFERENCE')


if __name__=='__main__': unittest.main()

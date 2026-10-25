"""Frozen plan mutations; PASS here never represents media acceptance."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'runtime'))
from drama_domain import validate_content


def load_fixture():
    return json.loads((Path(__file__).parent/'fixtures/return-key.json').read_text())


def by_id(document, table, ident):
    key={'shots':'shot_id','assets':'asset_id','entities':'entity_id',
         'snapshots':'snapshot_id','dialogues':'dialogue_id','scenes':'scene_id'}[table]
    return next(x for x in document[table] if x[key]==ident)


class DomainTests(unittest.TestCase):
    def setUp(self): self.doc=load_fixture()
    def assert_rule(self, rule, status='FAIL'):
        result=validate_content(self.doc)
        self.assertEqual(result['status'],status,result['findings'])
        self.assertIn(rule,{x['rule_id'] for x in result['findings']})
        for f in result['findings']:
            self.assertTrue({'rule_id','object_refs','field','method','result','evidence','impact'} <= set(f))
        return result

    def test_D01_main_plan_and_no_mutation(self):
        before=copy.deepcopy(self.doc); result=validate_content(self.doc)
        self.assertEqual(result['status'],'PASS',result['findings'])
        self.assertEqual(result['counts']['shots'],15)
        self.assertEqual(result['counts']['beats'],9)
        self.assertEqual(result['counts']['dialogues'],12)
        self.assertEqual(result['estimated_duration_sec'],150)
        self.assertTrue(all(a['actual_binding'] is None for a in self.doc['assets']))
        self.assertEqual(before,self.doc)

    def test_D02_explicit_reference_identity_mismatch(self):
        shot=by_id(self.doc,'shots','SH08')
        shot['asset_refs'].remove('A01');shot['asset_refs'].append('A02')
        shot['reference_bindings']=[{'asset_id':'A02','entity_id':'C01','control_scope':['identity']}]
        result=self.assert_rule('REFERENCE_IDENTITY_MISMATCH')
        finding=next(f for f in result['findings'] if f['rule_id']=='REFERENCE_IDENTITY_MISMATCH')
        self.assertEqual(set(finding['object_refs']),{'SH08','C01','A02'})

    def test_D03_display_names_are_not_identity_keys(self):
        by_id(self.doc,'entities','C02')['name']='林青'
        self.assertEqual(validate_content(self.doc)['status'],'PASS')

    def test_D04_false_proposition_true_belief_allowed(self):
        q=next(x for x in self.doc['propositions'] if x['proposition_id']=='Q01')
        k=next(x for x in self.doc['snapshots'][0]['knowledge'] if x['holder_id']=='C01' and x['proposition_id']=='Q01')
        self.assertIs(q['truth'],False);self.assertEqual(k['attitude'],'believes_true')
        self.assertEqual(validate_content(self.doc)['status'],'PASS')

    def test_D05_direct_witness_not_established_is_uncertain(self):
        k=next(x for x in by_id(self.doc,'snapshots','ST01')['knowledge'] if x['holder_id']=='C02' and x['proposition_id']=='Q05')
        k.update(basis_kind='observed',basis_event_refs=['E01'],reason='亲见试锁')
        self.assert_rule('WITNESS_NOT_ESTABLISHED','UNCERTAIN')
        self.assertEqual(k['attitude'],'believes_true')

    def test_D06_future_event_cannot_authorize_current_knowledge(self):
        k=next(x for x in by_id(self.doc,'snapshots','ST01')['knowledge'] if x['holder_id']=='C01' and x['proposition_id']=='Q03')
        k.update(attitude='believes_true',basis_event_refs=['E08'])
        self.assert_rule('FUTURE_EVENT_AS_EVIDENCE')

    def test_D07_audience_certainty_requires_evidence(self):
        k=next(x for x in by_id(self.doc,'snapshots','ST01')['knowledge'] if x['holder_id']=='AUDIENCE' and x['proposition_id']=='Q01')
        k.update(attitude='believes_true',certainty='certain',basis_kind='inferred',basis_event_refs=['E02'])
        # Keep explicit delta consistent so this isolates epistemic uncertainty.
        delta=next(x for x in by_id(self.doc,'scenes','SC02')['delta'] if x['target']=='AUDIENCE.Q01')
        delta['before']='believes_true'
        self.assert_rule('AUDIENCE_CERTAINTY_UNSUPPORTED','UNCERTAIN')

    def test_D08_handoff_must_match_poststate(self):
        by_id(self.doc,'snapshots','ST01')['entity_state']['P01']['custodian']='C01'
        result=self.assert_rule('STATE_DELTA_MISMATCH')
        self.assertTrue(any({'ST01','P01','E02'} <= set(f['object_refs']) for f in result['findings']))

    def test_D09_custody_is_not_every_moment_of_contact(self):
        shot=by_id(self.doc,'shots','SH06')
        shot['action']='钥匙短暂置于父亲侧台面，末尾左手重拿；保管人为C02'
        self.assertEqual(validate_content(self.doc)['status'],'PASS')

    def test_D12_required_beat_cannot_disappear(self):
        by_id(self.doc,'shots','SH09')['beat_refs'].remove('B05')
        self.assert_rule('REQUIRED_BEAT_UNCOVERED')

    def test_D13_many_beats_in_one_shot_allowed(self):
        self.assertEqual(by_id(self.doc,'shots','SH13')['beat_refs'],['B08','B09'])
        self.assertEqual(validate_content(self.doc)['status'],'PASS')

    def test_D14_unknown_asset(self):
        by_id(self.doc,'shots','SH09')['asset_refs'].append('A999')
        self.assert_rule('DANGLING_REFERENCE')

    def test_D15_path_is_not_actual_binding(self):
        by_id(self.doc,'assets','A01').update(status='reference_available',path='/tmp/planned.png')
        self.assert_rule('ASSET_BINDING_REQUIRED')

    def test_D16_estimate_is_not_a_measured_duration(self):
        by_id(self.doc,'shots','SH09')['actual_duration_sec']=14
        self.assert_rule('MEASUREMENT_UNBOUND')

    def test_D17_speech_budget_is_planning_uncertainty(self):
        by_id(self.doc,'dialogues','D08')['estimated_speech_sec']=18
        self.assert_rule('SPEECH_PLAN_CAPACITY','UNCERTAIN')

    def test_D19_valid_document_does_not_promote_reviews(self):
        result=validate_content(self.doc)
        for field in ('semantic_review','media_review','host_adoption'): self.assertEqual(result[field],'NOT_RUN')
        for field in ('visual_review','audio_review','host_adoption'): self.assertEqual(self.doc['review_scope'][field],'NOT_RUN')

    def test_duplicate_ids_rejected_but_same_names_allowed(self):
        self.doc['assets'].append(copy.deepcopy(self.doc['assets'][0]))
        self.assert_rule('DUPLICATE_ID')

    def test_cross_entity_variant_rejected(self):
        self.doc['snapshots'][0]['entity_state']['C01']['variant_id']='C02-V01'
        self.assert_rule('VARIANT_OWNER')

    def test_dialogue_backrefs_checked(self):
        by_id(self.doc,'dialogues','D08')['shot_refs']=['SH10']
        self.assert_rule('DIALOGUE_BACKREFERENCE')

    def test_claimed_bound_snapshot_requires_provenance(self):
        self.doc['snapshots'][0]['authority']='bound_revision'
        self.assert_rule('UNBOUND_AUTHORITY')

    def test_causal_cycle_rejected(self):
        self.doc['events'][0]['causes']=['E02'];self.doc['events'][1]['causes']=['E01']
        self.assert_rule('CAUSAL_CYCLE')

    def test_candidate_prestate_requires_producer_scene_dependency(self):
        by_id(self.doc,'snapshots','ST01')['authority']='candidate_dependency'
        by_id(self.doc,'scenes','SC02')['candidate_dependencies']=[]
        self.assert_rule('CANDIDATE_PRESTATE_DEPENDENCY')

    def test_declared_candidate_prestate_is_valid_without_user_adoption(self):
        by_id(self.doc,'snapshots','ST01')['authority']='candidate_dependency'
        self.assertEqual(validate_content(self.doc)['status'],'PASS')

    def test_future_snapshot_cannot_supply_earlier_scene(self):
        by_id(self.doc,'snapshots','ST01')['story_position']=99
        self.assert_rule('SCENE_STATE_POSITION')

    def test_planned_clock_cannot_overlap_or_have_unrepresented_gaps(self):
        for rng in ([0,10],[9,19]):
            self.doc=load_fixture()
            by_id(self.doc,'shots','SH02')['planned_range_sec']=rng
            self.assert_rule('SHOT_RANGE_ORDER')

    def test_changed_physical_field_cannot_omit_explicit_delta(self):
        for state in self.doc['snapshots']:
            state['entity_state']['C02']['hand']='right' if state['snapshot_id']=='ST00' else 'left'
        self.assert_rule('STATE_CHANGE_WITHOUT_DELTA')

    def test_new_physical_state_field_is_unknown_before_not_fabricated(self):
        for state in self.doc['snapshots'][1:]:
            state['entity_state']['C02']['hand']='left'
        self.assert_rule('STATE_FIELD_COVERAGE_CHANGED','UNCERTAIN')

    def test_invalid_shapes_report_fail_instead_of_crashing(self):
        bad_inputs=[None, [], {}, {'schema':'drama-content/0.1'}]
        for value in bad_inputs:
            with self.subTest(value=value): self.assertEqual(validate_content(value)['status'],'FAIL')
        for table in ('entities','snapshots','shots','scenes','assets'):
            with self.subTest(table=table):
                d=load_fixture();d[table][0]=None
                self.assertEqual(validate_content(d)['status'],'FAIL')
        for mutate in (
            lambda d:d['snapshots'][0]['entity_state']['C01'].update(variant_id={}),
            lambda d:d['snapshots'][0]['knowledge'][0].update(basis_event_refs=[{}]),
            lambda d:d['scenes'][0]['delta'][0].update(event_refs=[{}]),
        ):
            d=load_fixture();mutate(d);self.assertEqual(validate_content(d)['status'],'FAIL')


if __name__=='__main__': unittest.main()

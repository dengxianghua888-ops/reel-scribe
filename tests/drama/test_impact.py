"""Mutation tests against the frozen story, not synthetic editorial success."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'runtime'))
from drama_impact import analyze_impact

EXAMPLE = ROOT / 'workflows/raven-drama-production/examples/return-key'


def find(document, collection, key, value):
    return next(row for row in document[collection] if row[key] == value)


class ImpactTests(unittest.TestCase):
    def setUp(self):
        self.before = json.loads((EXAMPLE / 'drama-content.json').read_text())
        self.after = copy.deepcopy(self.before)

    def test_unchanged_candidate_has_no_impacts_or_actions(self):
        report = analyze_impact(self.before, self.after)
        self.assertEqual('PASS', report['status'])
        self.assertEqual([], report['deterministic_impacts'])
        self.assertEqual([], report['semantic_review_impacts'])
        self.assertEqual([], report['media_actions'])
        self.assertEqual([], report['scope_candidates']['domain_note_keys'])

    def test_indirect_background_change_refreshes_every_changed_context(self):
        from drama_domain import assemble_context, validate_content
        for content in (self.before,self.after):
            content['background'].extend([
                {'background_id':'BG99','text':'source','basis':{'kind':'authored','reference':'BG98'}},
                {'background_id':'BG98','text':'original','basis':{'kind':'authored'}}])
            content['propositions'][0]['basis']['reference']='BG99'
        self.after['background'][-1]['text']='changed'
        resources={self.before['style_ref']['path']:'style'}
        changed=set()
        for content in (self.before,self.after):
            self.assertEqual('PASS',validate_content(content)['status'])
        for scene in self.before['scenes']:
            sid=scene['scene_id']
            old=assemble_context(self.before,sid,100000,resources=resources)
            new=assemble_context(self.after,sid,100000,resources=resources)
            if old['payload']!=new['payload']:
                changed.add(sid)
        self.assertTrue(changed)
        report=analyze_impact(self.before,self.after)
        self.assertTrue(changed <= set(report['scope_candidates']['context_scene_ids']))
        self.assertFalse(changed & set(report['unaffected']['objects']['scenes']))

    def test_shot_and_dialogue_only_entity_changes_refresh_context(self):
        for field in ('visible_characters','speaker_id'):
            with self.subTest(field=field):
                before=copy.deepcopy(self.before)
                entity=copy.deepcopy(before['entities'][0])
                entity['entity_id']='C03'
                entity['variants'][0]['variant_id']='C03-V01'
                before['entities'].append(entity)
                if field=='visible_characters':
                    before['shots'][0][field].append('C03')
                else:
                    before['dialogues'][0][field]='C03'
                after=copy.deepcopy(before)
                after['entities'][-1]['name']='new name'
                report=analyze_impact(before,after)
                self.assertIn('SC01',report['scope_candidates']['context_scene_ids'])

    def test_d21_caption_style_preserves_story_voice_and_character_requirements(self):
        self.after['style_ref']['caption_style'] = {'font_size': 42, 'safe_bottom_ratio': .13}
        report = analyze_impact(self.before, self.after)
        scope = report['scope_candidates']
        self.assertEqual(12, len(scope['caption_asset_ids']))
        self.assertEqual([], scope['dialogue_audio_asset_ids'])
        self.assertEqual([], scope['visual_shot_ids'])
        self.assertEqual(['SC01', 'SC02', 'SC03'], scope['context_scene_ids'])
        self.assertFalse(any(row['rule_id'] == 'STORY_CONSEQUENCES_REQUIRE_REVIEW'
                             for row in report['semantic_review_impacts']))
        self.assertEqual(15, len(report['unaffected']['objects']['shots']))
        self.assertEqual(4, len(report['unaffected']['objects']['snapshots']))
        self.assertEqual(12, len(report['unaffected']['objects']['dialogues']))
        self.assertIn('A01', report['unaffected']['objects']['assets'])
        self.assertIn('A06', report['unaffected']['objects']['assets'])
        self.assertEqual('NOT_RUN', report['media_review'])

    def test_caption_asset_presentation_stays_local(self):
        cap = find(self.after, 'assets', 'asset_id', 'CAP-D08')
        cap['presentation'] = {'font_size': 42, 'safe_bottom_ratio': .13}
        report = analyze_impact(self.before, self.after)
        self.assertEqual(['CAP-D08'], report['scope_candidates']['caption_asset_ids'])
        self.assertEqual([], report['scope_candidates']['dialogue_audio_asset_ids'])
        self.assertIn('AUD-D08', report['unaffected']['objects']['assets'])
        self.assertEqual('undecided', cap['selection_status'])

    def test_d22_costume_changes_thirteen_visible_shots_not_offscreen_context(self):
        actor = find(self.after, 'entities', 'entity_id', 'C01')
        actor['variants'][0]['description'] = '深蓝直身外套、米白圆领内搭；全片保持'
        report = analyze_impact(self.before, self.after)
        expected = {'SH%02d' % i for i in range(1, 16)} - {'SH06', 'SH07'}
        self.assertEqual(expected, set(report['scope_candidates']['visual_shot_ids']))
        changed_assets = {aid for entry in report['deterministic_impacts']
                          for aid in entry['object_refs'] if aid.startswith(('A', 'T-'))}
        self.assertEqual({'A01'} | {'T-' + sid + '-V01' for sid in expected}, changed_assets)
        self.assertIn('T-SH07-V01', report['unaffected']['objects']['assets'])
        self.assertIn('SH07', report['unaffected']['objects']['shots'])
        self.assertIn('A06', report['unaffected']['objects']['assets'])
        self.assertEqual([], report['scope_candidates']['dialogue_audio_asset_ids'])
        self.assertEqual(['SC01', 'SC02', 'SC03'], report['scope_candidates']['context_scene_ids'])
        self.assertFalse(any(row['rule_id'] == 'STORY_CONSEQUENCES_REQUIRE_REVIEW'
                             for row in report['semantic_review_impacts']))
        self.assertEqual(12, len(report['unaffected']['objects']['dialogues']))

    def test_unused_costume_variant_does_not_expand_visible_scope(self):
        for content in [self.before, self.after]:
            find(content, 'entities', 'entity_id', 'C01')['variants'].append(
                {'variant_id': 'C01-V99', 'description': '从未使用的红外套'})
        find(self.after, 'entities', 'entity_id', 'C01')['variants'][1]['description'] = '从未使用的绿外套'
        report = analyze_impact(self.before, self.after)
        self.assertEqual([], report['scope_candidates']['visual_shot_ids'])
        self.assertEqual(['SC01', 'SC02', 'SC03'], report['scope_candidates']['context_scene_ids'])

    def test_context_refresh_covers_payload_changes_without_claiming_story_change(self):
        from drama_domain import assemble_context
        find(self.after, 'entities', 'entity_id', 'C01')['variants'][0]['description'] = '深蓝外套'
        resources = {self.before['style_ref']['path']: '维持低饱和度与自然动作。'}
        changed_payloads = set()
        for scene in self.before['scenes']:
            sid = scene['scene_id']
            old = assemble_context(self.before, sid, 100000, resources=resources)
            new = assemble_context(self.after, sid, 100000, resources=resources)
            self.assertEqual('PASS', old['status'], old['findings'])
            self.assertEqual('PASS', new['status'], new['findings'])
            if old['payload'] != new['payload']:
                changed_payloads.add(sid)
        report = analyze_impact(self.before, self.after)
        self.assertEqual(changed_payloads, set(report['scope_candidates']['context_scene_ids']))
        self.assertFalse(any(row['rule_id'] == 'STORY_CONSEQUENCES_REQUIRE_REVIEW'
                             for row in report['semantic_review_impacts']))
        self.assertNotIn('SH07', report['scope_candidates']['visual_shot_ids'])

    def test_indirect_basis_entity_refreshes_context_without_visual_consumption(self):
        for document in [self.before, self.after]:
            document['entities'].append({'entity_id': 'C03', 'kind': 'character',
                                         'name': '未出场背景人物', 'invariants': [],
                                         'variants': [{'variant_id': 'C03-V01', 'description': '灰色外套'}]})
            find(document, 'propositions', 'proposition_id', 'Q01')['basis']['reference'] = 'C03'
        find(self.after, 'entities', 'entity_id', 'C03')['variants'][0]['description'] = '蓝色外套'
        report = analyze_impact(self.before, self.after)
        self.assertEqual(['SC01', 'SC02', 'SC03'], report['scope_candidates']['context_scene_ids'])
        self.assertEqual([], report['scope_candidates']['visual_shot_ids'])

    def test_dialogue_change_marks_text_audio_and_timing_without_forcing_picture(self):
        find(self.after, 'dialogues', 'dialogue_id', 'D08')['text'] = '我以为，以后得敲门了。'
        report = analyze_impact(self.before, self.after)
        scope = report['scope_candidates']
        self.assertEqual(['AUD-D08'], scope['dialogue_audio_asset_ids'])
        self.assertEqual(['CAP-D08'], scope['caption_asset_ids'])
        self.assertEqual(['SH09'], scope['timing_review_shot_ids'])
        self.assertEqual([], scope['visual_shot_ids'])
        self.assertEqual(['SC02', 'SC03'], scope['context_scene_ids'])
        self.assertIn('A06', report['unaffected']['objects']['assets'])
        self.assertIn('AUD-D09', report['unaffected']['objects']['assets'])
        self.assertEqual(11, len(report['unaffected']['objects']['dialogues']))
        self.assertEqual([], report['media_actions'])
        self.assertIsNone(scope['work_scope'])

    def test_dialogue_audio_revision_does_not_list_timing_shot_as_unaffected(self):
        find(self.after, 'assets', 'asset_id', 'AUD-D08')['version'] = 'plan-v2'
        report = analyze_impact(self.before, self.after)
        self.assertEqual(['SH09'], report['scope_candidates']['timing_review_shot_ids'])
        self.assertNotIn('SH09', report['unaffected']['objects']['shots'])
        self.assertIn('SH08', report['unaffected']['objects']['shots'])
        self.assertEqual([], report['scope_candidates']['visual_shot_ids'])

    def test_early_reveal_state_change_rechecks_explicit_downstream_chain(self):
        state = find(self.after, 'snapshots', 'snapshot_id', 'ST01')
        knowledge = next(row for row in state['knowledge']
                         if row['holder_id'] == 'C01' and row['proposition_id'] == 'Q02')
        knowledge['attitude'] = 'believes_true'
        report = analyze_impact(self.before, self.after)
        self.assertEqual(['SC01', 'SC02', 'SC03'], report['scope_candidates']['context_scene_ids'])
        self.assertEqual([], report['scope_candidates']['visual_shot_ids'])
        self.assertTrue(any(row['rule_id'] == 'STORY_CONSEQUENCES_REQUIRE_REVIEW'
                            for row in report['semantic_review_impacts']))

    def test_proposition_change_does_not_automatically_rewrite_beliefs(self):
        find(self.after, 'propositions', 'proposition_id', 'Q02')['truth'] = False
        before_call = copy.deepcopy(self.after)
        report = analyze_impact(self.before, self.after)
        self.assertEqual(before_call, self.after)
        self.assertEqual(['SC01', 'SC02', 'SC03'], report['scope_candidates']['context_scene_ids'])
        self.assertEqual([], report['media_actions'])

    def test_display_name_change_keeps_stable_ids_separate(self):
        find(self.after, 'entities', 'entity_id', 'C02')['name'] = '林青'
        report = analyze_impact(self.before, self.after)
        self.assertIn('C01', report['unaffected']['objects']['entities'])
        self.assertNotIn('C02', report['unaffected']['objects']['entities'])
        self.assertEqual([], report['scope_candidates']['visual_shot_ids'])

    def test_unknown_top_field_requires_review_not_silent_preservation(self):
        self.after['future_state_machine'] = {'rewind': True}
        report = analyze_impact(self.before, self.after)
        self.assertEqual('UNCERTAIN', report['status'])
        self.assertFalse(report['unaffected']['conclusive'])
        self.assertEqual('UNCLASSIFIED_CHANGE', report['semantic_review_impacts'][0]['rule_id'])

    def test_unknown_object_and_variant_fields_require_review(self):
        find(self.after, 'scenes', 'scene_id', 'SC02')['new_rule'] = 'new semantics'
        find(self.after, 'entities', 'entity_id', 'C01')['variants'][0]['new_dimension'] = True
        report = analyze_impact(self.before, self.after)
        self.assertEqual('UNCERTAIN', report['status'])
        fields = {r['field'] for r in report['semantic_review_impacts']
                  if r['rule_id'] == 'UNCLASSIFIED_CHANGE'}
        self.assertIn('scenes.new_rule', fields)
        self.assertIn('entities.variants.new_dimension', fields)

    def test_presentation_reorder_is_not_ignored_by_id_map(self):
        self.after['shots'][0], self.after['shots'][1] = self.after['shots'][1], self.after['shots'][0]
        report = analyze_impact(self.before, self.after)
        self.assertTrue(any(r['rule_id'] == 'PRESENTATION_ORDER_REVIEW'
                            for r in report['semantic_review_impacts']))
        self.assertEqual(15, len(report['scope_candidates']['timing_review_shot_ids']))

    def test_flashback_changes_presentation_and_preserves_present_snapshots(self):
        variant = json.loads((EXAMPLE / 'variant-FB01.json').read_text())
        original = copy.deepcopy(variant)
        report = analyze_impact(self.before, variant)
        self.assertEqual('PASS', report['status'])
        self.assertEqual({'SH08', 'SH08-A', 'SH08-B', 'SH08-FB01'},
                         set(report['scope_candidates']['visual_shot_ids']))
        self.assertEqual([], report['scope_candidates']['dialogue_audio_asset_ids'])
        self.assertEqual(['CAP-D07'], report['scope_candidates']['caption_asset_ids'])
        self.assertEqual(4, len(report['unaffected']['objects']['snapshots']))
        self.assertIn('E05', report['unaffected']['objects']['events'])
        self.assertIn('AUD-D07', report['unaffected']['objects']['assets'])
        self.assertEqual(original, variant)
        self.assertEqual([], report['media_actions'])

    def test_flashback_speaker_change_does_not_preserve_audio_on_text_flag_alone(self):
        variant = json.loads((EXAMPLE / 'variant-FB01.json').read_text())
        variant['dialogue_rebindings'][0]['speaker_id'] = 'C01'
        report = analyze_impact(self.before, variant)
        self.assertEqual(['AUD-D07'], report['scope_candidates']['dialogue_audio_asset_ids'])

    def test_old_variant_base_rejected(self):
        variant = json.loads((EXAMPLE / 'variant-FB01.json').read_text())
        variant['base_content_revision'] = 'older-revision'
        report = analyze_impact(self.before, variant)
        self.assertEqual('FAIL', report['status'])
        self.assertEqual('VARIANT_BASE_CONFLICT', report['semantic_review_impacts'][0]['rule_id'])

    def test_invalid_inputs_do_not_crash_or_claim_success(self):
        for before, after in [(None, {}), ({}, {}), (self.before, {'schema': 'other'})]:
            self.assertEqual('FAIL', analyze_impact(before, after)['status'])
        self.after['shots'].append(copy.deepcopy(self.after['shots'][0]))
        self.assertEqual('FAIL', analyze_impact(self.before, self.after)['status'])

    def test_hashes_deterministic_and_inputs_unchanged(self):
        find(self.after, 'dialogues', 'dialogue_id', 'D08')['text'] = '我以为，以后得敲门了。'
        before_call, after_call = copy.deepcopy(self.before), copy.deepcopy(self.after)
        report = analyze_impact(self.before, self.after)
        self.assertEqual(report, analyze_impact(self.before, self.after))
        self.assertNotEqual(report['base']['canonical_json_sha256'], report['candidate']['canonical_json_sha256'])
        self.assertEqual(before_call, self.before)
        self.assertEqual(after_call, self.after)


if __name__ == '__main__':
    unittest.main()

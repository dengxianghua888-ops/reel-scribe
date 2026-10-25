"""COMP07/08: drama sidecars do not become film render authority or cache input.

Uses the unchanged film package's pure planner and revision validator. Synthetic
source identities exercise contracts, not real media, I1 execution or film QC.
"""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILM = ROOT / 'workflows/raven-film-recap/douyin-film-recap'
sys.path.insert(0, str(FILM / 'src'))

from douyin_film_recap.config import AppConfig  # noqa: E402
from douyin_film_recap.models import SourceInfo, Storyboard, StoryboardSegment, VisualReference  # noqa: E402
from douyin_film_recap.render_plan import compile_render_plan  # noqa: E402
from douyin_film_recap.revision import _validate_board  # noqa: E402
from douyin_film_recap.workspace import WorkspaceError  # noqa: E402


class FilmAttachmentCompatibility(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig(models={'llm_model': 'unused', 'vlm_model': 'unused'})
        self.identities = {'source-1': {'sha256': 'a' * 64, 'size': 100}}
        self.toolchain = {'verified': True, 'ffmpeg_sha256': 'f' * 64,
                          'ffprobe_sha256': 'e' * 64, 'version': 'synthetic-fixture',
                          'implementation_digest': 'd' * 64}
        self.board = Storyboard(
            project_name='film-compatibility-fixture', plan_fingerprint='fixture',
            target_duration_sec=1,
            sources=[SourceInfo(source_id='source-1', path='/not-read/source-1.mp4',
                                fingerprint='a' * 64, size_bytes=100, filename='source-1.mp4',
                                duration=1, width=320, height=240, fps=24)],
            segments=[StoryboardSegment(
                segment_id='segment-1', beat_id='beat-1', mode='original', title='fixture',
                text='', visuals=[VisualReference(source_id='source-1', start=0, end=1)],
                audio_owner='action_sound', planned_duration_sec=1, notes='')])

    def plan(self, board):
        return compile_render_plan(board, self.config, source_identities=self.identities,
                                   toolchain=self.toolchain)

    def test_comp07_sidecar_changes_preserve_storyboard_bytes_and_media_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            storyboard = root / '09_storyboard.json'
            original = self.board.model_dump_json(indent=2).encode()
            storyboard.write_bytes(original)
            sidecar = root / 'domain/drama/candidate.json'
            sidecar.parent.mkdir(parents=True)
            content = json.loads((ROOT / 'workflows/raven-drama-production/examples/return-key/drama-content.json').read_text())
            sidecar.write_text(json.dumps(content, ensure_ascii=False))
            first = self.plan(Storyboard.model_validate_json(storyboard.read_bytes()))
            first_domain_hash = hashlib.sha256(sidecar.read_bytes()).hexdigest()
            content['dialogues'][0]['text'] = '只改变旁路剧情候选。'
            content['content_revision'] = 'changed-sidecar-only'
            sidecar.write_text(json.dumps(content, ensure_ascii=False))
            self.assertNotEqual(first_domain_hash, hashlib.sha256(sidecar.read_bytes()).hexdigest())
            self.assertEqual(storyboard.read_bytes(), original)
            second = self.plan(Storyboard.model_validate_json(storyboard.read_bytes()))
            # The entire pure plan, including semantic keys and review binding,
            # still derives from the unchanged authoritative film storyboard.
            self.assertEqual(first, second)
            segment = next(n for n in first['nodes'] if n['kind'] == 'segment_av')
            self.assertEqual(segment['key_state'], 'complete')
            self.assertIsNotNone(segment['semantic_key'])

    def test_comp08_unknown_segment_drama_field_cannot_get_complete_media_key(self):
        raw = self.board.model_dump(mode='json')
        raw['segments'][0]['drama_domain_ref'] = {'package_id': 'unmapped-drama'}
        # The model permits opaque legacy extras; the render key must fail closed.
        model = Storyboard.model_validate(raw)
        plan = self.plan(model)
        segment = next(n for n in plan['nodes'] if n['kind'] == 'segment_av')
        self.assertIsNone(segment['semantic_key'])
        self.assertEqual(segment['key_state'], 'provisional')
        self.assertIn('UNCLASSIFIED_PARAMETER', segment['reason_codes'])

    def test_comp08_local_revision_rejects_injected_drama_fields(self):
        old = self.board.model_dump(mode='json')
        candidate = copy.deepcopy(old)
        candidate['segments'][0]['drama_domain_ref'] = {'package_id': 'unmapped-drama'}
        with self.assertRaisesRegex(WorkspaceError, 'REVISION_FIELD_UNSUPPORTED'):
            _validate_board(old, candidate, {'segment_ids': ['segment-1'],
                                           'fields': ['drama_domain_ref']}, local=True)
        candidate = copy.deepcopy(old)
        candidate['drama_domain_ref'] = {'package_id': 'unmapped-drama'}
        with self.assertRaisesRegex(WorkspaceError, 'REVISION_TOP_LEVEL_EDIT_UNSUPPORTED'):
            _validate_board(old, candidate, {'segment_ids': ['segment-1'],
                                           'fields': ['notes']}, local=True)


if __name__ == '__main__':
    unittest.main()

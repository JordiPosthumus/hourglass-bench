import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import option_layout
import question_preview


class RunQuestionPreview(unittest.TestCase):
    def test_images_use_declared_frozen_assets_and_reject_private_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); task, manifest, path = self.fixture(root)
            task['assets'] = ['chart.png', 'verify/key.txt', 'outside.png']
            path.write_text(json.dumps(task))
            image = path.parent/'chart.png'; image.write_bytes(b'fixture')
            secret = root/'secret.png'; secret.write_bytes(b'PRIVATE')
            (path.parent/'outside.png').symlink_to(secret)
            self.assertEqual(question_preview.image_file(root, 'example', 'chart.png', manifest), image.resolve())
            self.assertEqual(question_preview.images(task, 'fixture')[0], '/api/task-asset?id=example&file=chart.png&job=fixture')
            for name in ('task.json', 'verify/key.txt', '../secret.png', 'outside.png'):
                with self.assertRaises(ValueError): question_preview.image_file(root, 'example', name, manifest)
            with self.assertRaises(ValueError): question_preview.image_file(root, '../evaluations', 'chart.png')

    def fixture(self, root):
        task = {'id': 'example', 'kind': 'mcq', 'mode': 'option_id', 'prompt': 'Question.',
                'options': [{'id': f'{i:03d}', 'text': str(i)} for i in range(1, 21)],
                'answer': '017', 'shuffle': True, 'files': {'public.txt': 'PUBLIC', 'private.txt': 'PRIVATE'},
                'public_preview_files': ['public.txt'], 'verifier': {'secret': 'PRIVATE'}}
        path = root/'evaluations/fixture.tasks/example/task.json'; path.parent.mkdir(parents=True)
        path.write_text(json.dumps(task))
        manifest = {'id': 'fixture', 'task_snapshot': 'evaluations/fixture.tasks',
                    'option_layout_policy': option_layout.POLICY, 'presentation_seed': 'PRIVATE-SEED',
                    'expected': [{'task': 'example', 'task_sha': hashlib.sha256(path.read_bytes()).hexdigest()[:16],
                                  'task_bundle_sha': 'bundle', 'repeat': 3}]}
        return task, manifest, path

    def test_view_matches_executor_layout_and_preserves_answer_mapping(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); task, manifest, path = self.fixture(root); before = path.read_bytes()
            for repeat in (1, 2, 3):
                rendered = question_preview.for_run(root, manifest, 'example', repeat)
                actual, mapping = option_layout.prepare(task, repeat, 'bundle', 'PRIVATE-SEED')
                self.assertEqual(rendered['options'], actual['options'])
                self.assertEqual([o['id'] for o in rendered['options']], [f'{i:03d}' for i in range(1, 21)])
                self.assertEqual(mapping['display_to_original'][actual['answer']], task['answer'])
                self.assertNotIn('answer', rendered); self.assertNotIn('verifier', rendered)
                self.assertNotIn('PRIVATE', json.dumps(rendered))
                self.assertEqual(rendered['public_files'], {'public.txt': 'PUBLIC'})
            self.assertEqual(path.read_bytes(), before)

    def test_frozen_run_is_used_instead_of_current_bank(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); task, manifest, _ = self.fixture(root)
            bank = root/'tasks/example/task.json'; bank.parent.mkdir(parents=True)
            bank.write_text(json.dumps({**task, 'prompt': 'CHANGED BANK'}))
            self.assertEqual(question_preview.for_run(root, manifest, 'example', 1)['prompt'], 'Question.')

    def test_changed_frozen_question_and_out_of_scope_repeats_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); task, manifest, path = self.fixture(root)
            for tid, repeat in [('missing', 1), ('example', 0), ('example', 4)]:
                with self.assertRaises(ValueError): question_preview.for_run(root, manifest, tid, repeat)
            path.write_text(json.dumps({**task, 'prompt': 'changed'}))
            with self.assertRaises(ValueError): question_preview.for_run(root, manifest, 'example', 1)

    def test_active_repeat_comes_from_worker_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); _, manifest, _ = self.fixture(root)
            with self.assertRaises(ValueError): question_preview.active_repeat(root, manifest, 'example')
            (root/'logs').mkdir(); (root/'logs/attempt-fixture.json').write_text(json.dumps({'task': 'example', 'run': 2}))
            self.assertEqual(question_preview.active_repeat(root, manifest, 'example'), 2)

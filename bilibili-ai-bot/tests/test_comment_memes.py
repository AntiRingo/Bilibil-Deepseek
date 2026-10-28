import ast
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from PIL import Image

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import comment_memes as memes


class MemeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        stream = io.BytesIO()
        Image.new('RGB', (20, 10)).save(stream, format='PNG')
        self.raw = stream.getvalue()

    def test_upload_validate_list_and_routes(self):
        from flask import Flask
        app = Flask(__name__)
        memes.register_meme_routes(app)
        with patch.object(memes, 'library_dir', return_value=self.folder), patch.object(memes, 'describe_image', return_value='画面：抱抱；情绪：温柔；用途：安慰'):
            client = app.test_client()
            data = dict(image=(io.BytesIO(self.raw), '../../bad.svg'), name='抱抱', description='安慰')
            response = client.post('/api/comment_memes', data=data)
            self.assertEqual(response.status_code, 200)
            key = response.json['item']['id']
            self.assertEqual(response.json['item']['analysis_status'], 'ready')
            self.assertIn('温柔', response.json['item']['auto_description'])
            self.assertEqual(response.json['item']['description'], '安慰')
            self.assertEqual(len(client.get('/api/comment_memes').json['items']), 1)
            edited = client.patch('/api/comment_memes/' + key, json={'description':'只用于鼓励', 'name':'鼓励'})
            self.assertEqual(edited.json['item']['description'], '只用于鼓励')
            result = client.post('/api/comment_memes/' + key + '/analyze')
            self.assertEqual(result.json['item']['description'], '只用于鼓励')
            self.assertEqual(client.patch('/api/comment_memes/' + key, json={'description':None}).status_code, 400)
            self.assertEqual(client.patch('/api/comment_memes/' + 'f'*32, json={}).status_code, 404)
            cleared = client.patch('/api/comment_memes/' + key, json={'description':''}).json['item']
            self.assertEqual(memes.selection_items([cleared])[0]['description'], cleared['auto_description'])
            with client.get('/api/comment_memes/' + key) as preview:
                self.assertEqual(preview.mimetype, 'image/png')
            self.assertEqual(client.get('/api/comment_memes/bad').status_code, 404)
            self.assertEqual(client.post('/api/comment_memes', data={'image': (io.BytesIO(b'bad'), 'x.png'), 'name':'x', 'description':'y'}).status_code, 400)
            self.assertTrue(client.delete('/api/comment_memes/' + key).json['ok'])
            self.assertEqual(memes.list_memes(self.folder), [])
        with self.assertRaises(ValueError):
            memes.add_meme(self.folder, b'x' * (memes.MAX_BYTES + 1), 'x', 'y')
        self.assertEqual(memes.add_meme(self.folder, self.raw, 'x', '')['description'], '')

    def test_selection_only_accepts_library_ids(self):
        item = memes.add_meme(self.folder, self.raw, '抱抱', '温柔安慰')
        client = Mock()
        for output, expected in [('NONE', None), ('invented', None), (item['id'], item)]:
            client.chat.completions.create.return_value.choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=output))]
            self.assertEqual(memes.choose_meme([item], '难过', '抱抱', client, 'test'), expected)

    def test_upload_and_safe_fallback(self):
        config = types.ModuleType('config')
        config.get_raw_config = Mock(return_value={'ENABLE_COMMENT_MEMES': True})
        config.get_model_config = Mock(return_value=('https://example.invalid/v1', 'fake', 'test', ''))
        with patch.dict(sys.modules, config=config), patch.object(memes, 'library_dir', return_value=self.folder), patch('openai.OpenAI'), patch.object(memes, 'choose_meme') as choose, patch.object(memes.requests, 'post') as post:
            self.assertIsNone(memes.prepare_comment_pictures('', 'hello', {}, 'fake'))
            choose.assert_not_called()
            item = memes.add_meme(self.folder, self.raw, '开心', '大笑')
            choose.return_value = item
            post.return_value.json.return_value = {'code': 0, 'data': {'image_url': 'https://i0.hdslb.com/example.png', 'image_width':20, 'image_height':10, 'img_size':1}}
            pictures = memes.prepare_comment_pictures('哈哈', '开心', {}, 'fake')
            self.assertEqual(pictures[0]['img_width'], 20)
            post.side_effect = TimeoutError()
            self.assertIsNone(memes.prepare_comment_pictures('', '开心', {}, 'fake'))
            choose.side_effect = ValueError()
            self.assertIsNone(memes.prepare_comment_pictures('', '开心', {}, 'fake'))
            config.get_raw_config.return_value = {'ENABLE_COMMENT_MEMES': False}
            choose.reset_mock()
            self.assertIsNone(memes.prepare_comment_pictures('', 'hello', {}, 'fake'))
            choose.assert_not_called()

    def test_senders_keep_thread_and_do_not_retry(self):
        for filename, name in [('ai.py', 'send_reply'), ('Proactive.py', 'send_comment')]:
            tree = ast.parse((APP / filename).read_text(encoding='utf-8'))
            function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
            http = Mock()
            http.post.return_value.json.return_value = {'code': 0}
            ns = dict(requests=http, headers={}, BILI_JCT='fake', json=json)
            exec(compile(ast.Module(body=[function], type_ignores=[]), filename, 'exec'), ns)
            pictures = [{'img_src':'example', 'img_width':20, 'img_height':10, 'img_size':1}]
            with patch.object(memes, 'prepare_comment_pictures', return_value=pictures):
                if name == 'send_reply':
                    self.assertTrue(ns[name](200, 102, 1, 'hello', root_id=80, source_comment='hi'))
                    data = http.post.call_args.kwargs['data']
                    self.assertEqual((data['root'], data['parent']), (80, 102))
                else:
                    self.assertTrue(ns[name](200, 'hello'))
                self.assertEqual(json.loads(http.post.call_args.kwargs['data']['pictures']), pictures)
                http.post.assert_called_once()

    def test_failed_recognition_preserves_image_and_manual_usage(self):
        item = memes.add_meme(self.folder, self.raw, 'x', '')
        with patch.object(memes, 'describe_image', side_effect=TimeoutError()):
            item = memes.analyze_meme(self.folder, item)
        self.assertEqual(item['analysis_status'], 'failed')
        self.assertTrue((self.folder / (item['id'] + '.png')).exists())
        self.assertEqual(memes.selection_items([item]), [])
        item['description'] = '只用于鼓励'
        item['auto_description'] = '开怀大笑'
        memes.save_meme(self.folder, item)
        with patch.object(memes, 'describe_image', side_effect=TimeoutError()):
            item = memes.analyze_meme(self.folder, item)
        self.assertEqual(item['auto_description'], '开怀大笑')
        self.assertEqual(memes.selection_items([item])[0]['description'], '只用于鼓励')
        legacy = {'id':'old', 'name':'old', 'description':'原有用途'}
        self.assertEqual(memes.selection_items([legacy])[0]['description'], '原有用途')

    def test_vision_receives_real_image_and_uses_fallback(self):
        item = memes.add_meme(self.folder, self.raw, 'x', '')
        config = types.ModuleType('config')
        config.get_model_config = Mock(return_value=('https://example.invalid/v1', 'fake', 'vision-primary', 'vision-fallback'))
        response = types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='温柔抱抱，用于安慰'))])
        with patch.dict(sys.modules, config=config), patch('openai.OpenAI') as factory:
            client = factory.return_value.__enter__.return_value
            client.chat.completions.create.side_effect = [TimeoutError(), response]
            result = memes.describe_image(self.folder / (item['id'] + '.png'))
            self.assertEqual(result, '温柔抱抱，用于安慰')
            call = client.chat.completions.create.call_args.kwargs
            self.assertEqual(call['model'], 'vision-fallback')
            self.assertTrue(call['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,'))
            config.get_model_config.assert_called_once_with('vision')

"""Exercise advertised tools, side effects and recovery through real MCP stdio."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


SERVER = Path(__file__).resolve().parents[2] / 'scripts' / 'mcp_server.py'
ROOT = SERVER.parents[1]
INVALID_OBJECTS = (None, [], [1], '', 'invalid', False, True, 0, 1)


class McpRequestTests(unittest.TestCase):
    def exchange(self, messages, *, env=None, cwd=None):
        result = subprocess.run(
            [sys.executable, str(SERVER)],
            input=''.join(json.dumps(message) + '\n' for message in messages),
            text=True, capture_output=True, timeout=20, env=env, cwd=cwd,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        return sorted((json.loads(line) for line in result.stdout.splitlines()), key=lambda item: item['id'])

    @staticmethod
    def call(identifier, name, arguments):
        return {'jsonrpc': '2.0', 'id': identifier, 'method': 'tools/call',
                'params': {'name': name, 'arguments': arguments}}

    def tool_output(self, response):
        self.assertFalse(response['result']['isError'], response)
        self.assertEqual(response['result']['content'][0]['type'], 'text')
        return json.loads(response['result']['content'][0]['text'])

    @staticmethod
    def child_environment(work_root):
        # Never probe an inherited executable, use a host work root, or expose
        # the DeepSeek credential. These calls require no media/model provider.
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('EDITING_', 'PYTHON')) and key != 'DEEPSEEK_API_KEY'}
        env.update(PATH='', PYTHONDONTWRITEBYTECODE='1',
                   EDITING_SKILL_WORK_ROOT=str(work_root),
                   EDITING_FFMPEG=str(work_root / 'missing-ffmpeg'),
                   EDITING_FFPROBE=str(work_root / 'missing-ffprobe'))
        return env

    @staticmethod
    def snapshot(directory):
        return {str(path.relative_to(directory)): path.read_bytes() if path.is_file() else None
                for path in directory.rglob('*')}

    @staticmethod
    def budget_request(store):
        # Local SQLite bookkeeping only: no provider adapter or paid request.
        return {'operation': 'generation-task', 'action': 'budget-create',
                'store': str(store), 'budget_key': 'mcp-test',
                'currency': 'USD', 'limit_micros': 1000000}

    def test_tools_list_declares_complete_behavior_annotations(self):
        responses = self.exchange([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}])
        tools = responses[0]['result']['tools']
        self.assertEqual(len(tools), 3)
        self.assertEqual({tool['name'] for tool in tools},
                         {'diagnose_installation', 'list_skills', 'run_operation'})
        for tool in tools:
            with self.subTest(tool=tool['name']):
                hints = tool['annotations']
                self.assertEqual(set(hints), {'readOnlyHint', 'destructiveHint',
                                              'idempotentHint', 'openWorldHint'})
                self.assertTrue(all(type(value) is bool for value in hints.values()))
                if tool['name'] == 'run_operation':
                    self.assertFalse(hints['readOnlyHint'])
                    self.assertTrue(hints['destructiveHint'])
                    self.assertFalse(hints['idempotentHint'])
                    self.assertTrue(hints['openWorldHint'])
                else:
                    self.assertTrue(hints['readOnlyHint'])
                    self.assertFalse(hints['destructiveHint'])
                    self.assertTrue(hints['idempotentHint'])
                    self.assertFalse(hints['openWorldHint'])

    def test_list_skills_returns_registry_without_writing(self):
        registry_path = ROOT / 'registry' / 'skills.json'
        registry_bytes = registry_path.read_bytes()
        registry = json.loads(registry_bytes)
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            (directory / 'user-source.txt').write_text('preserve this source')
            before = self.snapshot(directory)
            responses = self.exchange([
                self.call(1, 'list_skills', {}), self.call(2, 'list_skills', {}),
            ], env=self.child_environment(directory), cwd=directory)
            expected = [{key: row.get(key) for key in ('id', 'layer', 'entry', 'status')}
                        for row in registry['entries']]
            for response in responses:
                output = self.tool_output(response)
                self.assertEqual(output['schema'], registry['schema'])
                self.assertEqual(output['entries'], expected)
            self.assertEqual(self.snapshot(directory), before)
            self.assertEqual(registry_path.read_bytes(), registry_bytes)
            self.assertEqual(responses[0]['result'], responses[1]['result'])

    def test_diagnose_installation_reports_missing_tools_without_writing(self):
        registry_bytes = (ROOT / 'registry' / 'skills.json').read_bytes()
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            (directory / 'user-source.txt').write_text('preserve this source')
            before = self.snapshot(directory)
            arguments = {'ffmpeg': str(directory / 'missing-ffmpeg'),
                         'ffprobe': str(directory / 'missing-ffprobe'),
                         'request': {'operation': 'media-inspect'}}
            responses = self.exchange([
                self.call(1, 'diagnose_installation', arguments),
                self.call(2, 'diagnose_installation', arguments),
            ], env=self.child_environment(directory), cwd=directory)
            for response in responses:
                output = self.tool_output(response)
                self.assertEqual(output['status'], 'DIAGNOSTIC_ONLY_NOT_INSTALLATION_ACCEPTANCE')
                self.assertEqual(Path(output['root']), ROOT)
                self.assertEqual(output['components']['ffmpeg']['status'], 'UNRESOLVED')
                self.assertEqual(output['components']['ffprobe']['status'], 'UNRESOLVED')
                self.assertEqual(output['selected_request']['operation'], 'media-inspect')
                self.assertGreater(output['registry']['atomic_count'], 0)
            self.assertEqual(self.snapshot(directory), before)
            self.assertEqual((ROOT / 'registry' / 'skills.json').read_bytes(), registry_bytes)

    def test_run_operation_writes_receipt_and_rejects_reuse_without_mutating_output(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            work = directory / 'operation'
            store = work / 'generation.sqlite3'
            arguments = {'request': self.budget_request(store), 'work_dir': str(work)}
            response = self.exchange([self.call(1, 'run_operation', arguments)],
                                     env=self.child_environment(directory), cwd=directory)[0]
            output = self.tool_output(response)
            receipt_path = work / 'receipt.json'
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(output['status'], 'SUCCEEDED')
            self.assertEqual(output['receipt_path'], str(receipt_path))
            self.assertEqual(output['receipt'], receipt)
            self.assertEqual(receipt['operation'], 'generation-task')
            self.assertEqual(receipt['result']['limit_micros'], 1000000)
            self.assertEqual(json.loads((work / 'request.json').read_text()), arguments['request'])
            with sqlite3.connect(store) as db:
                self.assertEqual(db.execute('SELECT budget_key, limit_micros, spent_micros FROM budgets').fetchall(),
                                 [('mcp-test', 1000000, 0)])
            before = self.snapshot(directory)
            responses = self.exchange([
                self.call(2, 'run_operation', arguments),
                {'jsonrpc': '2.0', 'id': 3, 'method': 'ping'},
            ], env=self.child_environment(directory), cwd=directory)
            self.assertTrue(responses[0]['result']['isError'])
            self.assertEqual(responses[0]['result']['content'][0]['text'],
                             'NEW_WORK_DIR_UNDER_CONFIGURED_ROOT_REQUIRED')
            self.assertEqual(responses[1]['result'], {})
            self.assertEqual(self.snapshot(directory), before)

    def test_run_operation_rejects_work_directory_boundaries_before_writing(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            work_root = directory / 'work'
            work_root.mkdir()
            existing = work_root / 'existing'
            existing.mkdir()
            (existing / 'user-source.txt').write_text('preserve this source')
            outside = directory / 'outside'
            outside.mkdir()
            (work_root / 'escape').symlink_to(outside, target_is_directory=True)
            cases = [str(work_root), str(existing), str(outside / 'new'),
                     str(work_root / 'escape' / 'new'), 'relative-work']
            messages = []
            for index, work_dir in enumerate(cases):
                messages.extend([
                    self.call(2 * index + 1, 'run_operation',
                              {'request': self.budget_request(directory / 'never.sqlite3'),
                               'work_dir': work_dir}),
                    {'jsonrpc': '2.0', 'id': 2 * index + 2, 'method': 'ping'},
                ])
            before = self.snapshot(directory)
            responses = self.exchange(messages, env=self.child_environment(work_root), cwd=directory)
            self.assertEqual(len(responses), len(messages))
            for index, response in enumerate(responses):
                self.assertEqual(response['id'], messages[index]['id'])
                if index % 2 == 0:
                    self.assertTrue(response['result']['isError'])
                else:
                    self.assertEqual(response['result'], {})
            self.assertEqual(self.snapshot(directory), before)

    def test_each_tool_rejects_unknown_arguments_and_connection_recovers(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            before = self.snapshot(directory)
            messages = []
            for index, name in enumerate(('diagnose_installation', 'list_skills', 'run_operation')):
                messages.extend([
                    self.call(2 * index + 1, name, {'unexpected': True}),
                    {'jsonrpc': '2.0', 'id': 2 * index + 2, 'method': 'ping'},
                ])
            responses = self.exchange(messages, env=self.child_environment(directory), cwd=directory)
            self.assertEqual(len(responses), len(messages))
            for index, response in enumerate(responses):
                self.assertEqual(response['id'], messages[index]['id'])
                if index % 2 == 0:
                    self.assertTrue(response['result']['isError'])
                    self.assertEqual(response['result']['content'][0]['text'], 'UNKNOWN_TOOL_ARGUMENTS')
                else:
                    self.assertEqual(response['result'], {})
            self.assertEqual(self.snapshot(directory), before)

    def test_failed_runtime_request_preserves_error_receipt_and_connection(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            work = directory / 'failed'
            responses = self.exchange([
                self.call(1, 'run_operation', {'request': {'operation': 'not-an-operation'},
                                             'work_dir': str(work)}),
                {'jsonrpc': '2.0', 'id': 2, 'method': 'ping'},
            ], env=self.child_environment(directory), cwd=directory)
            self.assertTrue(responses[0]['result']['isError'])
            output = json.loads(responses[0]['result']['content'][0]['text'])
            self.assertEqual(output['status'], 'FAILED')
            self.assertEqual(output['receipt'], json.loads((work / 'receipt.json').read_text()))
            self.assertEqual(output['receipt']['error'], 'UNSUPPORTED_OPERATION: not-an-operation')
            self.assertEqual(responses[1]['result'], {})

    def test_corrupt_sqlite_preserves_receipt_and_ping(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            store = directory / 'corrupt.sqlite3'
            store.write_bytes(b'not a database')
            work = directory / 'failed'
            responses = self.exchange([
                self.call(1, 'run_operation', {'request': self.budget_request(store),
                                             'work_dir': str(work)}),
                {'jsonrpc': '2.0', 'id': 2, 'method': 'ping'},
            ], env=self.child_environment(directory))
            self.assertTrue(responses[0]['result']['isError'])
            receipt = json.loads((work / 'receipt.json').read_text())
            self.assertEqual(receipt['status'], 'FAILED')
            self.assertIn('GENERATION_STORE_ERROR', receipt['error'])
            self.assertEqual(responses[1]['result'], {})

    def test_invalid_params_return_errors_and_connection_continues(self):
        messages = []
        for method in ('initialize', 'tools/call', 'ping', 'tools/list'):
            for params in INVALID_OBJECTS:
                identifier = len(messages) + 1
                messages.extend([
                    {'jsonrpc': '2.0', 'id': identifier, 'method': method, 'params': params},
                    {'jsonrpc': '2.0', 'id': identifier + 1, 'method': 'ping'},
                ])
        responses = self.exchange(messages)
        self.assertEqual(len(responses), len(messages))
        for index, response in enumerate(responses):
            self.assertEqual(response['id'], messages[index]['id'])
            if index % 2 == 0:
                self.assertEqual(response['error']['code'], -32602)
                self.assertEqual(response['error']['message'], 'PARAMS_OBJECT_REQUIRED')
            else:
                self.assertEqual(response['result'], {})

    def test_invalid_arguments_are_not_coerced_to_empty_objects(self):
        messages = []
        for arguments in INVALID_OBJECTS:
            identifier = len(messages) + 1
            messages.extend([
                {'jsonrpc': '2.0', 'id': identifier, 'method': 'tools/call',
                 'params': {'name': 'list_skills', 'arguments': arguments}},
                {'jsonrpc': '2.0', 'id': identifier + 1, 'method': 'ping'},
            ])
        responses = self.exchange(messages)
        self.assertEqual(len(responses), len(messages))
        for index, response in enumerate(responses):
            self.assertEqual(response['id'], messages[index]['id'])
            if index % 2 == 0:
                self.assertEqual(response['error']['code'], -32602)
                self.assertEqual(response['error']['message'], 'TOOL_ARGUMENTS_OBJECT_REQUIRED')
            else:
                self.assertEqual(response['result'], {})

    def test_omitted_and_object_arguments_and_initialize_remain_supported(self):
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'initialize',
             'params': {'protocolVersion': '2025-06-18'}},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
             'params': {'name': 'list_skills'}},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
             'params': {'name': 'list_skills', 'arguments': {}}},
        ]
        responses = self.exchange(messages)
        self.assertEqual(len(responses), 4)
        self.assertEqual(responses[0]['result']['protocolVersion'], '2025-03-26')
        self.assertEqual(responses[1]['result']['protocolVersion'], '2025-06-18')
        for response in responses[2:]:
            self.assertFalse(response['result']['isError'])
            content = json.loads(response['result']['content'][0]['text'])
            self.assertTrue(content['entries'])

    def raw_exchange(self, lines, *, diagnostic=None):
        result = subprocess.run(
            [sys.executable, str(SERVER)], input="\n".join(lines) + "\n",
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, diagnostic + "\n" if diagnostic else "")
        return [json.loads(line) for line in result.stdout.splitlines()]

    def test_uncorrelatable_parse_errors_use_diagnostics_and_preserve_ping(self):
        for malformed in ('{"private-marker"', '{"id": 1, "method": "ping",}', 'NaN'):
            with self.subTest(malformed=malformed):
                responses = self.raw_exchange([
                    malformed, json.dumps({'jsonrpc': '2.0', 'id': 91, 'method': 'ping'}),
                ], diagnostic='MCP_PARSE_ERROR: invalid JSON message')
                self.assertEqual(responses, [{'jsonrpc': '2.0', 'id': 91, 'result': {}}])

    def test_invalid_envelopes_reject_usable_ids_and_preserve_ping(self):
        cases = [
            (None, None), ([], None), ([{'jsonrpc': '2.0', 'id': 8, 'method': 'ping'}], None),
            ('private-marker', None), (1, None), (True, None), ({}, None),
            ({'id': 8, 'method': 'ping'}, 8),
            ({'jsonrpc': '1.0', 'id': 8, 'method': 'ping'}, 8),
            ({'jsonrpc': '2.0', 'id': 8}, 8),
            ({'jsonrpc': '2.0', 'id': 'string-id', 'method': []}, 'string-id'),
            ({'jsonrpc': '2.0', 'method': 1}, None),
            ({'jsonrpc': '2.0', 'id': True, 'method': 'ping'}, None),
            ({'jsonrpc': '2.0', 'id': [], 'method': 'ping'}, None),
            ({'jsonrpc': '2.0', 'id': {}, 'method': 'ping'}, None),
            ({'jsonrpc': '2.0', 'id': 1.5, 'method': 'ping'}, None),
            ({'jsonrpc': '2.0', 'id': None, 'method': 'ping'}, None),
        ]
        for message, expected_id in cases:
            with self.subTest(message=message):
                diagnostic = 'MCP_INVALID_REQUEST: no usable request id' if expected_id is None else None
                responses = self.raw_exchange([
                    json.dumps(message), json.dumps({'jsonrpc': '2.0', 'id': 91, 'method': 'ping'}),
                ], diagnostic=diagnostic)
                if expected_id is not None:
                    self.assertEqual(len(responses), 2)
                    self.assertEqual(responses[0]['id'], expected_id)
                    self.assertEqual(responses[0]['error']['code'], -32600)
                else:
                    self.assertEqual(len(responses), 1)
                self.assertEqual(responses[-1], {'jsonrpc': '2.0', 'id': 91, 'result': {}})

    def test_invalid_version_cannot_execute_writable_tool(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            message = self.call(1, 'run_operation', {
                'request': self.budget_request(directory / 'never-created.sqlite3'),
                'work_dir': str(directory / 'never-created'),
            })
            message['jsonrpc'] = '1.0'
            before = self.snapshot(directory)
            responses = self.exchange([
                message, {'jsonrpc': '2.0', 'id': 2, 'method': 'ping'},
            ], env=self.child_environment(directory))
            self.assertEqual(responses[0]['error']['code'], -32600)
            self.assertEqual(responses[1]['result'], {})
            self.assertEqual(self.snapshot(directory), before)

    def test_mcp_valid_string_ids_and_notifications_remain_supported(self):
        responses = self.raw_exchange([
            json.dumps({'jsonrpc': '2.0', 'id': 'string-id', 'method': 'ping'}),
            json.dumps({'jsonrpc': '2.0', 'method': 'ping'}),
            json.dumps({'jsonrpc': '2.0', 'id': 91, 'method': 'unknown-method'}),
        ])
        self.assertEqual(responses[0], {'jsonrpc': '2.0', 'id': 'string-id', 'result': {}})
        self.assertEqual(responses[1]['id'], 91)
        self.assertEqual(responses[1]['error']['code'], -32601)

    def test_malformed_notifications_are_silent_and_connection_continues(self):
        responses = self.exchange([
            {'jsonrpc': '2.0', 'method': 'initialize', 'params': None},
            {'jsonrpc': '2.0', 'method': 'tools/call', 'params': [1]},
            {'jsonrpc': '2.0', 'method': 'tools/call',
             'params': {'name': 'list_skills', 'arguments': False}},
            {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'},
        ])
        self.assertEqual(responses, [{'jsonrpc': '2.0', 'id': 1, 'result': {}}])


if __name__ == '__main__':
    unittest.main()

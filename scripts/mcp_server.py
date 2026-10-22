#!/usr/bin/env python3
"""Local stdio MCP bridge to the existing Editing Skill Library runtime.

The server speaks newline-delimited JSON-RPC over stdio. It does not perform
remote model calls, select an editing host, or infer that a listed skill works.
"""
import json
import os
from pathlib import Path
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

_OUTPUT_LOCK = threading.Lock()

VERSION = '0.1.0'
NAME = 'editing-skill-library'


def library_root():
    local = Path(__file__).resolve().parents[1]
    if (local / 'registry' / 'skills.json').is_file():
        return local
    configured = os.environ.get('EDITING_SKILL_LIBRARY_ROOT')
    if configured and Path(configured).is_absolute():
        root = Path(configured).resolve()
        if (root / 'registry' / 'skills.json').is_file():
            return root
    raise ValueError('LIBRARY_ROOT_UNAVAILABLE: integrate plugin at the library root or set EDITING_SKILL_LIBRARY_ROOT to an absolute library path')


def _tool_specs():
    return [
        {'name': 'diagnose_installation',
         'description': 'Read-only target-environment dependency inventory. Presence is not host or media acceptance.',
         'annotations': {'readOnlyHint': True, 'destructiveHint': False,
                         'idempotentHint': True, 'openWorldHint': False},
         'inputSchema': {'type': 'object', 'properties': {
             'ffmpeg': {'type': 'string', 'description': 'Absolute executable path; optional.'},
             'ffprobe': {'type': 'string', 'description': 'Absolute executable path; optional.'},
             'bindings': {'type': 'object', 'description': 'Optional font/asr lock path+sha256 references.'},
             'request': {'type': 'object', 'description': 'Optional exact local runtime request for branch-specific diagnosis.'}},
             'additionalProperties': False}},
        {'name': 'list_skills',
         'description': 'List the local registry entries and declared layer/status. Static enumeration only.',
         'annotations': {'readOnlyHint': True, 'destructiveHint': False,
                         'idempotentHint': True, 'openWorldHint': False},
         'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
        {'name': 'run_operation',
         'description': 'Run one existing atomic runtime request into a new directory under EDITING_SKILL_WORK_ROOT. May update existing stores or invoke external providers. No generic retry/resume guarantee; existing work directories are rejected. Requires explicit task authorization and separate authorization for paid provider calls.',
         # This dispatcher also reaches mutable Work/Task stores and external
         # model providers; a fresh receipt directory does not make it additive,
         # repeatable, or confined to local entities. Use conservative hints for
         # the complete dispatch surface, not just read-only atomic requests.
         'annotations': {'readOnlyHint': False, 'destructiveHint': True,
                         'idempotentHint': False, 'openWorldHint': True},
         'inputSchema': {'type': 'object', 'properties': {
             'request': {'type': 'object', 'description': 'Exact editing_runtime request object.'},
             'work_dir': {'type': 'string', 'description': 'New absolute work directory under configured work root.'},
             'ffmpeg': {'type': 'string', 'description': 'Optional absolute FFmpeg executable.'},
             'ffprobe': {'type': 'string', 'description': 'Optional absolute ffprobe executable.'}},
             'required': ['request', 'work_dir'], 'additionalProperties': False}},
    ]


def call_tool(name, arguments, *, cancel_event=None, progress=None):
    if not isinstance(arguments, dict):
        raise ValueError('TOOL_ARGUMENTS_OBJECT_REQUIRED')
    root = library_root()
    if name == 'list_skills':
        if arguments:
            raise ValueError('UNKNOWN_TOOL_ARGUMENTS')
        registry = json.loads((root / 'registry' / 'skills.json').read_text())
        return {'schema': registry.get('schema'), 'entries': [
            {k: row.get(k) for k in ('id', 'layer', 'entry', 'status')}
            for row in registry['entries']], 'limit': 'Static registry listing; no installation, route or capability execution claim.'}
    if name == 'diagnose_installation':
        if set(arguments) - {'ffmpeg', 'ffprobe', 'bindings', 'request'}:
            raise ValueError('UNKNOWN_TOOL_ARGUMENTS')
        local_runtime = Path(__file__).resolve().parents[1] / 'runtime'
        diagnostic_runtime = root / 'runtime' if (root / 'runtime' / 'dependency_discovery.py').is_file() else local_runtime
        sys.path.insert(0, str(diagnostic_runtime))
        try:
            from dependency_discovery import inspect
            return inspect(root, ffmpeg=arguments.get('ffmpeg'), ffprobe=arguments.get('ffprobe'),
                           bindings=arguments.get('bindings'), request=arguments.get('request'))
        finally:
            sys.path.pop(0)
    if name == 'run_operation':
        if set(arguments) - {'request', 'work_dir', 'ffmpeg', 'ffprobe'}:
            raise ValueError('UNKNOWN_TOOL_ARGUMENTS')
        request, raw = arguments.get('request'), arguments.get('work_dir')
        if not isinstance(request, dict) or not isinstance(raw, str) or not Path(raw).is_absolute():
            raise ValueError('REQUEST_OBJECT_AND_ABSOLUTE_WORK_DIR_REQUIRED')
        configured = os.environ.get('EDITING_SKILL_WORK_ROOT')
        if not configured or not Path(configured).is_absolute():
            raise ValueError('WORK_ROOT_REQUIRED: set EDITING_SKILL_WORK_ROOT to an absolute exclusive work parent')
        work_root = Path(configured).resolve()
        work_dir = Path(raw).resolve()
        if work_dir == work_root or work_root not in work_dir.parents or work_dir.exists():
            raise ValueError('NEW_WORK_DIR_UNDER_CONFIGURED_ROOT_REQUIRED')
        sys.path.insert(0, str(root / 'runtime'))
        try:
            import editing_runtime as runtime
            cancellation_token = runtime.RUN_CANCELLATION.set(cancel_event)
            progress_token = runtime.RUN_PROGRESS.set(progress)
            try:
                receipt = runtime.run(request, work_dir, runtime.Tools(arguments.get('ffmpeg'), arguments.get('ffprobe')))
            finally:
                runtime.RUN_CANCELLATION.reset(cancellation_token)
                runtime.RUN_PROGRESS.reset(progress_token)
        finally:
            sys.path.pop(0)
        return {'status': receipt['status'], 'receipt': receipt,
                'receipt_path': str(work_dir / 'receipt.json'),
                'limit': 'Runtime execution only; no human audiovisual or host acceptance.'}
    raise ValueError('UNKNOWN_TOOL: ' + str(name))


def _response(identifier, result=None, error=None):
    value = {'jsonrpc': '2.0', 'id': identifier}
    if error is None:
        value['result'] = result
    else:
        value['error'] = error
    _emit(value)


def _emit(value):
    with _OUTPUT_LOCK:
        sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')
        sys.stdout.flush()


def _reject_json_constant(value):
    # Python's JSON reader otherwise accepts NaN/Infinity, which are not JSON.
    raise ValueError('NON_JSON_CONSTANT')


def _valid_request_id(value):
    # Match MCP RequestId: bool, float and null are not request identifiers.
    return type(value) in (str, int)


def serve():
    # One execution lane preserves store/work ordering. Protocol input remains
    # live for ping and cancellation; output is atomic across both threads.
    pending = {}
    pending_lock = threading.Lock()

    def release_request(identifier, cancellation):
        with pending_lock:
            if pending.get(identifier) is cancellation:
                pending.pop(identifier)

    def execute_call(identifier, params, cancellation):
        progress_token = params.get('_meta', {}).get('progressToken') if isinstance(params.get('_meta', {}), dict) else None
        count = 0
        def progress(message):
            nonlocal count
            if type(progress_token) not in (str, int, float):
                return
            count += 1
            _emit({'jsonrpc': '2.0', 'method': 'notifications/progress', 'params': {
                'progressToken': progress_token, 'progress': count, 'message': message}})
        try:
            progress('Started; cancellation is cooperative')
            output = call_tool(params.get('name'), params.get('arguments', {}),
                               cancel_event=cancellation, progress=progress)
            progress('Finished')
            # Release before publishing the terminal reply: a client can reuse
            # an ID immediately after reading it. Cleanup must not erase that
            # newer request's cancellation token.
            release_request(identifier, cancellation)
            _response(identifier, {'content': [{'type': 'text', 'text': json.dumps(output, ensure_ascii=False)}],
                                   'isError': output.get('status') in ('FAILED', 'BUNDLE_DIAGNOSTIC_IDENTITY_FAILED')})
        except Exception as exc:  # Do not swallow KeyboardInterrupt/SystemExit.
            release_request(identifier, cancellation)
            _response(identifier, {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True})
        finally:
            release_request(identifier, cancellation)

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='mcp-operation') as executor:
        for line in sys.stdin:
            message = None
            if not line.strip():
                continue
            try:
                try:
                    message = json.loads(line, parse_constant=_reject_json_constant)
                except ValueError:
                    # No usable ID is available. Keep stdout valid for MCP
                    # clients and never echo a payload that may hold secrets.
                    print('MCP_PARSE_ERROR: invalid JSON message', file=sys.stderr, flush=True)
                    continue
                if not isinstance(message, dict):
                    print('MCP_INVALID_REQUEST: no usable request id', file=sys.stderr, flush=True)
                    continue
                identifier = message.get('id')
                method = message.get('method')
                if (message.get('jsonrpc') != '2.0' or not isinstance(method, str)
                        or ('id' in message and not _valid_request_id(identifier))):
                    if _valid_request_id(identifier):
                        _response(identifier, error={'code': -32600, 'message': 'INVALID_MCP_REQUEST'})
                    else:
                        print('MCP_INVALID_REQUEST: no usable request id', file=sys.stderr, flush=True)
                    continue
                params = message.get('params', {})
                if 'id' not in message:
                    if method == 'notifications/cancelled' and isinstance(params, dict):
                        request_id = params.get('requestId')
                        if _valid_request_id(request_id):
                            with pending_lock:
                                cancellation = pending.get(request_id)
                                if cancellation is not None:
                                    cancellation.set()
                    continue
                if not isinstance(params, dict):
                    _response(identifier, error={'code': -32602, 'message': 'PARAMS_OBJECT_REQUIRED'})
                    continue
                if method == 'initialize':
                    requested = params.get('protocolVersion')
                    protocol = requested if requested in ('2024-11-05', '2025-03-26', '2025-06-18') else '2025-03-26'
                    _response(identifier, {'protocolVersion': protocol,
                        'capabilities': {'tools': {'listChanged': False}},
                        'serverInfo': {'name': NAME, 'version': VERSION}})
                elif method == 'ping':
                    _response(identifier, {})
                elif method == 'tools/list':
                    _response(identifier, {'tools': _tool_specs()})
                elif method == 'tools/call':
                    if not isinstance(params.get('arguments', {}), dict):
                        _response(identifier, error={'code': -32602, 'message': 'TOOL_ARGUMENTS_OBJECT_REQUIRED'})
                        continue
                    with pending_lock:
                        if identifier in pending or len(pending) >= 16:
                            _response(identifier, error={'code': -32600, 'message': 'DUPLICATE_OR_TOO_MANY_PENDING_REQUESTS'})
                            continue
                        cancellation = threading.Event()
                        pending[identifier] = cancellation
                    executor.submit(execute_call, identifier, params, cancellation)
                else:
                    _response(identifier, error={'code': -32601, 'message': 'Method not found'})
            except (ValueError, TypeError, KeyError) as exc:
                if isinstance(message, dict) and _valid_request_id(message.get('id')):
                    _response(message['id'], error={'code': -32600, 'message': str(exc)})
    return 0


if __name__ == '__main__':
    sys.exit(serve())

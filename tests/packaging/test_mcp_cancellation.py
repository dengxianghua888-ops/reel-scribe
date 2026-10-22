"""Exercise live input while a tool is running, with atomic progress output."""
import importlib.util
import io
import json
from pathlib import Path
import queue
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'runtime'))
import editing_runtime as runtime


def test_owned_process_cooperatively_cancels_its_child():
    event = threading.Event()
    token = runtime.RUN_CANCELLATION.set(event)
    timer = threading.Timer(0.15, event.set)
    timer.start()
    try:
        started = time.monotonic()
        result = runtime.owned_process([sys.executable, '-c', 'import time; time.sleep(30)'])
        assert result.termination_reason == 'cancelled'
        assert result.returncode != 0
        assert time.monotonic() - started < 3
    finally:
        timer.cancel()
        timer.join()
        runtime.RUN_CANCELLATION.reset(token)


def test_live_ping_progress_and_cancel(monkeypatch):
    spec = importlib.util.spec_from_file_location('mcp_cancellation_test_server', ROOT / 'scripts/mcp_server.py')
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    incoming, outgoing = queue.Queue(), queue.Queue()
    started = threading.Event()
    class Input:
        def __iter__(self):
            while True:
                line = incoming.get(timeout=5)
                if line is None:
                    return
                yield line
    def fake_tool(name, arguments, *, cancel_event, progress):
        started.set()
        assert cancel_event.wait(3), 'server did not process cancellation during tool call'
        progress('Cancellation observed')
        return {'status': 'FAILED', 'cancelled': True}
    monkeypatch.setattr(server.sys, 'stdin', Input())
    monkeypatch.setattr(server, '_emit', outgoing.put)
    monkeypatch.setattr(server, 'call_tool', fake_tool)
    thread = threading.Thread(target=server.serve)
    thread.start()
    def send(value):
        incoming.put(json.dumps({'jsonrpc': '2.0', **value}) + '\n')
    try:
        send({'id': 1, 'method': 'tools/call', 'params': {
            'name': 'run_operation', 'arguments': {}, '_meta': {'progressToken': 'p'}}})
        assert started.wait(2)
        send({'id': 2, 'method': 'ping'})
        progress = outgoing.get(timeout=2)
        assert progress['method'] == 'notifications/progress'
        assert outgoing.get(timeout=2) == {'jsonrpc': '2.0', 'id': 2, 'result': {}}
        send({'method': 'notifications/cancelled', 'params': {'requestId': 1}})
        outputs = [outgoing.get(timeout=3) for _ in range(3)]
        assert outputs[-1]['id'] == 1
        assert outputs[-1]['result']['isError']
        assert [item['params']['progress'] for item in [progress] + outputs[:-1]] == [1, 2, 3]
    finally:
        incoming.put(None)
        thread.join(timeout=5)
    assert not thread.is_alive()


def test_serialized_work_directory_guard_and_eof_drain(tmp_path):
    import os
    import subprocess
    work = tmp_path / 'runs'
    work.mkdir()
    request = {'operation': 'generation-task', 'action': 'budget-create',
               'store': str(tmp_path / 'ledger.sqlite3'), 'budget_key': 'shared',
               'currency': 'USD', 'limit_micros': 100}
    env = dict(os.environ, EDITING_SKILL_WORK_ROOT=str(work),
               EDITING_FFMPEG=str(tmp_path / 'missing'), EDITING_FFPROBE=str(tmp_path / 'missing'))
    messages = [{'jsonrpc': '2.0', 'id': i, 'method': 'tools/call', 'params': {'name': 'run_operation',
        'arguments': {'request': request, 'work_dir': str(work / 'same')},
        '_meta': {'progressToken': f'p{i}'}}} for i in (1, 2)]
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/mcp_server.py')],
        input=''.join(json.dumps(m) + '\n' for m in messages), text=True,
        capture_output=True, env=env, timeout=15)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    replies = {row['id']: row for row in rows if 'id' in row}
    assert set(replies) == {1, 2}  # EOF drains both, no dropped/partial JSON.
    assert not replies[1]['result']['isError']
    assert replies[2]['result']['isError']
    assert 'NEW_WORK_DIR_UNDER_CONFIGURED_ROOT_REQUIRED' in replies[2]['result']['content'][0]['text']
    assert json.loads((work / 'same/receipt.json').read_text())['status'] == 'SUCCEEDED'
    assert any(row.get('method') == 'notifications/progress' for row in rows)


def test_cancelling_one_owned_process_does_not_cancel_another():
    from concurrent.futures import ThreadPoolExecutor
    event = threading.Event()
    def cancelled():
        token = runtime.RUN_CANCELLATION.set(event)
        try:
            return runtime.owned_process([sys.executable, '-c', 'import time; time.sleep(30)'])
        finally:
            runtime.RUN_CANCELLATION.reset(token)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cancelled)
        second = pool.submit(runtime.owned_process,
            [sys.executable, '-c', 'import time; time.sleep(.3); print("unrelated")'])
        event.set()
        assert first.result(timeout=4).termination_reason == 'cancelled'
        other = second.result(timeout=4)
        assert other.termination_reason is None and other.returncode == 0
        assert other.stdout.strip() == 'unrelated'


def test_queued_cancellation_retains_failed_receipt(tmp_path):
    event = threading.Event()
    event.set()
    token = runtime.RUN_CANCELLATION.set(event)
    try:
        receipt = runtime.run({'operation': 'generation-task', 'action': 'budget-create',
            'store': str(tmp_path / 'not-created.sqlite3'), 'budget_key': 'cancelled',
            'currency': 'USD', 'limit_micros': 100}, tmp_path / 'run', runtime.Tools())
        assert receipt['status'] == 'FAILED' and receipt['cancelled']
        assert (tmp_path / 'run/receipt.json').is_file()
        assert not (tmp_path / 'not-created.sqlite3').exists()
    finally:
        runtime.RUN_CANCELLATION.reset(token)


def test_completed_id_can_be_reused_without_erasing_new_cancel_token(monkeypatch):
    spec = importlib.util.spec_from_file_location('mcp_reused_id_server', ROOT / 'scripts/mcp_server.py')
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    incoming, outgoing = queue.Queue(), queue.Queue()
    release_reply, second_started = threading.Event(), threading.Event()
    class Input:
        def __iter__(self):
            while True:
                line = incoming.get(timeout=5)
                if line is None:
                    return
                yield line
    calls = []
    def fake_tool(name, arguments, *, cancel_event, progress):
        calls.append(cancel_event)
        if len(calls) == 2:
            second_started.set()
            assert cancel_event.wait(3)
            return {'status': 'FAILED', 'cancelled': True}
        return {'status': 'SUCCEEDED'}
    first_reply = True
    def response(identifier, result=None, error=None):
        nonlocal first_reply
        outgoing.put({'id': identifier, 'result': result, 'error': error})
        if identifier == 1 and error is None and first_reply:
            first_reply = False
            assert release_reply.wait(3)
    monkeypatch.setattr(server.sys, 'stdin', Input())
    monkeypatch.setattr(server, 'call_tool', fake_tool)
    monkeypatch.setattr(server, '_response', response)
    worker = threading.Thread(target=server.serve)
    worker.start()
    def send(value):
        incoming.put(json.dumps({'jsonrpc': '2.0', **value}) + '\n')
    call = {'id': 1, 'method': 'tools/call', 'params': {'name': 'run_operation'}}
    try:
        send(call)
        assert outgoing.get(timeout=2)['error'] is None
        send(call)
        send({'id': 2, 'method': 'ping'})
        assert outgoing.get(timeout=2)['id'] == 2  # No duplicate-ID rejection.
        release_reply.set()
        assert second_started.wait(2)
        send({'method': 'notifications/cancelled', 'params': {'requestId': 1}})
        result = outgoing.get(timeout=3)
        assert result['id'] == 1 and result['result']['isError']
        assert calls[0] is not calls[1] and not calls[0].is_set()
    finally:
        release_reply.set()
        incoming.put(None)
        worker.join(timeout=5)
    assert not worker.is_alive()

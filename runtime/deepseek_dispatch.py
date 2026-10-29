"""Explicit, durable DeepSeek text/function request surface.

Prompt bodies live in caller-owned files and the private call ledger, rather than
being copied into the public operation request or receipt. Send is a distinct
action and is never run by prepare/read/result.
"""
import hashlib
import json
from pathlib import Path

from deepseek_text import DeepSeekCallStore, DeepSeekTextClient, DeepSeekError
from editing_runtime import exact_keys


def execute(request, directory=None, tools=None):
    if not isinstance(request, dict) or request.get('operation') != 'model-text-deepseek':
        raise DeepSeekError('MODEL_TEXT_OPERATION_REQUIRED')
    action = request.get('action')
    fields = {
        'budget-create': ['budget_key', 'currency', 'limit_micros'],
        'prepare': ['intent_key', 'body_path', 'body_sha256', 'budget_key', 'reservation_micros'],
        'read': ['call_id'],
        'result': ['call_id'],
        'send-once': ['call_id'],
        'settle-cost': ['call_id', 'event_key', 'evidence_path', 'evidence_sha256'],
    }
    if action not in fields:
        raise DeepSeekError('MODEL_TEXT_ACTION_UNSUPPORTED')
    extra = ['timeout_seconds'] if action == 'send-once' else []
    exact_keys(request, ['operation', 'action', 'store'] + fields[action] + extra,
               ['operation', 'action', 'store'] + fields[action])
    path = Path(request['store'])
    if not path.is_absolute():
        raise DeepSeekError('ABSOLUTE_MODEL_LEDGER_REQUIRED')
    store = DeepSeekCallStore(path)
    if action == 'budget-create':
        store.create_budget(request['budget_key'], request['currency'], request['limit_micros'])
        return {'budget_key': request['budget_key'], 'status': 'CREATED_OR_MATCHED',
                'hard_provider_cap': False}
    if action == 'prepare':
        body_path = Path(request['body_path'])
        if not body_path.is_absolute() or not body_path.is_file():
            raise DeepSeekError('ABSOLUTE_BODY_FILE_REQUIRED')
        body_bytes = body_path.read_bytes()
        if hashlib.sha256(body_bytes).hexdigest() != request['body_sha256']:
            raise DeepSeekError('BODY_HASH_MISMATCH')
        body = json.loads(body_bytes.decode('utf-8'))
        return store.prepare(request['intent_key'], body, request['budget_key'],
                             request['reservation_micros'])
    if action == 'read':
        return store.read(request['call_id'])
    if action == 'result':
        return store.result(request['call_id'])
    if action == 'settle-cost':
        return store.settle_cost(request['call_id'], request['event_key'],
                                 request['evidence_path'], request['evidence_sha256'])
    client = DeepSeekTextClient(timeout_seconds=request.get('timeout_seconds', 120))
    return store.send_once(request['call_id'], client)

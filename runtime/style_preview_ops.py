"""Same-base, explicit presentation comparisons; never choose or commit a winner."""
import copy
import html
import json
from pathlib import Path
import re
from urllib.parse import quote

from editing_runtime import exact_keys, fingerprint, require, run, sha256, source, write_json
from work_ops import connect, load
import style_recipe_ops
from source_binding import document_references


def state(store):
    db = connect(store)
    try:
        return load(db)
    finally:
        db.close()


def reference(path):
    return {'path': str(path), 'sha256': sha256(path)}


def execute(request, directory, tools):
    fields = ['operation', 'store', 'expected_version', 'variants']
    exact_keys(request, fields + ['audio_backend', 'source_consumption'], fields)
    require(request['operation'] == 'style-recipe-preview', 'STYLE_PREVIEW_OPERATION_UNSUPPORTED')
    variants = request['variants']
    require(isinstance(variants, list) and 2 <= len(variants) <= 4, 'STYLE_PREVIEW_REQUIRES_2_TO_4_VARIANTS')
    ids = []
    for variant in variants:
        fields = ['id', 'recipe', 'expected_recipe_sha256', 'capabilities', 'scope']
        exact_keys(variant, fields, fields)
        require(isinstance(variant['id'], str)
                and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}', variant['id']), 'STYLE_PREVIEW_ID_INVALID')
        ids.append(variant['id'])
    require(len(set(ids)) == len(ids), 'STYLE_PREVIEW_DUPLICATE_ID')
    base = state(request['store'])
    require(base['version'] == request['expected_version'], 'WORK_VERSION_CONFLICT')
    # All recipes must compile before any expensive render is attempted.
    compiled = []
    variants_dir = directory / 'variants'
    variants_dir.mkdir(exist_ok=False)
    for variant in variants:
        folder = variants_dir / variant['id']
        folder.mkdir(exist_ok=False)
        recipe_dir = folder / 'compile'
        recipe_dir.mkdir()
        result = style_recipe_ops.execute({'operation': 'style-recipe-compile',
            'document': copy.deepcopy(base['document']), 'base_version': base['version'],
            'expected_document_sha256': base['document_sha256'],
            **{key: copy.deepcopy(variant[key]) for key in
               ['recipe', 'expected_recipe_sha256', 'capabilities', 'scope']}}, recipe_dir, tools)
        compiled.append((variant, folder, result, reference(recipe_dir / 'candidate.json')))
    recovery = {'operation': 'work-batch-render', 'action': 'prepare',
        'batch_dir': str((directory / 'recovery-batch').resolve()), 'batch_id': 'style-preview',
        'jobs': [{'id': variant['id'], 'store': request['store'], 'expected_version': base['version'],
                  'preview_candidate': candidate,
                  **{key: copy.deepcopy(request[key]) for key in ['audio_backend', 'source_consumption'] if key in request}}
                 for variant, _, _, candidate in compiled]}
    write_json(directory / 'batch-prepare-request.json', recovery)
    prepared = run(recovery, directory / 'batch-prepare', tools)
    require(prepared['status'] == 'SUCCEEDED', 'STYLE_PREVIEW_BATCH_PREPARE_FAILED: ' + prepared.get('error', 'unknown'))
    resume = {'operation': 'work-batch-render', 'action': 'run', 'batch_dir': recovery['batch_dir'],
              'manifest_sha256': prepared['result']['manifest_sha256'], 'job_ids': ids, 'retry_failed': False}
    write_json(directory / 'batch-resume-request.json', resume)
    batch_receipt = run(resume, directory / 'batch-run', tools)
    require(batch_receipt['status'] == 'SUCCEEDED', 'STYLE_PREVIEW_RENDER_FAILED: ' + batch_receipt.get('error', 'unknown'))
    batch = batch_receipt['result']
    require(batch['status'] == 'RENDERED', 'STYLE_PREVIEW_RENDER_FAILED_OR_STALE: ' + batch['status'])
    jobs = {job['id']: job for job in batch['jobs']}
    results = []
    for variant, folder, recipe_result, candidate in compiled:
        job = jobs[variant['id']]
        require(job['status'] == 'RENDERED' and job['current_version_matches'], 'STYLE_PREVIEW_STALE_BASE')
        receipt_ref = {'path': job['receipt'], 'sha256': job['receipt_sha256']}
        source(receipt_ref)
        receipt_bytes = Path(job['receipt']).read_bytes()
        import hashlib
        require(hashlib.sha256(receipt_bytes).hexdigest() == job['receipt_sha256'], 'STYLE_PREVIEW_RECEIPT_CHANGED')
        consumed_receipt = json.loads(receipt_bytes)
        rendered = consumed_receipt['result']
        bindings = [item for item in consumed_receipt['artifacts'] if item['path'] == 'render-binding.json']
        require(len(bindings) == 1, 'STYLE_PREVIEW_BINDING_UNBOUND')
        binding_ref = {'path': str(Path(job['receipt']).parent / 'render-binding.json'),
                       'sha256': bindings[0]['sha256']}
        require(source(binding_ref)['bytes'] == bindings[0]['bytes'], 'STYLE_PREVIEW_BINDING_CHANGED')
        require(rendered['current_at_finish'] and rendered['preview_current_at_finish'], 'STYLE_PREVIEW_STALE_BASE')
        require(rendered['document_sha256'] == recipe_result['document_sha256'], 'STYLE_PREVIEW_DOCUMENT_MISMATCH')
        require(rendered['source_consumption']['adoptable'], 'STYLE_PREVIEW_SOURCE_NOT_ADOPTABLE')
        results.append({'id': variant['id'], 'recipe_sha256': variant['expected_recipe_sha256'],
            'mapped_parameters': recipe_result['mapped_parameters'],
            'candidate': candidate, 'document_sha256': rendered['document_sha256'],
            'video': rendered['video'], 'render_receipt': receipt_ref,
            'render_binding': binding_ref,
            'source_consumption': rendered['source_consumption'],
            'technical_status': rendered['technical_status'], 'style_effect': 'NOT_VERIFIED',
            'listening_review': 'NOT_RUN', 'native_editor_acceptance': 'NOT_RUN'})
    # Do not publish a successful set after partial render failure, stale head,
    # changed originals, candidate substitution, or loss of an earlier output.
    for ref in document_references(base['document']):
        source(ref)
    for variant in variants:
        source(variant['recipe']['style']['card'])
    for result in results:
        for key in ['candidate', 'video', 'render_receipt', 'render_binding']:
            source(result[key])
    require(state(request['store'])['version'] == base['version'], 'STYLE_PREVIEW_STALE_BASE')
    manifest = {'schema': 'style-preview/1', 'status': 'PREVIEWS_RENDERED_NOT_COMMITTED',
        'work_id': base['work_id'], 'base_version': base['version'],
        'base_document_sha256': base['document_sha256'], 'variants': results,
        'source_consumption_request': copy.deepcopy(request.get('source_consumption')),
        'audio_backend_request': copy.deepcopy(request.get('audio_backend')),
        'applied_to_work': False, 'selected_variant': None,
        'batch_prepare_request': reference(directory / 'batch-prepare-request.json'),
        'batch_resume_request': reference(directory / 'batch-resume-request.json'),
        'same_content': 'UNCHANGED_SOURCE_PLAN_CAPTIONS_AND_EVIDENCE',
        'head_current_at_final_check': True, 'adoption_requires_fresh_head': True,
        'adoption_authorized_by_preview': False,
        'content_review': 'NOT_RUN', 'style_effect': 'NOT_VERIFIED',
        'scope': 'Explicit subtitle presentation and existing-track gain only; no semantic style execution'}
    cards = []
    root = directory.resolve()
    for result in results:
        video = Path(result['video']['path']).resolve()
        require(video.is_relative_to(root), 'STYLE_PREVIEW_OUTPUT_OUTSIDE_DIRECTORY')
        relative = quote(video.relative_to(root).as_posix(), safe='/')
        cards.append('<section><h2>' + html.escape(result['id']) + '</h2><video controls preload="metadata" src="'
                     + relative + '"></video><pre>'
                     + html.escape(json.dumps(result['mapped_parameters'], ensure_ascii=False, indent=2))
                     + '</pre><p>技术预览，未做风格效果、听检或真实用户验收。未提交当前作品。</p></section>')
    page = ('<!doctype html><html lang="zh"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>同内容呈现候选对比</title><style>body{font-family:system-ui;margin:2rem;max-width:1100px}'
            'main{display:flex;flex-wrap:wrap;gap:1rem}section{flex:1 1 320px;border:1px solid #bbb;padding:1rem}'
            'video{width:100%;max-height:480px}pre{white-space:pre-wrap}</style>'
            '<h1>同内容呈现候选对比</h1><p>没有自动选择胜者。采用前需要重新核对作品版本。</p><main>'
            + ''.join(cards) + '</main></html>')
    comparison = directory / 'comparison.html'
    with comparison.open('x', encoding='utf-8') as stream:
        stream.write(page)
    manifest['comparison'] = reference(comparison)
    try:
        write_json(directory / 'style-preview.json', manifest)
    except Exception:
        comparison.unlink()
        raise
    return {**manifest, 'manifest': reference(directory / 'style-preview.json')}

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import socket
import uuid
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .jobs import Runner, TERMINAL
from .media import IMAGE_EXT, VIDEO_EXT, inspect_media
from .models import InferenceConfig, JobRequest, Provider, Settings, TollJobRequest
from .providers import probe, safe_error
from .store import Store, now
from .toll import PROFILES, prepare_config

PROJECT = Path(__file__).resolve().parent.parent
MAX_FILE = 512 * 1024 * 1024
MAX_UPLOAD = 2 * 1024 * 1024 * 1024


def create_app(data_dir: Path | None = None) -> FastAPI:
    root = (data_dir or Path(os.environ.get('STUDIO_DATA_DIR', PROJECT / 'data'))).resolve()

    @asynccontextmanager
    async def lifespan(app):
        store = Store(root)
        app.state.store = store
        app.state.runner = Runner(store)
        app.state.runner.start()
        try:
            yield
        finally:
            await app.state.runner.stop()
            store.close()

    app = FastAPI(title='CAT Studio', version='0.2.0', lifespan=lifespan)

    @app.middleware('http')
    async def local_origin(request: Request, call_next):
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and request.url.path.startswith('/api/'):
            origin = request.headers.get('origin')
            if origin and urlsplit(origin).netloc != request.headers.get('host'):
                return JSONResponse({'detail': 'Origem não permitida.'}, status_code=403)
            length = request.headers.get('content-length')
            limit = MAX_UPLOAD if request.url.path == '/api/media' else 1024 * 1024
            if not length or not length.isdigit():
                return JSONResponse({'detail': 'Envie Content-Length.'}, status_code=411)
            if int(length) > limit:
                return JSONResponse({'detail': 'Requisição excede o limite de tamanho.'}, status_code=413)
        return await call_next(request)

    def settings() -> Settings:
        return Settings(**(app.state.store.get('settings', 1) or {}))

    def public_settings():
        return {'providers': [{**p.model_dump(exclude={'api_key'}), 'has_api_key': bool(p.api_key)} for p in settings().providers]}

    def provider_for(key):
        p = next((p for p in settings().providers if p.id == key), None)
        if not p:
            raise HTTPException(400, 'Provedor não encontrado. Salve a configuração primeiro.')
        return p

    def get_job(key):
        job = app.state.store.get('jobs', key)
        if not job:
            raise HTTPException(404, 'Execução não encontrada.')
        return job

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'application': 'decision-studio', 'edition': 'toll-cat', 'version': '0.2.0', 'hostname': socket.gethostname()}

    @app.get('/api/toll/profiles')
    def toll_profiles():
        return list(PROFILES.values())

    @app.get('/api/toll/defaults')
    def toll_defaults():
        config, _ = prepare_config(InferenceConfig(task='toll_cat', video_mode='uniform', max_frames=8))
        return {'config': config.model_dump()}

    @app.get('/api/defaults')
    def defaults():
        return {'config': InferenceConfig().model_dump(), 'limits': {'file_bytes': MAX_FILE, 'upload_bytes': MAX_UPLOAD, 'images_per_context': 16}}

    @app.get('/api/settings')
    def read_settings():
        return public_settings()

    @app.put('/api/settings')
    def write_settings(body: Settings):
        old = {p.id: p for p in settings().providers}
        for p in body.providers:
            if p.api_key is None and p.id in old:
                p.api_key = old[p.id].api_key
        app.state.store.put('settings', 1, body.model_dump())
        return public_settings()

    @app.post('/api/providers/test')
    async def test_provider(body: Provider):
        if body.api_key is None:
            old = next((p for p in settings().providers if p.id == body.id), None)
            body.api_key = old.api_key if old else None
        try:
            return await probe(body)
        except Exception as exc:
            raise HTTPException(400, safe_error(exc, [body])) from exc

    @app.get('/api/media')
    def list_media():
        return app.state.store.all('media')

    @app.post('/api/media')
    async def upload(files: Annotated[list[UploadFile], File()], paths: Annotated[str, Form()] = '[]'):
        if not 1 <= len(files) <= 500:
            raise HTTPException(400, 'Selecione de 1 a 500 arquivos por envio.')
        try:
            relative = json.loads(paths)
            if not isinstance(relative, list) or (relative and len(relative) != len(files)) or any(not isinstance(p, str) for p in relative):
                raise ValueError()
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, 'Lista de caminhos inválida.') from exc
        (root / 'media').mkdir(exist_ok=True)
        (root / 'previews').mkdir(exist_ok=True)
        uploaded, errors = [], []
        for index, file in enumerate(files):
            name = PurePosixPath((file.filename or 'arquivo').replace('\\', '/')).name[:200]
            suffix = Path(name).suffix.lower()
            media_id = uuid.uuid4().hex
            path, preview = root / 'media' / (media_id + suffix), root / 'previews' / (media_id + '.jpg')
            try:
                if suffix not in IMAGE_EXT | VIDEO_EXT:
                    raise ValueError('Formato não suportado.')
                size = 0
                with path.open('wb') as dest:
                    while chunk := await file.read(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_FILE:
                            raise ValueError('Arquivo excede 512 MiB.')
                        await asyncio.to_thread(dest.write, chunk)
                meta = await asyncio.to_thread(inspect_media, path, preview)
                rel = relative[index].replace('\\', '/')[:1000] if relative else name
                if PurePosixPath(rel).is_absolute() or '..' in PurePosixPath(rel).parts:
                    rel = name
                record = {'id': media_id, 'name': name, 'relative_path': rel, 'size': size, 'created_at': now(),
                          'path': path.relative_to(root).as_posix(), 'preview_path': preview.relative_to(root).as_posix(), **meta}
                app.state.store.put('media', media_id, record)
                uploaded.append(record)
            except Exception as exc:
                path.unlink(missing_ok=True)
                preview.unlink(missing_ok=True)
                errors.append({'name': name, 'error': str(exc)[:500]})
            finally:
                await file.close()
        return {'media': uploaded, 'errors': errors}

    @app.get('/api/media/{media_id}/preview')
    def media_preview(media_id: str):
        media = app.state.store.get('media', media_id)
        if not media:
            raise HTTPException(404)
        return FileResponse(root / media['preview_path'], media_type='image/jpeg')

    @app.get('/api/jobs')
    def jobs():
        return app.state.store.all('jobs')

    @app.post('/api/jobs', status_code=202)
    def submit(body: JobRequest):
        try:
            return app.state.runner.submit(body, provider_for(body.config.provider_id))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/toll/jobs', status_code=202)
    def toll_submit(body: TollJobRequest):
        body.config.task = 'toll_cat'
        return submit(body)

    @app.get('/api/jobs/{job_id}')
    def job_detail(job_id: str):
        return get_job(job_id)

    @app.post('/api/jobs/{job_id}/cancel')
    def cancel(job_id: str):
        job = get_job(job_id)
        app.state.runner.cancel(job_id)
        return {'status': job['status'], 'cancel_requested': job['status'] not in TERMINAL}

    @app.get('/api/jobs/{job_id}/results')
    def results(job_id: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
        job = get_job(job_id)
        return {'items': app.state.store.results(job_id, offset, limit), 'total': job['completed']}

    @app.get('/api/jobs/{job_id}/frames/{seq}/{sample}')
    def result_preview(job_id: str, seq: int, sample: int):
        get_job(job_id)
        rows = app.state.store.results(job_id, max(0, seq), 1)
        if seq < 0 or not rows or not 0 <= sample < len(rows[0]['samples']):
            raise HTTPException(404)
        return FileResponse(root / rows[0]['samples'][sample]['frame_path'], media_type='image/jpeg')

    @app.get('/api/jobs/{job_id}/export')
    def export(job_id: str, format: Literal['json', 'jsonl', 'csv'] = 'json'):
        job = get_job(job_id)
        def rows():
            for offset in range(0, job['completed'], 200):
                yield from app.state.store.results(job_id, offset, min(200, job['completed'] - offset))
        def encode(value):
            return json.dumps(value, ensure_ascii=False, allow_nan=False)
        def stream():
            if format == 'json':
                yield '{"job":' + encode(job) + ',"results":['
                for index, row in enumerate(rows()):
                    yield (',' if index else '') + encode(row)
                yield ']}'
            elif format == 'jsonl':
                yield encode({'type': 'job', 'job': job}) + '\n'
                for row in rows():
                    yield encode({'type': 'result', 'result': row}) + '\n'
            else:
                output = io.StringIO()
                writer = csv.writer(output)
                def line(values):
                    output.seek(0); output.truncate(0)
                    writer.writerow([("'" + str(v)) if str(v).lstrip().startswith(('=', '+', '-', '@')) else v for v in values])
                    return output.getvalue()
                if job['config'].get('task') == 'toll_cat':
                    yield '\ufeff' + line(['seq', 'files', 'timestamps_seconds', 'status', 'profile_id', 'profile_version',
                                           'model_choice', 'suggested_cat', 'candidate', 'candidate_label', 'probability',
                                           'selected', 'uncertain_probability', 'margin', 'evidence', 'needs_review', 'reasons', 'error'])
                    for row in rows():
                        c = row.get('classification', {})
                        for item in c.get('ranking') or [{}]:
                            yield line([row['seq'], ' | '.join(s['name'] for s in row['samples']),
                                        ' | '.join(str(s.get('timestamp', '')) for s in row['samples']),
                                        c.get('status', row['status']), job['toll_profile']['id'], job['toll_profile']['version'],
                                        c.get('selected', ''), c.get('suggested_cat') or '', item.get('code', ''),
                                        item.get('label', ''), item.get('probability') if item.get('probability') is not None else '',
                                        item.get('selected', ''), c.get('uncertain_probability', ''), c.get('margin', ''),
                                        c.get('evidence', ''), row['needs_review'], ' | '.join(c.get('reasons', [])), row.get('error', '')])
                    return
                yield '\ufeff' + line(['seq', 'files', 'timestamps_seconds', 'status', 'field', 'value', 'probability', 'expected_value', 'needs_review', 'error'])
                for row in rows():
                    fields = row.get('fields') or {'': {}}
                    for name, field in fields.items():
                        yield line([row['seq'], ' | '.join(s['name'] for s in row['samples']),
                                    ' | '.join(str(s.get('timestamp', '')) for s in row['samples']), row['status'], name,
                                    encode(field.get('value')), field.get('probability', ''), field.get('expected_value', ''), row['needs_review'], row.get('error', '')])
        return StreamingResponse(stream(), media_type={'csv': 'text/csv', 'json': 'application/json', 'jsonl': 'application/x-ndjson'}[format],
                                 headers={'Content-Disposition': f'attachment; filename="decision-{job_id[:8]}.{format}"'})

    @app.get('/{path:path}', include_in_schema=False)
    def frontend(path: str):
        dist = PROJECT / 'dist'
        candidate = (dist / path).resolve()
        if path.startswith('api/'):
            raise HTTPException(404)
        if candidate.is_relative_to(dist.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        if (dist / 'index.html').exists():
            return FileResponse(dist / 'index.html')
        return JSONResponse({'message': 'Execute npm install e npm run build para preparar a interface.'}, status_code=503)

    return app


app = create_app()

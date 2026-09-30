from __future__ import annotations

import asyncio
import math
import time
import uuid
from collections import OrderedDict
from pathlib import PurePosixPath

from .media import Sampler, frame_plan
from .models import InferenceConfig, JobRequest, Provider, validate_schema
from .providers import decide, safe_error, vision_json
from .store import Store, now
from .toll import classify, prepare_config

TERMINAL = {'completed', 'partial', 'failed', 'cancelled', 'interrupted'}


def plan(media: list[dict], config: InferenceConfig) -> tuple[list[list[dict]], int, list[str]]:
    """Plan groups without decoding or retaining images in memory."""
    warnings = []
    lengths = {}
    for m in media:
        indices, requested = frame_plan(m, config)
        lengths[m['id']] = len(indices)
        if not indices:
            raise ValueError(f'{m["name"]}: o intervalo selecionado não contém quadros.')
        if requested > len(indices) and config.video_mode != 'uniform':
            warnings.append(f'{m["name"]}: {len(indices)} de {requested} quadros; limite de amostragem aplicado.')
    if config.grouping == 'individual':
        groups = [[m] for m in media]
        total = len(media) if config.task == 'toll_cat' else sum(math.ceil(lengths[m['id']] / (config.video_group_size if m['kind'] == 'video' else 1)) for m in media)
    else:
        by_key = OrderedDict()
        for m in media:
            key = 'all' if config.grouping == 'together' else str(PurePosixPath(m.get('relative_path') or m['name']).parent)
            by_key.setdefault(key, []).append(m)
        groups = list(by_key.values())
        for group in groups:
            if sum(lengths[m['id']] for m in group) > 16:
                raise ValueError('Um conjunto excede 16 imagens/quadros. Reduza a seleção ou use avaliação individual com janelas de vídeo.')
        total = len(groups)
    if total > 20000:
        raise ValueError('Uma execução pode conter até 20.000 decisões. Divida a seleção.')
    return groups, total, warnings


class Runner:
    def __init__(self, store: Store):
        self.store = store
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self.events: dict[str, asyncio.Event] = {}
        self.worker: asyncio.Task | None = None

    def start(self):
        for job in self.store.all('jobs'):
            if job['status'] not in TERMINAL:
                job.update(status='interrupted', finished_at=now(), error='O aplicativo foi reiniciado. Os resultados já gravados foram preservados.')
                self.store.put('jobs', job['id'], job)
        self.worker = asyncio.create_task(self.loop())

    async def stop(self):
        for event in self.events.values():
            event.set()
        if self.worker:
            # Finish any in-flight decoder before closing the database.
            await self.queue.join()
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)

    def submit(self, request: JobRequest, provider: Provider) -> dict:
        profile = None
        if request.config.task == 'toll_cat':
            request.config, profile = prepare_config(request.config)
        if self.queue.full():
            raise ValueError('Fila cheia. Aguarde uma execução terminar.')
        if len(set(request.media_ids)) != len(request.media_ids):
            raise ValueError('A seleção contém arquivos repetidos.')
        validate_schema(request.config.output_schema)
        media = [self.store.get('media', key) for key in request.media_ids]
        if any(m is None for m in media):
            raise ValueError('Um arquivo da seleção não existe mais.')
        groups, total, warnings = plan(media, request.config)
        job_id = uuid.uuid4().hex
        job = {'id': job_id, 'name': request.name, 'created_at': now(), 'status': 'queued',
               'config': request.config.model_dump(), 'media_ids': request.media_ids,
               'provider': provider.model_dump(exclude={'api_key'}), 'total': total, 'completed': 0,
               'failed': 0, 'review': 0, 'warnings': warnings}
        if profile:
            job['toll_profile'] = profile
        self.store.put('jobs', job_id, job)
        self.events[job_id] = asyncio.Event()
        self.queue.put_nowait((job, groups, provider.model_copy(deep=True)))
        return job

    def cancel(self, job_id: str):
        if job_id in self.events:
            self.events[job_id].set()

    async def loop(self):
        while True:
            job, groups, provider = await self.queue.get()
            try:
                await self.run(job, groups, provider)
            except Exception as exc:
                job.update(status='failed', error=safe_error(exc, [provider]), finished_at=now())
                self.store.put('jobs', job['id'], job)
            finally:
                self.events.pop(job['id'], None)
                self.queue.task_done()

    async def interruptible(self, coro, stop: asyncio.Event):
        task, cancel = asyncio.create_task(coro), asyncio.create_task(stop.wait())
        try:
            done, _ = await asyncio.wait([task, cancel], return_when=asyncio.FIRST_COMPLETED)
            if cancel in done:
                task.cancel()
                raise asyncio.CancelledError()
            return await task
        finally:
            task.cancel()
            cancel.cancel()
            await asyncio.gather(task, cancel, return_exceptions=True)

    async def samples(self, groups, config, job_id, stop):
        for group in groups:
            pending = []
            for media in group:
                sampler = await asyncio.to_thread(Sampler, media, self.store.root, self.store.root / 'frames' / job_id, config)
                try:
                    while not stop.is_set():
                        sample = await asyncio.to_thread(sampler.next)
                        if sample is None:
                            break
                        pending.append(sample)
                        width = config.video_group_size if media['kind'] == 'video' else 1
                        if config.task != 'toll_cat' and config.grouping == 'individual' and len(pending) == width:
                            yield pending
                            pending = []
                finally:
                    await asyncio.to_thread(sampler.close)
            if pending and not stop.is_set():
                yield pending
            if stop.is_set():
                return

    async def run(self, job, groups, provider):
        config = InferenceConfig(**job['config'])
        stop = self.events[job['id']]
        job.update(status='running', started_at=now())
        self.store.put('jobs', job['id'], job)
        started = time.perf_counter()
        batch, bytes_count, images_count = [], 0, 0

        async def flush():
            nonlocal batch, bytes_count, images_count
            if not batch or stop.is_set():
                return
            try:
                if config.pipeline == 'native_decision':
                    results = await self.interruptible(decide(provider, config, batch), stop)
                else:
                    results = [await self.interruptible(vision_json(provider, config, batch[0]), stop)]
            except asyncio.CancelledError:
                stop.set()
                return
            except Exception as exc:
                results = [{'error': safe_error(exc, [provider])} for _ in batch]
            for samples, output in zip(batch, results):
                if config.task == 'toll_cat' and not output.get('error'):
                    try:
                        output['classification'] = classify(output, job['toll_profile'], config)
                    except ValueError as exc:
                        output = {'error': safe_error(exc, [provider])}
                review = bool(output.get('error')) or any(f.get('probability') is not None and f['probability'] < config.review_threshold for f in output.get('fields', {}).values())
                review = review or output.get('classification', {}).get('needs_review', False)
                seq = job['completed']
                row = {'seq': seq, 'created_at': now(), 'status': 'error' if output.get('error') else 'ok',
                       'samples': [{k: v for k, v in s.items() if k != 'image'} for s in samples],
                       'needs_review': review, **output}
                self.store.add_result(job['id'], seq, row)
                job['completed'] += 1
                job['failed'] += int(bool(output.get('error')))
                job['review'] += int(review)
            self.store.put('jobs', job['id'], job)
            batch, bytes_count, images_count = [], 0, 0

        try:
            async for samples in self.samples(groups, config, job['id'], stop):
                size = sum(len(s['image']) for s in samples)
                limit = config.batch_size if config.pipeline == 'native_decision' else 1
                if batch and (len(batch) >= limit or images_count + len(samples) > 64 or bytes_count + size > 28 * 1024 * 1024):
                    await flush()
                if stop.is_set():
                    break
                batch.append(samples)
                bytes_count += size
                images_count += len(samples)
            await flush()
            status = 'cancelled' if stop.is_set() else ('failed' if job['failed'] == job['total'] else 'partial' if job['failed'] else 'completed')
            job.update(status=status)
        except Exception as exc:
            job.update(status='partial' if job['completed'] else 'failed', error=safe_error(exc, [provider]))
        finally:
            job.update(finished_at=now(), elapsed_ms=round((time.perf_counter() - started) * 1000))
            self.store.put('jobs', job['id'], job)

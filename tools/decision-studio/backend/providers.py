from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Any

import httpx
from jsonschema import Draft202012Validator

from .models import InferenceConfig, Provider, to_json_schema


def endpoint(base: str, path: str) -> str:
    if base.endswith('/v1') and path.startswith('/v1/'):
        return base + path[3:]
    return base + path


def safe_error(exc: Exception, providers=()) -> str:
    msg = str(exc) or type(exc).__name__
    for provider in providers:
        if provider and provider.api_key:
            msg = msg.replace(provider.api_key, '[credencial ocultada]')
    return msg[:1500]


async def request_json(provider: Provider, path: str, body: dict | None = None) -> dict:
    headers = {'Accept': 'application/json'}
    if provider.api_key:
        headers['Authorization'] = f'Bearer {provider.api_key}'
    payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode() if body is not None else None
    if payload and len(payload) > 32 * 1024 * 1024:
        raise ValueError('Requisição excede 32 MiB. Reduza lote, resolução ou imagens por grupo.')
    if payload:
        headers['Content-Type'] = 'application/json'
    try:
        async with httpx.AsyncClient(timeout=provider.timeout_seconds, trust_env=False, follow_redirects=False) as client:
            async with client.stream('GET' if body is None else 'POST', endpoint(provider.base_url, path), headers=headers, content=payload) as response:
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 8 * 1024 * 1024:
                        raise ValueError('Resposta do provedor excede 8 MiB.')
                if response.status_code >= 300:
                    detail = data.decode('utf-8', errors='replace')[:1000]
                    hint = ' Use codex/decision-vision com --decision-seqs 64 e --mmproj.' if path.endswith('decision') and response.status_code in {400, 404, 501} else ''
                    raise ValueError(f'{provider.name}: HTTP {response.status_code}. {detail}{hint}')
                value = json.loads(data)
                if not isinstance(value, dict) or value.get('error'):
                    raise ValueError(f'Resposta incompatível do provedor: {str(value)[:1000]}')
                return value
    except httpx.TimeoutException as exc:
        raise ValueError(f'{provider.name}: tempo limite de {provider.timeout_seconds}s atingido.') from exc
    except httpx.RequestError as exc:
        raise ValueError(f'Não foi possível conectar a {provider.name} ({provider.base_url}). Verifique endereço, porta e servidor.') from exc
    except json.JSONDecodeError as exc:
        raise ValueError('O provedor não retornou JSON válido.') from exc


async def probe(provider: Provider) -> dict:
    start = time.perf_counter()
    raw = await request_json(provider, '/v1/models')
    models = []
    for item in raw.get('data', raw.get('models', [])):
        if isinstance(item, dict) and (item.get('id') or item.get('name')):
            models.append({'id': item.get('id', item.get('name')), 'decision': item.get('decision'), 'meta': item.get('meta')})
    return {'ok': True, 'models': models, 'latency_ms': round((time.perf_counter() - start) * 1000),
            'message': 'Conectado. Capacidades declaradas pelo servidor; valide o modelo com suas imagens.'}


def content_parts(samples: list[dict], context: str) -> list[dict]:
    parts = [{'type': 'text', 'text': context or 'Evaluate the following visual evidence in the given order.'}]
    for i, s in enumerate(samples):
        label = f'Image {i + 1}: {s.get("relative_path") or s["name"]}'
        if s.get('timestamp') is not None:
            label += f' | video frame {s["frame_index"]} | t={s["timestamp"]:.3f}s'
        parts += [{'type': 'text', 'text': label}, {'type': 'image_url', 'image_url': {'url': s['image']}}]
    return parts


def probability(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('O provedor retornou uma probabilidade inválida.')
    return float(value)


def normalize_decision(item: dict, schema: dict) -> dict:
    decision, fields = item.get('decision'), item.get('fields')
    if not isinstance(decision, dict) or not isinstance(fields, dict):
        raise ValueError('Resposta de decisão sem decision/fields.')
    Draft202012Validator(to_json_schema(schema)).validate(decision)
    out = {}
    for name, value in decision.items():
        f = fields.get(name)
        if not isinstance(f, dict):
            raise ValueError(f'Resposta sem metadados do campo {name}.')
        distribution = f.get('distribution')
        if distribution is not None:
            if not isinstance(distribution, list) or not distribution:
                raise ValueError('Distribuição inválida.')
            ps = [probability(d.get('probability')) for d in distribution]
            if None in ps or not math.isclose(sum(ps), 1, abs_tol=1e-4):
                raise ValueError('Distribuição incompleta ou não normalizada.')
        out[name] = {**f, 'value': value, 'probability': probability(f.get('probability'))}
    return {'decision': decision, 'fields': out, 'usage': item.get('usage', {})}


def request_summary(config: InferenceConfig, groups: list[list[dict]]) -> dict:
    return {'config': config.model_dump(), 'groups': [[{
        **{k: v for k, v in s.items() if k != 'image'},
        'image_sha256': hashlib.sha256(s['image'].encode()).hexdigest(),
    } for s in g] for g in groups]}


async def decide(provider: Provider, config: InferenceConfig, groups: list[list[dict]]) -> list[dict]:
    body = {'contexts': [{'content': content_parts(g, config.context)} for g in groups],
            'instructions': config.instructions, 'schema': config.output_schema,
            'mode': config.decision_mode, 'tree_max': config.tree_max,
            'cache_prompt': config.cache_prompt, 'return_distribution': True}
    if config.model.strip():
        body['model'] = config.model.strip()
    start = time.perf_counter()
    raw = await request_json(provider, '/v1/decision', body)
    results = raw.get('results')
    if not isinstance(results, list) or len(results) != len(groups):
        raise ValueError('A quantidade de decisões não corresponde aos contextos enviados.')
    duration = (time.perf_counter() - start) * 1000
    return [{**normalize_decision(item, config.output_schema), 'raw': {**raw, 'results': [item]},
             'request': request_summary(config, [groups[i]]), 'batch_size': len(groups), 'batch_index': i,
             'batch_roundtrip_ms': duration, 'amortized_ms': duration / len(groups),
             'score_kind': 'constrained_probability'} for i, item in enumerate(results)]


async def vision_json(provider: Provider, config: InferenceConfig, samples: list[dict]) -> dict:
    body: dict[str, Any] = {
        'messages': [{'role': 'system', 'content': config.instructions + '\nReturn only JSON matching the schema.'},
                     {'role': 'user', 'content': content_parts(samples, config.context)}],
        'stream': False, 'temperature': config.temperature, 'top_p': config.top_p,
        'max_tokens': config.max_tokens, 'chat_template_kwargs': {'enable_thinking': False},
        'response_format': {'type': 'json_schema', 'json_schema': {'name': 'visual_decision', 'strict': True, 'schema': to_json_schema(config.output_schema)}}}
    if config.model.strip():
        body['model'] = config.model.strip()
    if config.seed is not None:
        body['seed'] = config.seed
    start = time.perf_counter()
    raw = await request_json(provider, '/v1/chat/completions', body)
    try:
        choice = raw['choices'][0]
        if choice.get('finish_reason') == 'length':
            raise ValueError('Saída truncada. Aumente o limite de tokens.')
        value = json.loads(choice['message']['content'])
        Draft202012Validator(to_json_schema(config.output_schema)).validate(value)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('O modelo não retornou um objeto JSON válido.') from exc
    return {'decision': value, 'fields': {k: {'value': v, 'probability': None} for k, v in value.items()},
            'usage': raw.get('usage', {}), 'raw': raw, 'request': request_summary(config, [samples]),
            'amortized_ms': (time.perf_counter() - start) * 1000, 'score_kind': 'generated_json'}

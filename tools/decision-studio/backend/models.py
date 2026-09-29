from __future__ import annotations

import math
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DEFAULT_SCHEMA = {
    "scene": {"type": "enum", "choices": ["indoor", "outdoor", "uncertain"], "description": "Is the scene indoors or outdoors?"},
    "person_visible": {"type": "boolean", "description": "Is at least one person visible?"},
    "needs_review": {"type": "boolean", "description": "Is the visual evidence ambiguous or insufficient?"},
}

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Provider(StrictModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    base_url: str = "http://127.0.0.1:8080"
    protocol: Literal["llama_cpp"] = "llama_cpp"
    api_key: str | None = Field(default=None, max_length=2000)
    timeout_seconds: int = Field(default=120, ge=5, le=1800)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        u = urlsplit(value)
        if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError("Use uma URL HTTP(S) sem credenciais, parâmetros ou fragmentos.")
        try:
            _ = u.port
        except ValueError as exc:
            raise ValueError("Porta inválida.") from exc
        return value


class Settings(StrictModel):
    providers: list[Provider] = Field(default_factory=lambda: [Provider(id="local", name="llama.cpp local")], max_length=30)

    @model_validator(mode="after")
    def unique(self):
        if len({p.id for p in self.providers}) != len(self.providers):
            raise ValueError("IDs de provedores devem ser únicos.")
        return self


class InferenceConfig(StrictModel):
    pipeline: Literal["native_decision", "vision_json"] = "native_decision"
    provider_id: str = "local"
    model: str = Field(default="", max_length=250)
    grouping: Literal["individual", "together", "directory"] = "individual"
    video_group_size: int = Field(default=1, ge=1, le=16)
    instructions: str = Field(default="Answer each question using only the visual evidence. Treat uncertainty explicitly.", max_length=30000)
    context: str = Field(default="", max_length=30000)
    output_schema: dict[str, Any] = Field(default_factory=lambda: DEFAULT_SCHEMA.copy())
    decision_mode: Literal["auto", "tree", "greedy"] = "auto"
    tree_max: int = Field(default=128, ge=1, le=255)
    cache_prompt: bool = True
    batch_size: int = Field(default=8, ge=1, le=64)
    temperature: float = Field(default=0, ge=0, le=2)
    top_p: float = Field(default=1, gt=0, le=1)
    max_tokens: int = Field(default=512, ge=32, le=16384)
    seed: int | None = Field(default=42, ge=0, le=2147483647)
    image_max_side: int = Field(default=1280, ge=224, le=4096)
    jpeg_quality: int = Field(default=90, ge=40, le=100)
    video_mode: Literal["interval", "all"] = "interval"
    frame_interval: float = Field(default=2, ge=0.04, le=3600)
    max_frames: int = Field(default=120, ge=1, le=5000)
    start_seconds: float = Field(default=0, ge=0, le=86400)
    end_seconds: float | None = Field(default=None, gt=0, le=86400)
    review_threshold: float = Field(default=0.7, ge=0, le=1)

    @model_validator(mode="after")
    def ranges(self):
        if self.end_seconds is not None and self.end_seconds <= self.start_seconds:
            raise ValueError("O fim do vídeo deve ser posterior ao início.")
        return self


class JobRequest(StrictModel):
    name: str = Field(default="Nova execução", min_length=1, max_length=150)
    media_ids: list[str] = Field(min_length=1, max_length=500)
    config: InferenceConfig = Field(default_factory=InferenceConfig)


def validate_schema(schema: dict) -> dict:
    """Validate finite decisions before sending a paid/remote inference request."""
    if not schema or len(str(schema)) > 100000:
        raise ValueError("Defina uma estrutura de saída com até 100 KB.")
    props = schema.get("properties", schema)
    if not isinstance(props, dict) or not 1 <= len(props) <= 64:
        raise ValueError("Use entre 1 e 64 campos de decisão.")
    for name, f in props.items():
        if not name.strip() or not isinstance(f, dict):
            raise ValueError("Cada campo deve ter nome e objeto de configuração.")
        if not isinstance(f.get("description"), str) or not f["description"].strip():
            raise ValueError(f"{name}: escreva a pergunta no campo description.")
        choices = f.get("choices", f.get("enum"))
        kind = f.get("type")
        if choices is not None:
            if not isinstance(choices, list) or not 1 <= len(choices) <= 255 or any(not isinstance(x, str) or not x for x in choices) or len(set(choices)) != len(choices):
                raise ValueError(f"{name}: use 1–255 opções de texto únicas.")
        elif kind == "boolean":
            pass
        elif kind in {"integer", "number"}:
            low, high, step = f.get("minimum"), f.get("maximum"), f.get("step", f.get("multipleOf", 1 if kind == "integer" else None))
            if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in (low, high, step)) or step <= 0 or high < low:
                raise ValueError(f"{name}: defina mínimo, máximo e passo válidos.")
            if kind == "integer" and (int(low) != low or int(high) != high or step != 1):
                raise ValueError(f"{name}: integer requer limites inteiros e passo 1.")
            n = (high - low) / step
            if not math.isclose(n, round(n), abs_tol=1e-7) or not 0 <= n <= 254:
                raise ValueError(f"{name}: o intervalo precisa conter 1–255 valores exatos.")
            if f.get("aggregate", "mode") not in {"mode", "median", "mean"}:
                raise ValueError(f"{name}: aggregate deve ser mode, median ou mean.")
        else:
            raise ValueError(f"{name}: use enum, boolean, integer ou number limitado.")
    return schema


def to_json_schema(schema: dict) -> dict:
    props = schema.get("properties", schema)
    out = {}
    for name, f in props.items():
        p = {k: v for k, v in f.items() if k in {"description", "minimum", "maximum"}}
        if f.get("choices", f.get("enum")) is not None:
            p.update(type="string", enum=f.get("choices", f.get("enum")))
        else:
            p["type"] = f["type"]
            if f["type"] == "number":
                low, high, step = f["minimum"], f["maximum"], f.get("step", f.get("multipleOf"))
                p["enum"] = [round(low + i * step, 9) for i in range(round((high - low) / step) + 1)]
        out[name] = p
    return {"type": "object", "properties": out, "required": list(out), "additionalProperties": False}

# Native visual decisions

Extension of `/v1/decision` on the `codex/decision-vision` branch. Start `llama-server` with a vision GGUF, its compatible `--mmproj`, and `--decision-seqs N` (N >= 3). All media support comes from the existing mtmd implementation; this does not add vision to text-only models.

## Request

Existing string contexts work unchanged. A context can also be an object with an ordered `content` array of text and base64 JPEG/PNG image parts:

```json
{
  "instructions": "Answer using the visual evidence in the supplied order.",
  "schema": {
    "person_visible": {"type": "boolean", "description": "Is a person visible in any image?"},
    "visibility": {"type": "integer", "minimum": 0, "maximum": 4, "aggregate": "mean", "description": "Visibility, from 0 (unclear) to 4 (clear)."}
  },
  "contexts": [
    {"content": [
      {"type": "text", "text": "Image 1, camera A:"},
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}},
      {"type": "text", "text": "Image 2, camera B:"},
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
    ]}
  ],
  "mode": "tree",
  "return_distribution": true
}
```

This yields **one result conditioned on both images**. To evaluate images independently, put them in separate context objects. Mixed strings and visual objects are supported and results preserve context order. Content objects use the visual preparation path and therefore require mmproj even if an individual object contains text only. The Python example below produces a real payload:

```python
import base64, requests

def image(path):
    with open(path, 'rb') as f:
        return {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(f.read()).decode()}}

response = requests.post('http://localhost:8080/v1/decision', json={
    'contexts': [{'content': [{'type': 'text', 'text': 'Compare the two images.'}, image('a.png'), image('b.png')]}],
    'schema': {'different': {'type': 'boolean', 'description': 'Are the visible scenes different?'}},
    'mode': 'tree', 'return_distribution': True,
}, timeout=120)
response.raise_for_status()
print(response.json())
```

## Response additions

Existing `decision` and `fields` are preserved. With `return_distribution: true`:

- Tree fields include `distribution: [{"value": ..., "probability": ...}, ...]` in schema candidate order.
- Greedy fields return `distribution: null`; their existing `probability` remains the selected path score.
- Numeric tree fields include `expected_value`, independently of the selected aggregate. `aggregate: mean` still selects the nearest permitted grid value in `decision`; it does not silently change the output type.

Per-result usage adds `images` and `image_tokens`. Aggregate usage adds the same totals. `timings.vision_encode_ms` measures encoding **inside** `prefill_ms`, so it must not be added to `total_ms` again. Prefill includes prompt/media preparation and decoder work; scoring includes branch evaluation. `per_decision_ms` is an amortized batch measure.

`GET /v1/models` exposes `data[].decision` with `enabled`, `vision`, `version: 1`, limits and distribution support. These are server-declared capabilities, not a quality certification for a model.

## Implementation

The server reuses `oaicompat_chat_params_parse`, `process_mtmd_prompt`, `mtmd_encode_chunk` and `mtmd_helper_decode_image_chunk`. The engine receives prepared-context callbacks that prefill its reserved trunk sequence and return both logical `next_pos` and token count. The distinction matters for multimodal position encodings. Branch suffixes start at `next_pos`, not the image embedding count. The helper handles model-specific image positions and noncausal image attention.

Prepared contexts are processed one at a time within a request. The visual trunk KV is shared by the field branches; images are encoded once per context, not once per field. There is no cross-request visual cache in this version. Existing text prefix caching and text batching are retained. A sequence guard frees the engine's reserved pool after errors or cancellation without clearing ordinary chat slots.

Disconnects set a shared cancellation flag from the HTTP waiter. Prefill and branch batches check it; cancellation is cooperative and cannot interrupt a device kernel already running. The CLI API remains text-only.

## Bounds and supported transport

- 1–256 contexts, 1–64 fields, 1–255 candidates per field; `tree_max` 1–255.
- Up to 16 images per context, 64 images per request.
- JPEG/PNG data URLs only, up to 8 MiB each (including prefix/encoding), and 32 MiB JSON body.
- The effective image/token capacity depends on model, context window and available KV memory.
- Remote image URLs, filesystem paths, audio and raw video content are rejected. The client may sample a video into labeled frames and use multiple image parts.
- Invalid/corrupt media returns a client error. Decode/encoder resource failures remain server errors. A subsequent request can reuse the engine.

Validated with the tinygemma3 fixture on CPU; see [validation](../decision-studio/docs/VALIDATION.md). Large-image crops, M-RoPE/hybrid models, GPU execution and long-context memory exhaustion require model-specific validation. Using the standard helper is necessary but not sufficient evidence of compatibility with every architecture.

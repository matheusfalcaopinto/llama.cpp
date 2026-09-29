# Native visual decisions + Decision Studio

Personal fork branch `codex/decision-vision`, based on `thecodacus/llama.cpp:parallel-decision` at `ad129b08d9f134cd298d1f8a85efc52b1b66e18e`.

- [Decision Studio web application](tools/decision-studio/README.md): local/LAN image, directory and video inference; providers, typed output schemas, history and exports.
- [Native image API](tools/parallel-decision/README-vision.md): multi-image contexts at `/v1/decision` with constrained probabilities.
- [Validation and remaining limits](tools/decision-studio/docs/VALIDATION.md).

The server requires a supported vision GGUF and matching mmproj. Visual embeddings are prefetched once per context and shared across decision branches. No intermediate captioning model is used. Existing text contexts remain supported. No Jev/Laya integration.

The native CLI remains text-only; visual input is available through `llama-server` and Decision Studio. The current validated model is the tinygemma3 test fixture on Windows CPU, not a production-quality model or a complete architecture compatibility matrix.

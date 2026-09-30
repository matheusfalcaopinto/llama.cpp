# Native visual decisions + CAT Studio

Personal fork branch `codex/toll-cat`, derived from `codex/decision-vision`. The native server changes are based on `thecodacus/llama.cpp:parallel-decision` at `ad129b08d9f134cd298d1f8a85efc52b1b66e18e`.

- [CAT Studio web application](tools/decision-studio/README.md): local/LAN Brazilian toll vehicle categorization from images, batches, directories and sampled video frames.
- [CAT validation and limits](tools/decision-studio/docs/CAT_VALIDATION.md): versioned concession-specific tables, candidate probabilities, indeterminate decisions and review signals.
- [Native image API](tools/parallel-decision/README-vision.md): direct multi-image contexts at `/v1/decision` with constrained probabilities.

This branch specializes the client workflow. The native server is unchanged from `codex/decision-vision` and remains compatible with it. The generic client is available on that original branch.

A supported vision GGUF and matching mmproj are required. Image embeddings enter the model directly and are shared across decision fields. The application does not train or download a toll classifier, calculate charges, or claim validated vehicle-category accuracy. Categories depend on the selected concession table. Administrative exemptions cannot be verified by image alone.

The integration fixture is tinygemma3 on Windows CPU. Production model/GPU compatibility, category accuracy and score calibration require separate validation on representative annotated vehicle media.

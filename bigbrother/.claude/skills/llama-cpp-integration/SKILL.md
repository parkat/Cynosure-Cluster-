---
name: llama-cpp-integration
description: When loading models, calling llama.cpp APIs, or building against libllama.so.
---

# llama.cpp integration

## When this applies
- Any work in `src/compute/` that touches the model
- Building `libllama.so` or linking against it
- Bumping the `vendor/llama.cpp` submodule SHA

## Core invariants
1. **vendor/llama.cpp is read-only.** Never edit anything under it. The pre-tool-use hook blocks writes.
2. **One `llama_context*` per worker thread.** Contexts are not internally thread-safe. If you need parallel decode, you need multiple contexts (one per request stream).
3. **Models are loaded once per process.** `llama_model*` is shared across contexts. Loading is the expensive step (mmap of the GGUF).
4. **Build llama.cpp as a shared lib.** We need `BUILD_SHARED_LIBS=ON` to produce `libllama.so` and link our daemons against it. Static linking the GPU backend pulls in CUDA, ggml-cuda, etc. into every binary and balloons size.
5. **CUDA pinned at 12.6.** See ADR-003. Build llama.cpp with `-DGGML_CUDA=ON -DCMAKE_CUDA_COMPILER=/usr/local/cuda-12.6/bin/nvcc`.

## Key APIs (from include/llama.h)

```cpp
// Loading
llama_model* llama_model_load_from_file(const char* path, llama_model_params params);
void llama_model_free(llama_model* model);

// Contexts (one per concurrent request)
llama_context* llama_init_from_model(llama_model* model, llama_context_params ctx_params);
void llama_free(llama_context* ctx);

// Batched decode
int32_t llama_decode(llama_context* ctx, llama_batch batch);

// KV cache control (we'll lean on this for the ring)
void llama_kv_cache_clear(llama_context* ctx);
bool llama_kv_cache_seq_rm(llama_context* ctx, llama_seq_id seq, llama_pos p0, llama_pos p1);

// Tokenization
int32_t llama_tokenize(const llama_vocab* vocab, const char* text, int32_t text_len,
                       llama_token* tokens, int32_t n_tokens_max, bool add_special, bool parse_special);
```

The full API surface is in `vendor/llama.cpp/include/llama.h`. Read it before writing wrapper code.

## Build invocation

```bash
cmake -B vendor/llama.cpp/build vendor/llama.cpp \
  -DBUILD_SHARED_LIBS=ON \
  -DGGML_CUDA=ON \
  -DCMAKE_CUDA_ARCHITECTURES="60;61" \
  -DLLAMA_CURL=OFF \
  -DCMAKE_BUILD_TYPE=Release
cmake --build vendor/llama.cpp/build -j$(nproc)
```

`CMAKE_CUDA_ARCHITECTURES="60;61"` covers P100 (sm_60) and GTX 1060 (sm_61). Do not add 70+ or you'll silently break Pascal.

## Common mistakes
- Sharing a `llama_context*` across threads — it'll crash or corrupt KV cache silently.
- Calling `llama_decode` on a freed model — segfault.
- Forgetting `add_special=true` on the first tokenize — silently degrades quality.
- Building llama.cpp with `LLAMA_CURL=ON` — it'll pull libcurl as a runtime dep we don't need.
- Bumping CUDA past 12.6 — drops Pascal support, see ADR-003.

## Pinning policy
We track stable releases. Bump deliberately:
1. Read upstream changelog: https://github.com/ggml-org/llama.cpp/releases
2. Watch breakage tracker: https://github.com/ggml-org/llama.cpp/issues/9289
3. Bump submodule SHA, rebuild, run unit tests + single-node baseline
4. Append an ADR if the bump required wrapper changes

## References
- @ARCHITECTURE.md — compute layer placement
- @DECISIONS.md — ADR-001 (wrap not fork), ADR-003 (CUDA 12.6)
- https://github.com/ggml-org/llama.cpp
- https://github.com/ggml-org/llama.cpp/blob/master/include/llama.h

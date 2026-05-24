# Baseline targets per phase

| Phase | Deliverable | Success criterion |
|---|---|---|
| 1 | Single-node llama_wrapper | TinyLlama 1.1B Q4_0 generates 10 tokens via wrapper, no crash |
| 2 | Two-process ring (localhost) | 1000 dummy tensors ring-passed in order, no losses |
| 3 | Two-node static plan | Llama-3.2-1B Q4_K_M coherent text across 2 nodes |
| 4 | Halda solver | Halda's plan ≥ hand-written plan on Phase 3 test |
| 5 | Four-node 70B | Llama-3.3-70B Q4_K_M coherent text on 3-4 nodes |

**Foundation done = Phase 5 success criterion met.**

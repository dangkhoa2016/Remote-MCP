# Limitations

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](limitations.vi.md)

- The target runtime is Kaggle NVIDIA Tesla T4 ×2.
- The intended serving topology is two independent model replicas, not tensor sharding.
- The project does not claim that two GPUs are always exactly 2× faster than one GPU.
- Quick Demo corpus vectors are precomputed; user queries remain live.
- Full 100K rebuild requires the production-acceptance notebook and substantially more runtime.
- Search quality depends on corpus coverage as well as embedding quality.
- Optional external exposure is a temporary demonstration surface, not a permanent hosted SLA service.
- Runtime timings vary between Kaggle sessions.

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUAL = ROOT / "kaggle" / "demo.ipynb"
PROD = ROOT / "notebooks" / "kaggle-t4x2-production-demo.ipynb"

REPO_URL_MARKER = "https://github.com/dangkhoa2016/Qwen3-Embedding-8B-On-T4x2-GPU"

EXPECTED_MODEL_FP = "b41f597aceb7c52762877f2db5bf75504ee243e7382c21ef1608e07b41eb60da"
EXPECTED_DATASET_SHA = "1f69b4b64a0aecf41505aef3cf6fa5c5ce19e4a733d198765ee6f431beb711e9"

REQUIRED_EVIDENCE_FILES = [
    "environment.txt",
    "git-identity.txt",
    "dependency-versions.txt",
    "pip-list.json",
    "input-preflight.txt",
    "index-metadata.json",
    "index-build.log",
    "nvidia-smi-before.txt",
    "nvidia-smi-after.txt",
    "server.log",
    "startup-timing.json",
    "ready.json",
    "info-sanitized.json",
    "metrics.json",
    "embedding-en-summary.json",
    "embedding-vi-summary.json",
    "search-en.json",
    "search-vi.json",
    "cross-lingual-en-to-vi.json",
    "cross-lingual-vi-to-en.json",
    "concurrency-smoke.json",
    "public-tunnel-status.json",
    "teardown.json",
    "SHA256SUMS",
]


def load_nb(path: Path) -> dict:
    nb = json.loads(path.read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    assert isinstance(nb["cells"], list) and nb["cells"]
    return nb


def sources(nb: dict, cell_type: str | None = None) -> str:
    cells = nb["cells"]
    if cell_type is not None:
        cells = [c for c in cells if c["cell_type"] == cell_type]
    return "\n".join("".join(c.get("source", [])) for c in cells)


def md_cells(nb: dict) -> list[str]:
    return ["".join(c.get("source", [])) for c in nb["cells"] if c["cell_type"] == "markdown"]


def code_cells(nb: dict) -> list[str]:
    return ["".join(c.get("source", [])) for c in nb["cells"] if c["cell_type"] == "code"]


def assert_clean_committed_notebook(nb: dict) -> None:
    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            assert cell.get("execution_count") is None
            assert cell.get("outputs", []) == []


def test_both_notebooks_exist_and_are_valid_nbformat4():
    qual = load_nb(QUAL)
    prod = load_nb(PROD)
    assert_clean_committed_notebook(qual)
    assert_clean_committed_notebook(prod)


def test_both_notebooks_have_empty_outputs_and_no_execution_count():
    for path in (QUAL, PROD):
        nb = load_nb(path)
        for cell in nb["cells"]:
            if cell["cell_type"] == "code":
                assert cell.get("execution_count") is None
                assert cell.get("outputs", []) == []


def test_major_markdown_stages_are_bilingual():
    for path in (QUAL, PROD):
        nb = load_nb(path)
        stages = [md for md in md_cells(nb) if "## Stage" in md]
        assert len(stages) >= 3, path
        for md in stages:
            assert "**English:**" in md, (path, md[:120])
            assert "**Tiếng Việt:**" in md, (path, md[:120])


def test_banners_are_bilingual_and_state_role():
    qual_banner = md_cells(load_nb(QUAL))[0]
    prod_banner = md_cells(load_nb(PROD))[0]
    for banner in (qual_banner, prod_banner):
        assert "**English:**" in banner
        assert "**Tiếng Việt:**" in banner
    assert "VERIFY" in qual_banner
    assert "QUALIFICATION" in qual_banner
    assert "USE" in prod_banner
    assert "DEMO" in prod_banner
    assert "T4×2" in prod_banner


def test_both_notebooks_contain_official_repository_url():
    for path in (QUAL, PROD):
        text = sources(load_nb(path))
        assert REPO_URL_MARKER in text
        assert "git@github.com" not in text.split("Internet:")[0].replace("git clone git@:", "")


def test_both_notebooks_have_v100_ref_and_maintainer_override():
    for path in (QUAL, PROD):
        code = sources(load_nb(path), "code")
        assert 'REPO_REF = "v1.0.0"' in code
        assert "REPO_REF_OVERRIDE" in code
        assert 'REPO_REF_OVERRIDE.strip() or REPO_REF' in code
        assert 'REPO_REF_OVERRIDE = ""' in code


def test_both_notebooks_execute_exact_ref_fetch_checkout():
    for path in (QUAL, PROD):
        code = sources(load_nb(path), "code")
        assert "git" in code
        assert "fetch" in code
        assert "+refs/heads/*:refs/remotes/origin/*" in code
        assert "+refs/tags/*:refs/tags/*" in code
        assert "checkout" in code and "--detach" in code and "--force" in code
        assert "SELECTED_REF" in code


def test_both_notebooks_print_exact_head_and_require_clean_tree():
    for path in (QUAL, PROD):
        code = sources(load_nb(path), "code")
        assert "rev-parse" in code and "HEAD" in code
        assert "status" in code and "--porcelain" in code
        assert "dirty" in code


def test_qualification_links_to_production_and_says_verify():
    text = sources(load_nb(QUAL))
    assert "notebooks/kaggle-t4x2-production-demo.ipynb" in text
    assert "VERIFY" in text
    assert "QUALIFICATION" in text


def test_production_links_to_qualification_and_says_use_demo():
    text = sources(load_nb(PROD))
    assert "kaggle/demo.ipynb" in text
    assert "USE" in text or "use" in text
    assert "DEMO" in text


def test_production_hard_gates_at_least_two_cuda_devices():
    prod = load_nb(PROD)
    code = sources(prod, "code")
    assert "torch.cuda.is_available()" in code
    assert "torch.cuda.device_count()" in code
    assert "< 2" in code
    assert "Need T4×2" in code or "Need at least 2" in code
    md = sources(prod, "markdown")
    assert "T4×2" in md
    assert "2 T4" in md or "two T4" in md


def test_production_validates_canonical_100k_metadata():
    prod = load_nb(PROD)
    code = sources(prod, "code")
    assert "100000" in code
    assert "4096" in code
    assert EXPECTED_MODEL_FP in code
    assert EXPECTED_DATASET_SHA in code
    assert "row_count" in code
    assert "dimensions" in code
    assert "dataset_sha256" in code
    assert "model_fingerprint" in code


def test_production_markdown_forbids_reduced_corpus():
    prod = load_nb(PROD)
    md = sources(prod, "markdown")
    assert "never reduce" in md or "reduced corpus is forbidden" in md or "no --limit" in md


def test_production_has_no_corpus_limit_in_code():
    nb = load_nb(PROD)
    code = sources(nb, "code")
    assert "DEMO_CORPUS_LIMIT" not in code
    assert "--limit" not in code


def test_production_api_key_created_under_kaggle_working_not_input():
    prod = load_nb(PROD)
    for cell in code_cells(prod):
        if "API_KEY_FILE" in cell and "token_urlsafe" in cell:
            assert "/kaggle/input" not in cell
            break
    else:
        raise AssertionError("API key creation cell not found")
    code = sources(prod, "code")
    assert "secrets" in code
    assert "api-key" in code
    assert "secrets.token_urlsafe(32)" in code
    assert "0o600" in code


def test_production_service_uses_single_uvicorn_parent_via_run_demo():
    prod = load_nb(PROD)
    code = sources(prod, "code")
    assert "WORKER_COUNT=2" in code or "WORKER_COUNT': '2'" in code or '"WORKER_COUNT", "2"' in code or "WORKER_COUNT='2'" in code
    assert "MAX_BATCH_ESTIMATED_TOKENS=512" in code or "'MAX_BATCH_ESTIMATED_TOKENS': '512'" in code or '"MAX_BATCH_ESTIMATED_TOKENS", "512"' in code
    assert "EXPOSE_MODE=off" in code or "'EXPOSE_MODE': 'off'" in code or '"EXPOSE_MODE", "off"' in code
    assert "kaggle/run-demo.sh" in code
    assert "--workers 1" in code or "workers 1" in code


def test_production_readiness_matrix_health_ready():
    prod = load_nb(PROD)
    code = sources(prod, "code")
    assert "/health" in code
    assert "/ready" in code
    assert "200" in code
    assert "401" in code
    assert "Bearer" in code


def test_production_covers_authenticated_infon_metrics_embeddings_search():
    prod = load_nb(PROD)
    code = sources(prod, "code")
    for endpoint in ("/info", "/metrics", "/v1/embeddings", "/v1/search"):
        assert endpoint in code


def test_production_bilingual_unicode_examples():
    prod = load_nb(PROD)
    code = sources(prod, "code")
    assert any(ch in code for ch in "ếịầĐơư")
    assert "language" in code and '"en"' in code
    assert '"vi"' in code
    assert any(word in code for word in ("thủ đô", "Tổng thống", "trí tuệ nhân tạo", "dân chủ", "thành phố Hà Nội", "Hà Nội"))


def test_production_has_both_cross_lingual_demo_sections():
    prod = load_nb(PROD)
    md = sources(prod, "markdown")
    assert "EN→VI" in md
    assert "VI→EN" in md


def test_production_bounded_concurrency_smoke_contract():
    prod = load_nb(PROD)
    code = sources(prod, "code")
    assert "CONCURRENCY" in code
    assert "concurrency" in code or "ThreadPoolExecutor" in code
    assert "unexpected_5xx" in code or "5xx" in code
    assert "finite" in code
    assert "batches_per_worker" in code or "worker_batches" in code


def test_production_tunnel_disabled_default():
    prod = load_nb(PROD)
    code = sources(prod, "code")
    assert "ENABLE_PUBLIC_TUNNEL = False" in code


def test_production_evidence_stage_references_all_required_filenames():
    prod = load_nb(PROD)
    text = sources(prod)
    for name in REQUIRED_EVIDENCE_FILES:
        assert name in text, name


def test_production_teardown_terminates_service_and_verifies_no_process():
    prod = load_nb(PROD)
    code = sources(prod, "code")
    assert "teardown" in code or "TEARDOWN" in code
    assert "terminate" in code or "kill" in code or "SIGTERM" in code or "terminate()" in code
    assert "no project process" in code or "no process" in code
    assert "teardown.json" in code


PYTEST_EXEC_RE = re.compile(
    r"subprocess\.run\(\s*\[\s*sys\.executable\s*,\s*['\"]-m['\"]\s*,\s*['\"]pytest['\"]\s*,\s*['\"]-q['\"]"
)

QUAL_BOOTSTRAP_INVOCATION = "bootstrap_and_adopt_environment(PROJECT_ROOT)"
PROD_BOOTSTRAP_INVOCATION = "BOOTSTRAP_ENV = bootstrap_and_adopt_environment(PROJECT_ROOT)"


def code_positions(nb: dict) -> list[tuple[int, str]]:
    return [
        (i, "".join(c.get("source", [])))
        for i, c in enumerate(nb["cells"])
        if c["cell_type"] == "code"
    ]


def find_pytest_executions(nb: dict) -> list[tuple[int, int]]:
    hits = []
    for i, src in code_positions(nb):
        match = PYTEST_EXEC_RE.search(src)
        if match is not None:
            hits.append((i, match.start()))
    assert hits, "actual full `python -m pytest -q` execution missing"
    return hits


def assert_execution_before(early: list[tuple[int, int]], late: list[tuple[int, int]], msg: str) -> None:
    assert early, f"{msg}: earlier statement not found"
    assert late, f"{msg}: later statement not found"
    early_i, early_pos = min(early)
    late_i, late_pos = min(late)
    if early_i != late_i:
        assert early_i < late_i, msg
    else:
        assert early_pos < late_pos, msg


def test_qualification_actual_bootstrap_invocation_before_pytest():
    nb = load_nb(QUAL)
    cells = code_positions(nb)
    code = "\n".join(src for _, src in cells)

    assert "kaggle/bootstrap.sh" in code
    assert "env -0" in code
    assert "os.environ" in code
    assert "PATH" in code
    assert "PYTHONPATH" in code
    assert "LD_LIBRARY_PATH" in code

    assert 'subprocess.run(["bash", "kaggle/bootstrap.sh"], check=True)' not in code
    assert "subprocess.run(['bash', 'kaggle/bootstrap.sh'], check=True)" not in code

    invocations = [
        (i, src.index(QUAL_BOOTSTRAP_INVOCATION))
        for i, src in cells
        if QUAL_BOOTSTRAP_INVOCATION in src
    ]
    assert invocations, "qualification actual bootstrap_and_adopt_environment(PROJECT_ROOT) invocation cell missing"
    pytest_hits = find_pytest_executions(nb)
    assert_execution_before(
        invocations,
        pytest_hits,
        "actual bootstrap/adopt invocation must precede actual full pytest execution (not helper-definition order)",
    )


def test_qualification_has_no_direct_stage0_nvidia_smi_after_bootstrap():
    nb = load_nb(QUAL)
    cells = code_positions(nb)
    code = "\n".join(src for _, src in cells)

    stage0_markers = [
        "subprocess.run(['nvidia-smi', '--query-gpu=index,name,memory.total', '--format=csv'], check=True)",
        'subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv"], check=True)',
        'nvidia-smi', '--query-gpu=index,name,memory.total', '--format=csv',
    ]
    exact_hits = [m for m in stage0_markers[:2] if m in code]
    assert not exact_hits, "qualification still has a direct Stage-0 nvidia-smi subprocess after bootstrap"

    invocations = [
        (i, src.index(QUAL_BOOTSTRAP_INVOCATION))
        for i, src in cells
        if QUAL_BOOTSTRAP_INVOCATION in src
    ]
    assert invocations, "qualification actual bootstrap invocation cell missing"
    pytest_hits = find_pytest_executions(nb)
    assert_execution_before(
        invocations,
        pytest_hits,
        "actual bootstrap invocation must precede actual full pytest execution",
    )


def test_production_actual_bootstrap_invocation_before_gpu_preflight():
    nb = load_nb(PROD)
    cells = code_positions(nb)
    code = "\n".join(src for _, src in cells)

    assert "kaggle/bootstrap.sh" in code
    assert "env -0" in code
    assert "os.environ" in code
    assert "PYTHONPATH" in code
    assert "LD_LIBRARY_PATH" in code

    invocations = [
        (i, src.index(PROD_BOOTSTRAP_INVOCATION))
        for i, src in cells
        if PROD_BOOTSTRAP_INVOCATION in src
    ]
    assert invocations, "production actual BOOTSTRAP_ENV = bootstrap_and_adopt_environment(PROJECT_ROOT) cell missing"
    preflights = [
        (i, src.index("torch.cuda.is_available()"))
        for i, src in cells
        if "torch.cuda.is_available()" in src and "torch.cuda.device_count()" in src
    ]
    assert preflights, "production actual Stage-1 GPU/Torch preflight cell missing"

    assert_execution_before(
        invocations,
        preflights,
        "actual BOOTSTRAP_ENV assignment/invocation must precede actual GPU/Torch preflight execution (not helper-definition order)",
    )


def test_production_stage2_doc_matches_stage0_bootstrap_architecture():
    nb = load_nb(PROD)
    stages = [
        "".join(c.get("source", []))
        for c in nb["cells"]
        if c["cell_type"] == "markdown" and "## Stage 2" in "".join(c.get("source", []))
    ]
    assert len(stages) == 1, "exactly one Stage 2 markdown cell required"

    text = stages[0]
    assert "**English:**" in text
    assert "**Tiếng Việt:**" in text

    for phrase, label in (
        ("Bootstrap already ran in Stage 0", "bootstrap already ran in Stage 0"),
        ("adopted", "environment adopted into notebook process"),
        ("Stage-1 GPU preflight", "adoption before the Stage-1 GPU preflight"),
        ("PATH", "PATH export adopted"),
        ("LD_LIBRARY_PATH", "LD_LIBRARY_PATH export adopted"),
        ("a second time", "Stage 2 does not run bootstrap a second time"),
    ):
        assert phrase in text, label



def test_qualification_stage3_selects_only_evidence_directories():
    nb = load_nb(QUAL)
    code = sources(nb, "code")

    assert "QUAL_WORK.glob" in code
    assert "qualification-*" in code
    assert "p.is_dir()" in code
    assert "qualification-console.log" not in code
    assert "if not QUAL_DIRS" in code
    assert "QUAL_DIR = QUAL_DIRS[-1]" in code


def test_bootstrap_authority_static_contract():
    boot = (ROOT / "kaggle" / "bootstrap.sh").read_text(encoding="utf-8")

    for marker in (
        "/opt/bin",
        "/opt/nvidia/bin",
        "/usr/local/nvidia/lib64",
        "command -v nvidia-smi",
        "GPU_COUNT",
        "GPU_COUNT < 2",
    ):
        assert marker in boot, marker

    path_i = min(boot.index("/opt/bin"), boot.index("/opt/nvidia/bin"))
    nvidia_i = boot.index("command -v nvidia-smi")
    assert path_i < nvidia_i


def test_qualification_python_code_cells_compile():
    nb = load_nb(QUAL)
    failures = []
    for index, cell in enumerate(nb["cells"]):
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell.get("source", []))
        try:
            compile(source, f"{QUAL.name}:cell-{index}", "exec")
        except SyntaxError as exc:
            failures.append(
                f"cell {index}: {exc.msg} at line {exc.lineno}\n{source}"
            )
    assert not failures, "invalid Python notebook code cells:\n" + "\n\n".join(failures)


def test_production_concurrency_metrics_uses_json_string_worker_keys():
    prod = load_nb(PROD)
    code = sources(prod, "code")
    assert "smoke_batches = smoke_metrics.get('batches_per_worker', {})" in code
    assert "'0' in smoke_batches" in code
    assert "'1' in smoke_batches" in code


def test_production_final_evidence_inventory_assertion_follows_artifact_generation():
    nb = load_nb(PROD)
    cells = code_cells(nb)

    def cell_index_containing(marker: str) -> int:
        hits = [i for i, src in enumerate(cells) if marker in src]
        assert hits, f"production notebook cell missing marker: {marker}"
        return hits[-1]

    final_assert_i = cell_index_containing("assert not missing, f'missing evidence files: {missing}'")
    required_generation_markers = (
        "EVIDENCE_DIR / 'dependency-versions.txt'",
        "EVIDENCE_DIR / 'pip-list.json'",
        "EVIDENCE_DIR / 'server.log'",
        "EVIDENCE_DIR / 'index-build.log'",
        "EVIDENCE_DIR / 'teardown.json'",
        "EVIDENCE_DIR / 'SHA256SUMS'",
    )

    for marker in required_generation_markers:
        assert cell_index_containing(marker) < final_assert_i, (
            marker,
            "final required-evidence assertion must follow every required artifact-generation cell",
        )

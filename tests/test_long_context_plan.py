def test_long_context_targets_are_ascending_and_keep_4k_default_separate():
    from app.qualification.long_context import TARGETS, next_targets_after_results
    assert TARGETS == (4096, 8192, 16384, 24576, 32768)
    assert next_targets_after_results([{'target_tokens': 8192, 'status': 'OOM'}]) == ()


def test_next_targets_continue_only_after_pass():
    from app.qualification.long_context import next_targets_after_results
    assert next_targets_after_results([{'target_tokens': 4096, 'status': 'PASS'}]) == (8192, 16384, 24576, 32768)
    assert next_targets_after_results([{'target_tokens': 4096, 'status': 'ERROR'}]) == ()


def test_normal_service_default_remains_4096():
    from app.config import Settings
    assert Settings().max_sequence_tokens == 4096


def test_oom_at_8192_stops_actual_escalation():
    from app.qualification.long_context import next_targets_after_results
    assert next_targets_after_results([
        {"target_tokens": 4096, "status": "PASS"},
        {"target_tokens": 8192, "status": "OOM"},
    ]) == ()


def test_materialize_final_results_marks_skipped_targets_not_run_after_oom():
    from app.qualification.long_context import materialize_final_results
    statuses = {
        row["target_tokens"]: row["status"]
        for row in materialize_final_results(
            targets=(4096, 8192, 16384, 24576, 32768),
            executed=[
                {"target_tokens": 4096, "status": "PASS"},
                {"target_tokens": 8192, "status": "OOM"},
            ],
        )
    }
    assert statuses == {
        4096: "PASS",
        8192: "OOM",
        16384: "NOT_RUN_AFTER_OOM",
        24576: "NOT_RUN_AFTER_OOM",
        32768: "NOT_RUN_AFTER_OOM",
    }


def test_only_first_failed_target_carries_oom():
    from app.qualification.long_context import materialize_final_results
    rows = materialize_final_results(
        targets=(4096, 8192, 16384),
        executed=[
            {"target_tokens": 4096, "status": "PASS"},
            {"target_tokens": 8192, "status": "OOM"},
        ],
    )
    oom_rows = [r for r in rows if r["status"] == "OOM"]
    assert [r["target_tokens"] for r in oom_rows] == [8192]


def test_materialize_final_results_skipped_rows_have_no_fake_metrics():
    from app.qualification.long_context import materialize_final_results
    rows = materialize_final_results(
        targets=(4096, 8192, 16384, 24576, 32768),
        executed=[
            {"target_tokens": 4096, "status": "PASS"},
            {"target_tokens": 8192, "status": "OOM"},
        ],
    )
    skipped = [r for r in rows if r["status"] == "NOT_RUN_AFTER_OOM"]
    assert len(skipped) == 3
    for row in skipped:
        assert "actual_tokens" not in row
        assert "latency_seconds" not in row
        assert "cuda_max_allocated_bytes" not in row
        assert "cuda_max_reserved_bytes" not in row
        assert row["blocked_by_target_tokens"] == 8192

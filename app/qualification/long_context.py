from __future__ import annotations

from collections.abc import Sequence

TARGETS = (4096, 8192, 16384, 24576, 32768)


def should_continue(status: str) -> bool:
    return status == 'PASS'


def next_targets_after_results(results: Sequence[dict]) -> tuple[int, ...]:
    if not results:
        return TARGETS
    last = results[-1]
    if not should_continue(str(last.get('status'))):
        return ()
    attempted = {int(item['target_tokens']) for item in results if 'target_tokens' in item}
    return tuple(target for target in TARGETS if target not in attempted and target > max(attempted, default=0))


def materialize_final_results(targets: Sequence[int], executed: Sequence[dict]) -> list[dict]:
    """Materialize every configured target, truthfully classifying each.

    Executed targets keep their measured records. Any target that was never
    actually attempted because an earlier target stopped escalation is reported
    as NOT_RUN_AFTER_OOM pointing at the blocking target. A skipped target is
    never reported as OOM and carries no fabricated metrics.
    """
    by_target = {int(row['target_tokens']): row for row in executed}
    final: list[dict] = []
    blocked_by: int | None = None
    for target in targets:
        record = by_target.get(int(target))
        if record is not None:
            final.append(record)
            if blocked_by is None and str(record.get('status')) != 'PASS':
                blocked_by = int(record['target_tokens'])
        elif blocked_by is not None:
            final.append({
                'target_tokens': int(target),
                'status': 'NOT_RUN_AFTER_OOM',
                'blocked_by_target_tokens': blocked_by,
            })
    return final

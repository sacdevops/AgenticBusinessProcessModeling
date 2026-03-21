"""Task-level statistics tracker.

One tracker entry is created per session (task_id + session_id).
Records: wall-clock duration, LLM interaction counts per agent, token usage per agent.
A Markdown report is written to data/task_stats/ when the task is completed.
"""

import os
from datetime import datetime
from typing import Dict, Any


_BASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'task_stats'
)

# Keyed by task_id → tracking dict
_state: Dict[str, Dict[str, Any]] = {}


def start_task(task_id: str, session_id: str) -> None:
    """Initialize tracking for a task session. Safe to call multiple times — no-op if already started."""
    if task_id in _state:
        return
    _state[task_id] = {
        'session_id': session_id,
        'started_at': datetime.now(),
        'finished_at': None,
        'interactions': {'Supervisor': 0, 'Worker': 0},
        'tokens_in':    {'Supervisor': 0, 'Worker': 0},
        'tokens_out':   {'Supervisor': 0, 'Worker': 0},
    }
    print(f'[TaskTracker] Started tracking task {task_id} (session {session_id})')


def record_llm_call(
    task_id: str,
    ai_type: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """Record one LLM API call with its token usage."""
    if task_id not in _state:
        return
    s = _state[task_id]
    agent = ai_type if ai_type in ('Supervisor', 'Worker') else 'Supervisor'
    s['interactions'][agent] += 1
    s['tokens_in'][agent]    += prompt_tokens
    s['tokens_out'][agent]   += completion_tokens


def _write_report(task_id: str, s: dict, bpmn_xml: str = '') -> None:
    """Write Markdown report and optional BPMN into the task subfolder (overwrites)."""
    session_id = s.get('session_id', 'unknown')
    started    = s['started_at']
    finished   = s.get('finished_at', datetime.now())
    duration   = finished - started

    duration_str = f'{duration.total_seconds():.2f}s'

    sup_in  = s['tokens_in'].get('Supervisor', 0)
    sup_out = s['tokens_out'].get('Supervisor', 0)
    wor_in  = s['tokens_in'].get('Worker', 0)
    wor_out = s['tokens_out'].get('Worker', 0)
    sup_ia  = s['interactions'].get('Supervisor', 0)
    wor_ia  = s['interactions'].get('Worker', 0)

    total_in  = sup_in  + wor_in
    total_out = sup_out + wor_out
    total_tok = total_in + total_out
    total_ia  = sup_ia  + wor_ia

    report = f"""\
# Task Report: {task_id}

**Session ID:** `{session_id}`

---

## Timing

| | |
|---|---|
| Started             | {started.strftime('%Y-%m-%d %H:%M:%S')} |
| Supervisor finished | {finished.strftime('%Y-%m-%d %H:%M:%S')} |
| Duration            | {duration_str} |

---

## LLM Interactions

| Agent | Interactions |
|---|---|
| Supervisor | {sup_ia} |
| Worker | {wor_ia} |
| **Total** | **{total_ia}** |

---

## Token Usage

| Agent | Input Tokens | Output Tokens | Total |
|---|---|---|---|
| Supervisor | {sup_in:,} | {sup_out:,} | {sup_in + sup_out:,} |
| Worker | {wor_in:,} | {wor_out:,} | {wor_in + wor_out:,} |
| **Total** | **{total_in:,}** | **{total_out:,}** | **{total_tok:,}** |
"""

    folder_name = f'{task_id}_{session_id}'
    out_dir = os.path.join(_BASE_DIR, folder_name)
    os.makedirs(out_dir, exist_ok=True)

    md_path = os.path.join(out_dir, f'{folder_name}.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f'[TaskTracker] Report saved → {md_path}')

    if bpmn_xml:
        bpmn_path = os.path.join(out_dir, f'{folder_name}.bpmn')
        with open(bpmn_path, 'w', encoding='utf-8') as f:
            f.write(bpmn_xml)
        print(f'[TaskTracker] BPMN saved  → {bpmn_path}')


def snapshot_task(task_id: str, bpmn_xml: str = '') -> None:
    """Record the moment the Supervisor hands back to the user.

    Sets finished_at to now and writes the report + BPMN snapshot without
    removing the tracking state, so subsequent interactions keep accumulating.
    Each call overwrites the previous snapshot in the same subfolder.
    """
    if task_id not in _state:
        return
    _state[task_id]['finished_at'] = datetime.now()
    _write_report(task_id, _state[task_id], bpmn_xml)
    print(f'[TaskTracker] Snapshot written for task {task_id}')


def save_task_report(task_id: str, bpmn_xml: str = '') -> None:
    """Write a final report + BPMN and remove tracking state (called on explicit save)."""
    if task_id not in _state:
        return
    _state[task_id]['finished_at'] = datetime.now()
    _write_report(task_id, _state[task_id], bpmn_xml)
    _state.pop(task_id)
    print(f'[TaskTracker] Final report written for task {task_id}')


def cleanup_task(task_id: str) -> None:
    """Discard tracking state without saving (e.g. on unexpected disconnect)."""
    if _state.pop(task_id, None) is not None:
        print(f'[TaskTracker] Discarded tracking for task {task_id} (no report written)')

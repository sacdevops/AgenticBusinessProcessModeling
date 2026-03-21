from flask_socketio import emit, join_room
from app.ai_service import AIService
from app import task_tracker
import config
import traceback
import uuid

chat_histories = {}
active_sessions = {}
stopped_tasks = set()
custom_task_descriptions = {}

# Worker-only orchestration state
# orch_phase values: PLAN | EXECUTING | REVIEWING | AWAITING_USER
agent_orchestrators = {}

_FALLBACK_GREETING = (
    "Hello! I'm your BPMN Modeling Agent. "
    "I'll analyze the task, create a plan, and build the diagram autonomously. Let me get started."
)
_INITIAL_GREETING_SIGNAL = '[INITIAL_GREETING]'

def register_handlers(socketio):

    @socketio.on('connect')
    def handle_connect():
        emit('connected', {'status': 'connected'})
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Clean up session data when a client disconnects."""
        tasks_to_clean = list(active_sessions.keys())

        for task_id in tasks_to_clean:
            task_tracker.cleanup_task(task_id)
            active_sessions.pop(task_id, None)
            chat_histories.pop(task_id, None)
            stopped_tasks.discard(task_id)
            agent_orchestrators.pop(task_id, None)
            print(f'[Backend] Cleaned up session for task {task_id} on disconnect')
    
    @socketio.on('stop_ai')
    def handle_stop_ai(data):
        task_id = data.get('task_id')
        if task_id:
            stopped_tasks.add(task_id)
    
    @socketio.on('join_task')
    def handle_join_task(data):
        task_id = data.get('task_id')

        is_valid = isinstance(task_id, str) and (
            task_id == 'custom' or task_id in config.TASKS_BY_ID
        )
        if not is_valid:
            return

        if task_id:
            join_room(task_id)
            if task_id not in chat_histories:
                chat_histories[task_id] = []

            if task_id not in active_sessions:
                active_sessions[task_id] = str(uuid.uuid4())[:8]
                task_tracker.start_task(task_id, active_sessions[task_id])
            
            emit('task_joined', {'task_id': task_id})

    @socketio.on('set_custom_task')
    def handle_set_custom_task(data):
        task_id = data.get('task_id')
        description = data.get('description', '')
        if isinstance(task_id, str) and task_id == 'custom' and isinstance(description, str):
            custom_task_descriptions[task_id] = description
    
    @socketio.on('send_message')
    def handle_send_message(data):
        task_id = data.get('task_id')
        message = data.get('message')
        current_bpmn = data.get('bpmn_xml', '')

        if not isinstance(task_id, str) or not task_id:
            return
        if not isinstance(message, str) or not message:
            return
        if task_id != 'custom' and task_id not in config.TASKS_BY_ID:
            return

        if task_id in stopped_tasks:
            stopped_tasks.discard(task_id)

        if task_id not in chat_histories:
            chat_histories[task_id] = []

        emit('ai_typing', {'typing': True})

        if task_id == 'custom':
            task_description = custom_task_descriptions.get(task_id, '')
        else:
            task = config.TASKS_BY_ID.get(task_id)
            task_description = task['description'] if task else ''
        session_id = active_sessions.get(task_id, '')

        is_initial_greeting = message == _INITIAL_GREETING_SIGNAL

        # Remove the greeting signal from chat history (system trigger, not real user text)
        if is_initial_greeting:
            if chat_histories[task_id] and chat_histories[task_id][-1]['message'] == _INITIAL_GREETING_SIGNAL:
                chat_histories[task_id].pop()
        else:
            chat_histories[task_id].append({'sender': 'user', 'message': message})

        # Initialise orchestrator state
        if task_id not in agent_orchestrators:
            agent_orchestrators[task_id] = {
                'orch_phase': 'PLAN',
                'goals': [],
                'worker_iteration': 0,
                'worker_memory': [],
                'last_issues': [],
            }
        state = agent_orchestrators[task_id]
        worker = AIService('Worker', task_id, session_id=session_id)

        # ── Initial greeting ──────────────────────────────────────────────────
        if is_initial_greeting:
            try:
                result = worker.generate_worker_greeting(task_description)
                greeting = result.get('message', _FALLBACK_GREETING)
            except Exception as e:
                print(f"[Worker] Greeting error: {e}")
                greeting = _FALLBACK_GREETING

            chat_histories[task_id].append({'sender': 'ai', 'message': greeting})
            state['worker_memory'].append({'role': 'assistant', 'content': greeting})

            emit('ai_response', {
                'sender': 'ai',
                'message': greeting,
                'actions': [],
                'complete': False,
                'phase': 'GREETING',
                'plan': [],
                'await_feedback': False,
            })
            emit('ai_typing', {'typing': False})

            if task_id not in stopped_tasks:
                emit('agent_iterating', {'phase': 'GREETING', 'complete': False})
            return

        # ── Regular user message — Worker handles it ──────────────────────────
        state['worker_memory'].append({'role': 'user', 'content': message})
        state['last_user_message'] = message

        orch_phase = state.get('orch_phase', 'AWAITING_USER')

        if orch_phase == 'AWAITING_USER':
            instruction = (
                'The user has sent a message. React to it: '
                'if they want changes or corrections to the model, use PLAN phase to define new goals. '
                'If they are asking a question about the task, BPMN, the current model, or any domain topic, use ANSWER phase to answer directly — do NOT plan or trigger modeling. '
                'If they are satisfied or making a general comment, respond with FEEDBACK phase. '
                'If they want to finalize, set complete: true in FEEDBACK phase.'
            )
        else:
            instruction = (
                'The user sent a message while modeling is in progress. Acknowledge briefly in FEEDBACK '
                'phase and explain that you are still working. Use FEEDBACK phase.'
            )

        try:
            response = worker.get_planning_response(
                task_description, instruction, state['worker_memory'],
                current_bpmn, user_message=message
            )
            resp_phase = response.get('phase', 'FEEDBACK')
            resp_message = response.get('message', '')
            goals = response.get('goals', [])
            is_complete = response.get('complete', False)

            if resp_message:
                state['worker_memory'].append({'role': 'assistant', 'content': resp_message})
                chat_histories[task_id].append({'sender': 'ai', 'message': resp_message})

            if resp_phase == 'PLAN' and goals:
                state['goals'] = goals
                state['worker_iteration'] = 0
                state['orch_phase'] = 'EXECUTING'

            emit('ai_response', {
                'sender': 'ai',
                'message': resp_message,
                'actions': [],
                'complete': is_complete,
                'phase': resp_phase,
                'goals': goals,
                'await_feedback': resp_phase in ('FEEDBACK', 'ANSWER'),
            })

            if goals and resp_phase == 'PLAN':
                emit('agent_plan_update', {
                    'plan': [{'id': g['id'], 'label': g.get('title', ''), 'status': 'pending'} for g in goals],
                    'phase': 'PLAN',
                    'step': None,
                    'step_status': None,
                })

            emit('ai_typing', {'typing': False})

            if resp_phase == 'PLAN' and goals and task_id not in stopped_tasks:
                emit('agent_iterating', {'phase': 'PLAN', 'complete': False})

        except Exception as e:
            print(f"[Worker] send_message error: {e}")
            emit('ai_typing', {'typing': False})
            emit('error', {'message': 'An unexpected error occurred. Please try again.'})
        return
    
    @socketio.on('request_completion')
    def handle_request_completion(data):
        task_id = data.get('task_id')

        is_valid = isinstance(task_id, str) and (
            task_id == 'custom' or task_id in config.TASKS_BY_ID
        )
        if not is_valid:
            return

        state = agent_orchestrators.get(task_id, {})
        last_issues = state.get('last_issues', [])
        blocking = [i for i in last_issues if i.get('severity') in ('critical', 'warning')]

        if not blocking:
            emit('completion_review_result', {
                'task_id': task_id,
                'has_issues': False,
                'issues': [i for i in last_issues if i.get('severity') == 'info'],
                'message': 'The model has been reviewed and is ready for completion.'
            })
        else:
            blocking_summary = '; '.join(i.get('shortDesc', '') for i in blocking[:3])
            emit('completion_review_result', {
                'task_id': task_id,
                'has_issues': True,
                'issues': last_issues,
                'message': f'The review found {len(blocking)} issue(s): {blocking_summary}. Please address them or confirm completion anyway.'
            })
    
    @socketio.on('clear_chat')
    def handle_clear_chat(data):
        task_id = data.get('task_id')
        if task_id and task_id in chat_histories:
            chat_histories[task_id] = []
            agent_orchestrators.pop(task_id, None)
            emit('chat_cleared', {'task_id': task_id})

    @socketio.on('ignore_issue')
    def handle_ignore_issue(data):
        """Remove a single issue from the orchestrator state so the AI no longer considers it."""
        task_id = data.get('task_id')
        issue_index = data.get('issue_index')
        if not isinstance(task_id, str) or issue_index is None:
            return
        state = agent_orchestrators.get(task_id)
        if state and isinstance(issue_index, int):
            last_issues = state.get('last_issues', [])
            if 0 <= issue_index < len(last_issues):
                removed = last_issues.pop(issue_index)
                print(f"[Orchestrator] Issue ignored: {removed.get('shortDesc', '?')}")

    @socketio.on('fix_issue')
    def handle_fix_issue(data):
        """Have the Worker fix one specific issue without touching the rest of the model."""
        task_id = data.get('task_id')
        issue = data.get('issue', {})
        current_bpmn = data.get('bpmn_xml', '')

        is_valid = isinstance(task_id, str) and (
            task_id == 'custom' or task_id in config.TASKS_BY_ID
        )
        if not is_valid or not issue:
            return
        if task_id in stopped_tasks:
            return

        if task_id == 'custom':
            task_description = custom_task_descriptions.get(task_id, '')
        else:
            task = config.TASKS_BY_ID.get(task_id)
            task_description = task['description'] if task else ''
        session_id = active_sessions.get(task_id, '')

        state = agent_orchestrators.get(task_id, {})

        # Build a single targeted goal from the issue
        element_id = issue.get('elementId', '?')
        short_desc = issue.get('shortDesc', 'Fix reported issue')
        long_desc = issue.get('longDesc', short_desc)

        targeted_goal = {
            'id': 1,
            'title': f'Fix: {short_desc[:40]}',
            'details': (
                f'Fix ONLY this specific issue on element "{element_id}": {long_desc} '
                f'Do NOT change any other elements. Use done: true after making the fix.'
            ),
        }

        worker = AIService('Worker', task_id, session_id=session_id)
        try:
            resp = worker.get_worker_response(
                task_description,
                [targeted_goal],
                current_bpmn,
                user_message=(
                    f'Fix only this issue: [{issue.get("severity", "warning").upper()}] '
                    f'{short_desc} — {long_desc}. '
                    f'Affected element: {element_id}. Do not touch anything else.'
                ),
                iteration=1,
            )
            message = resp.get('message', '')
            actions = resp.get('actions', [])

            # Remove the fixed issue from state so the AI forgets it
            last_issues = state.get('last_issues', [])
            state['last_issues'] = [
                i for i in last_issues
                if not (i.get('elementId') == element_id and i.get('shortDesc') == short_desc)
            ]

            if message:
                chat_histories.setdefault(task_id, []).append({'sender': 'ai', 'message': message})
                state.setdefault('worker_memory', []).append({'role': 'assistant', 'content': message})

            emit('fix_issue_result', {
                'message': message,
                'actions': actions,
                'issue': issue,
            })

        except Exception as e:
            print(f"[fix_issue] Error: {e}")
            traceback.print_exc()
            emit('fix_issue_result', {'message': f'Error while fixing: {e}', 'actions': [], 'issue': issue})

    @socketio.on('agent_continue')
    def handle_agent_continue(data):
        """Drive the Worker-only orchestration loop: PLAN → EXECUTING → REVIEWING → AWAITING_USER."""
        task_id = data.get('task_id')
        current_bpmn = data.get('bpmn_xml', '')

        if not task_id or task_id in stopped_tasks:
            return

        emit('ai_typing', {'typing': True})

        if task_id == 'custom':
            task_description = custom_task_descriptions.get(task_id, '')
        else:
            task = config.TASKS_BY_ID.get(task_id)
            task_description = task['description'] if task else ''
        session_id = active_sessions.get(task_id, '')

        # ── Init or retrieve orchestrator state ───────────────────────────────
        if task_id not in agent_orchestrators:
            agent_orchestrators[task_id] = {
                'orch_phase': 'PLAN',
                'goals': [],
                'worker_iteration': 0,
                'worker_memory': [],
                'last_issues': [],
            }
        state = agent_orchestrators[task_id]
        orch_phase = state['orch_phase']

        worker = AIService('Worker', task_id, session_id=session_id)

        def _goals_as_plan(goals, active_status=None):
            return [
                {
                    'id': g['id'],
                    'label': g.get('title', ''),
                    # Never downgrade an already-complete goal to in_progress
                    'status': 'complete' if g.get('status') == 'complete' else (active_status or g.get('status', 'pending'))
                }
                for g in goals
            ]

        def _worker_chat(message):
            """Append Worker message to memory and user-facing chat."""
            if message:
                state['worker_memory'].append({'role': 'assistant', 'content': message})
                chat_histories[task_id].append({'sender': 'ai', 'message': message})

        def _emit_worker_modeling_response(message, actions):
            """Emit Worker modeling message to chat."""
            if message:
                chat_histories[task_id].append({'sender': 'worker', 'message': message})
            emit('ai_response', {
                'sender': 'worker',
                'message': message,
                'actions': actions,
                'complete': False,
                'phase': 'EXECUTING',
                'goals': [],
                'await_feedback': False,
            })

        try:
            # ══ PLAN: Worker analyzes task and defines goals ══════════════════════
            if orch_phase == 'PLAN':
                emit('ai_typing', {'typing': True, 'sender': 'Worker'})

                instruction = (
                    'Analyze the task thoroughly. Define a comprehensive set of goals describing WHAT the final BPMN model '
                    'must achieve — participants (expanded or collapsed), process outcomes, decisions, messages. '
                    'Each goal has a short title (for UI) and a details field describing what should be achieved. '
                    'Do NOT specify BPMN element types, IDs, or coordinates. Use PLAN phase.'
                )
                response = worker.get_planning_response(
                    task_description, instruction, state['worker_memory'], current_bpmn,
                    phase_hint='PLAN',
                )
                message = response.get('message', '')
                goals = response.get('goals', [])

                _worker_chat(message)
                emit('ai_response', {
                    'sender': 'ai',
                    'message': message,
                    'actions': [],
                    'complete': False,
                    'phase': 'PLAN',
                    'goals': goals,
                    'await_feedback': False,
                })

                if goals:
                    state['goals'] = goals
                    state['worker_iteration'] = 0
                    state['orch_phase'] = 'EXECUTING'
                    emit('agent_plan_update', {
                        'plan': _goals_as_plan(goals, 'pending'),
                        'phase': 'PLAN',
                        'step': None,
                        'step_status': None,
                    })

                emit('ai_typing', {'typing': False})
                if goals and task_id not in stopped_tasks:
                    emit('agent_iterating', {'phase': 'PLAN', 'complete': False})

            # ══ EXECUTING: Worker models the BPMN diagram ════════════════════════
            elif orch_phase == 'EXECUTING':
                goals = state.get('goals', [])
                iteration = state.get('worker_iteration', 0) + 1
                state['worker_iteration'] = iteration

                # Only pass goals that are not yet completed
                pending_goals = [g for g in goals if g.get('status') != 'complete']

                emit('agent_plan_update', {
                    'plan': _goals_as_plan(goals, active_status='in_progress'),
                    'phase': 'EXECUTING',
                    'step': None,
                    'step_status': 'in_progress',
                })

                emit('ai_typing', {'typing': True, 'sender': 'Worker'})

                worker_resp = worker.get_worker_response(
                    task_description, pending_goals, current_bpmn,
                    user_message=state.get('last_user_message', ''),
                    iteration=iteration,
                    memory=state.get('worker_memory', []),
                )
                worker_message = worker_resp.get('message', '')
                actions = worker_resp.get('actions', [])
                is_done = worker_resp.get('done', True)
                completed_ids = set(worker_resp.get('completed_goals', []))

                if worker_message:
                    state['worker_memory'].append({'role': 'assistant', 'content': worker_message})

                # Mark reported goals as complete
                if completed_ids:
                    for g in goals:
                        if g.get('id') in completed_ids:
                            g['status'] = 'complete'

                _emit_worker_modeling_response(worker_message, [])

                if actions:
                    emit('actions_generated', {'actions': actions})

                # Emit updated plan with completed goals checked off
                emit('agent_plan_update', {
                    'plan': _goals_as_plan(goals),
                    'phase': 'EXECUTING',
                    'step': None,
                    'step_status': 'in_progress',
                })

                if is_done:
                    state['orch_phase'] = 'REVIEWING'
                else:
                    # Check if all goals are now complete even though done=false
                    all_complete = all(g.get('status') == 'complete' for g in goals)
                    if all_complete:
                        state['orch_phase'] = 'REVIEWING'

                emit('ai_typing', {'typing': False})
                if task_id not in stopped_tasks:
                    emit('agent_iterating', {'phase': 'EXECUTING', 'complete': False})

            # ══ REVIEWING: Worker visually inspects its own model ════════════════
            elif orch_phase == 'REVIEWING':
                emit('ai_typing', {'typing': True, 'sender': 'Worker'})

                goals = state.get('goals', [])
                goals_summary = '\n'.join(
                    f"  - Goal {g['id']}: {g.get('title', '')} — {g.get('details', '')}"
                    for g in goals
                )

                instruction = (
                    'Review the completed BPMN model carefully against the task description, BPMN standards, and the goals below.\n'
                    f'Goals to verify:\n{goals_summary}\n\n'
                    'For each goal, check whether it is correctly and completely modeled. '
                    'Also verify: every expanded pool has exactly one StartEvent and at least one EndEvent, '
                    'no elements inside collapsed pools, all elements have a valid parent pool or lane, '
                    'no isolated elements or dead ends, gateway rules (labeled XOR/OR outgoing conditions), '
                    'cross-pool connections use message flows with valid endpoints, correct task types and specific labels.\n'
                    'Use REVIEW phase. In goals_status, mark each goal as done: true (fully achieved) or done: false (missing or incorrect). '
                    'Report all issues by severity (critical / warning / info). '
                    'IMPORTANT: Do NOT perform any modeling actions — only report your findings. '
                    'The user will see the issues and decide how to proceed. Set await_feedback: true.'
                )
                response = worker.get_planning_response(
                    task_description, instruction, state['worker_memory'], current_bpmn,
                    phase_hint='REVIEW',
                )
                message = response.get('message', '')
                issues = response.get('issues', [])
                goals_status = response.get('goals_status', [])

                _worker_chat(message)
                state['last_issues'] = issues

                # Update goal status from review
                if goals_status:
                    status_by_id = {str(gs['id']): gs.get('done', False) for gs in goals_status}
                    for g in goals:
                        g_id = str(g.get('id', ''))
                        if g_id in status_by_id:
                            g['status'] = 'complete' if status_by_id[g_id] else 'pending'

                emit('ai_response', {
                    'sender': 'ai',
                    'message': message,
                    'actions': [],
                    'complete': False,
                    'phase': 'REVIEW',
                    'goals': [],
                    'await_feedback': True,
                })

                if issues:
                    emit('reviewer_issues', {'issues': issues})

                emit('agent_plan_update', {
                    'plan': _goals_as_plan(goals),
                    'phase': 'REVIEWING',
                    'step': None,
                    'step_status': None,
                })

                task_tracker.snapshot_task(task_id, current_bpmn)

                # ── Auto-retry for critical issues ────────────────────────────
                _MAX_CRITICAL_RETRIES = 3
                critical_issues = [i for i in issues if i.get('severity') == 'critical']
                review_retries = state.get('review_retry_count', 0)

                if critical_issues and review_retries < _MAX_CRITICAL_RETRIES and task_id not in stopped_tasks:
                    state['review_retry_count'] = review_retries + 1
                    retry_goals = [
                        {
                            'id': idx + 1,
                            'title': f"Fix: {issue.get('shortDesc', 'Critical issue')[:40]}",
                            'details': (
                                f"Fix the critical issue on element \"{issue.get('elementId', '?')}\": "
                                f"{issue.get('longDesc', issue.get('shortDesc', ''))}. "
                                + (f"Suggested fix: {issue.get('fixHint', '')} " if issue.get('fixHint') else '')
                                + f"This is a CRITICAL error that must be resolved before the model is complete."
                            ),
                        }
                        for idx, issue in enumerate(critical_issues)
                    ]
                    state['goals'] = retry_goals
                    state['worker_iteration'] = 0
                    state['orch_phase'] = 'EXECUTING'

                    retry_note = (
                        f"⚠️ {len(critical_issues)} critical issue(s) detected. "
                        f"Automatically starting correction pass {state['review_retry_count']}/{_MAX_CRITICAL_RETRIES}…"
                    )
                    _worker_chat(retry_note)
                    emit('ai_response', {
                        'sender': 'ai',
                        'message': retry_note,
                        'actions': [],
                        'complete': False,
                        'phase': 'REVIEW',
                        'goals': [],
                        'await_feedback': False,
                    })
                    emit('agent_plan_update', {
                        'plan': _goals_as_plan(retry_goals, 'pending'),
                        'phase': 'PLAN',
                        'step': None,
                        'step_status': None,
                    })
                    emit('ai_typing', {'typing': False})
                    emit('agent_iterating', {'phase': 'EXECUTING', 'complete': False})
                else:
                    if critical_issues and review_retries >= _MAX_CRITICAL_RETRIES:
                        max_note = (
                            f"⚠️ After {_MAX_CRITICAL_RETRIES} correction attempt(s), "
                            f"{len(critical_issues)} critical issue(s) remain. Please review manually."
                        )
                        _worker_chat(max_note)
                        emit('ai_response', {
                            'sender': 'ai',
                            'message': max_note,
                            'actions': [],
                            'complete': False,
                            'phase': 'REVIEW',
                            'goals': [],
                            'await_feedback': True,
                        })
                    state['review_retry_count'] = 0
                    state['orch_phase'] = 'AWAITING_USER'
                    emit('ai_typing', {'typing': False})
                    if task_id not in stopped_tasks:
                        emit('agent_iterating', {'phase': 'REVIEW_DONE', 'complete': False})

            # ══ AWAITING_USER: nothing to auto-drive — user messages handled in send_message ══

        except Exception as e:
            print(f"[Orchestrator] Error in phase {orch_phase}: {e}")
            traceback.print_exc()
            emit('ai_typing', {'typing': False})
            emit('error', {'message': 'An unexpected error occurred during modeling. Please try again.'})


def complete_and_upload(task_id: str, bpmn_xml: str = '') -> None:
    """Clean up session state when a task is completed."""
    task_tracker.save_task_report(task_id, bpmn_xml)
    active_sessions.pop(task_id, None)
    chat_histories.pop(task_id, None)
    stopped_tasks.discard(task_id)
    agent_orchestrators.pop(task_id, None)

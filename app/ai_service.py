import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional

from openai import OpenAI

import config
from app.prompts import (
    WORKER_PROMPT_GREETING_FINAL,
    WORKER_PROMPT_PLAN_FINAL,
    WORKER_PROMPT_EXECUTING_FINAL,
    WORKER_PROMPT_REVIEW_FINAL,
    WORKER_PROMPT_REACTION_FINAL,
)
from app import task_tracker
from lion import loads as lion_loads, dumps as lion_dumps, strip_markdown_fences
from benchmarks.config import LION_SCHEMA_MAPPINGS, ACTION_ORDER


class AIService:
    _client: OpenAI = None

    _BPMN_NS = {
        'bpmn': 'http://www.omg.org/spec/BPMN/20100524/MODEL',
        'bpmndi': 'http://www.omg.org/spec/BPMN/20100524/DI',
        'dc': 'http://www.omg.org/spec/DD/20100524/DC',
        'di': 'http://www.omg.org/spec/DD/20100524/DI',
    }
    _TASK_TAGS = frozenset({
        'task', 'userTask', 'serviceTask', 'sendTask', 'receiveTask',
        'manualTask', 'businessRuleTask', 'scriptTask',
    })
    _EVENT_TAGS = frozenset({
        'startEvent', 'endEvent', 'intermediateCatchEvent',
        'intermediateThrowEvent', 'boundaryEvent',
    })
    _GATEWAY_TAGS = frozenset({
        'exclusiveGateway', 'parallelGateway', 'inclusiveGateway',
        'eventBasedGateway', 'complexGateway',
    })
    _EVENT_DEF_TAGS = frozenset({
        'messageEventDefinition', 'timerEventDefinition', 'signalEventDefinition',
        'errorEventDefinition', 'conditionalEventDefinition', 'terminateEventDefinition',
        'escalationEventDefinition', 'compensateEventDefinition',
    })
    _ACTION_VALIDATION_RULES = {
        'participate': ['x', 'y', 'width', 'height'],
        'draw': ['elementType', 'x', 'y'],
        'connect': ['sourceId', 'targetId'],
        'rename': ['elementId', 'label'],
        'move': ['elementId', 'x', 'y'],
        'resize': ['elementId', 'width', 'height'],
        'delete': ['elementId'],
        'update': ['elementId', 'property', 'value'],
    }
    _BPMN_NS_TAG = '{http://www.omg.org/spec/BPMN/20100524/MODEL}'

    _LION_SCALAR_KEY_RE = re.compile(
        r'^(\s*)(message|phase|title|details|shortDesc|longDesc)\s*:\s*(.+)$'
    )
    _LION_KEY_DELIMITER_RE = re.compile(
        r'^\s*(?:message|phase|goals|goals_status|issues|complete|await_feedback|'
        r'actions|done|participate|draw|connect|move|resize|rename|delete|lane|update|'
        r'title|details|shortDesc|longDesc|elementId|severity|category|prop|val)\s*[:(]'
    )

    @classmethod
    def _get_client(cls) -> OpenAI:
        if cls._client is None:
            cls._client = OpenAI(
                api_key=os.getenv('OPENAI_API_KEY')
            )
        return cls._client

    def __init__(self, ai_type: str, task_id: str = 'unknown', session_id: str = ''):
        self.client = self._get_client()
        self.model = config.GPT_MODEL
        self.ai_type = ai_type
        self.task_id = task_id
        self.session_id = session_id
    
    def _log_llm_io(self, label: str, messages: list, response_content: str):
        if not getattr(config, 'LOG_LLM_IO', False):
            return
        
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'llm_logs')
        os.makedirs(log_dir, exist_ok=True)
        
        ai_short = self.ai_type.lower()
        sid = f'_{self.session_id}' if self.session_id else ''
        log_file = os.path.join(log_dir, f'{self.task_id}_{ai_short}{sid}.md')
        
        interaction_num = 1
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                interaction_num = sum(1 for line in f if '## Interaction ' in line) + 1
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        with open(log_file, 'a', encoding='utf-8') as f:
            if interaction_num == 1:
                f.write(f'# LLM Log: {self.task_id}\n')
                f.write(f'- **AI Type:** {self.ai_type}\n')
                f.write(f'- **Model:** {self.model}\n')
                f.write(f'- **Started:** {timestamp}\n\n')
                f.write(f'---\n\n')
            
            f.write(f'## Interaction {interaction_num} — {label}\n')
            f.write(f'**Time:** {timestamp}\n\n')
            
            f.write(f'### Input\n\n')
            for msg in messages:
                role = msg.get('role', 'unknown').upper()
                content = msg.get('content', '')
                f.write(f'**[{role}]**\n```\n{content}\n```\n\n')
            
            f.write(f'### Output\n\n')
            f.write(f'```\n{response_content}\n```\n\n')
            f.write(f'---\n\n')
    
    def _parse_issues(self, raw_issues: List[Any]) -> List[Dict[str, Any]]:
        """Convert and validate raw issues (list/tuple or dict) into normalized issue dicts."""
        result = []
        for item in raw_issues:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                issue = {
                    'elementId': str(item[0]),
                    'severity': str(item[1]) if len(item) > 1 else 'info',
                    'category': str(item[2]) if len(item) > 2 else 'general',
                    'shortDesc': str(item[3]) if len(item) > 3 else 'Issue detected',
                    'longDesc': str(item[4]) if len(item) > 4 else 'No details available',
                    'fixHint': str(item[5]) if len(item) > 5 else '',
                }
            elif isinstance(item, dict):
                issue = item
            else:
                continue

            if 'elementId' not in issue:
                continue

            severity = issue.get('severity', 'info')
            if severity not in ('critical', 'warning', 'info'):
                severity = 'warning' if severity == 'major' else 'info'

            result.append({
                'elementId': issue.get('elementId', ''),
                'severity': severity,
                'category': issue.get('category', 'general'),
                'shortDesc': issue.get('shortDesc', issue.get('message', 'Issue detected')),
                'longDesc': issue.get('longDesc', issue.get('message', 'No details available')),
                'fixHint': issue.get('fixHint', ''),
            })
        return result

    def _bpmn_xml_to_lion(self, xml: str) -> Dict[str, Any]:
        if not xml:
            return {}
        
        try:
            root = ET.fromstring(xml)
            ns = self._BPMN_NS
            
            bounds_map: Dict[str, Dict[str, int]] = {}
            for shape in root.findall('.//bpmndi:BPMNShape', ns):
                bpmn_elem = shape.get('bpmnElement', '')
                bounds = shape.find('dc:Bounds', ns)
                if bpmn_elem and bounds is not None:
                    bounds_map[bpmn_elem] = {
                        'x': int(float(bounds.get('x', '0'))),
                        'y': int(float(bounds.get('y', '0'))),
                        'width': int(float(bounds.get('width', '0'))),
                        'height': int(float(bounds.get('height', '0')))
                    }
            
            proc_to_participant: Dict[str, str] = {}
            
            model: Dict[str, Any] = {
                'pools': [],
                'lanes': [],
                'tasks': [],
                'events': [],
                'gateways': [],
                'flows': []
            }

            pool_expanded_map: Dict[str, bool] = {}
            for shape in root.findall('.//bpmndi:BPMNShape', ns):
                shape_elem = shape.get('bpmnElement', '')
                is_exp_attr = shape.get('isExpanded', None)
                if is_exp_attr is not None:
                    pool_expanded_map[shape_elem] = is_exp_attr.lower() != 'false'

            expanded_processes: set = set()
            for proc in root.findall('.//bpmn:process', ns):
                for child in proc:
                    tag = child.tag.replace(self._BPMN_NS_TAG, '')
                    if tag not in ('documentation', 'laneSet', 'extensionElements'):
                        expanded_processes.add(proc.get('id', ''))
                        break

            for participant in root.findall('.//bpmn:participant', ns):
                p_id = participant.get('id', '')
                p_name = participant.get('name', '')
                process_ref = participant.get('processRef', '')
                if process_ref:
                    proc_to_participant[process_ref] = p_id
                b = bounds_map.get(p_id, {})

                if p_id in pool_expanded_map:
                    is_expanded = pool_expanded_map[p_id]
                elif process_ref and process_ref in expanded_processes:
                    is_expanded = True
                else:
                    is_expanded = False
                model['pools'].append({
                    'id': p_id,
                    'name': p_name,
                    'expanded': is_expanded,
                    'x': b.get('x', 0),
                    'y': b.get('y', 0),
                    'width': b.get('width', 0),
                    'height': b.get('height', 0)
                })
            
            for process in root.findall('.//bpmn:process', ns):
                process_id = process.get('id', '')
                pool_id = proc_to_participant.get(process_id, '')
                
                # Collect lane → flowNodeRef mappings
                lane_members: Dict[str, str] = {}
                for lane_set in process.findall('bpmn:laneSet', ns):
                    for lane in lane_set.findall('.//bpmn:lane', ns):
                        lane_id = lane.get('id', '')
                        lane_name = lane.get('name', '')
                        b = bounds_map.get(lane_id, {})
                        model['lanes'].append({
                            'id': lane_id,
                            'name': lane_name,
                            'pool_id': pool_id,
                            'x': b.get('x', 0),
                            'y': b.get('y', 0),
                            'width': b.get('width', 0),
                            'height': b.get('height', 0)
                        })
                        for ref in lane.findall('bpmn:flowNodeRef', ns):
                            if ref.text:
                                lane_members[ref.text.strip()] = lane_id
                
                for elem in process:
                    tag = elem.tag.replace(self._BPMN_NS_TAG, '')
                    elem_id = elem.get('id', '')
                    elem_name = elem.get('name', '')
                    b = bounds_map.get(elem_id, {})
                    parent_id = lane_members.get(elem_id, pool_id)

                    if tag == 'sequenceFlow':
                        model['flows'].append({
                            'id': elem_id,
                            'source': elem.get('sourceRef', ''),
                            'target': elem.get('targetRef', ''),
                            'type': 'sequenceFlow',
                            'name': elem.get('name', '')
                        })

                    elif tag in self._TASK_TAGS:
                        model['tasks'].append({
                            'id': elem_id,
                            'name': elem_name,
                            'type': tag,
                            'parent': parent_id,
                            'x': b.get('x', 0),
                            'y': b.get('y', 0),
                            'width': b.get('width', 100),
                            'height': b.get('height', 80)
                        })

                    elif tag in self._EVENT_TAGS:
                        event_def = ''
                        for child in elem:
                            child_tag = child.tag.replace(self._BPMN_NS_TAG, '')
                            if child_tag in self._EVENT_DEF_TAGS:
                                event_def = child_tag
                                break
                        model['events'].append({
                            'type': tag,
                            'id': elem_id,
                            'name': elem_name,
                            'parent': parent_id,
                            'eventDefinition': event_def,
                            'x': b.get('x', 0),
                            'y': b.get('y', 0),
                            'width': b.get('width', 36),
                            'height': b.get('height', 36)
                        })

                    elif tag in self._GATEWAY_TAGS:
                        model['gateways'].append({
                            'id': elem_id,
                            'name': elem_name,
                            'type': tag,
                            'parent': parent_id,
                            'x': b.get('x', 0),
                            'y': b.get('y', 0),
                            'width': b.get('width', 50),
                            'height': b.get('height', 50)
                        })
            
            # --- Message flows (cross-pool) ---
            for mf in root.findall('.//bpmn:messageFlow', ns):
                model['flows'].append({
                    'id': mf.get('id', ''),
                    'source': mf.get('sourceRef', ''),
                    'target': mf.get('targetRef', ''),
                    'type': 'messageFlow',
                    'name': mf.get('name', '')
                })
            
            return model
            
        except ET.ParseError as e:
            print(f"[BPMN Parser] XML Parse Error: {e}")
            return {}
    
    def _format_memory_lion(self, messages: List[Dict[str, str]]) -> List[str]:
        """Extract only text messages for memory — content only, no role, no internal signals."""
        SKIP_SIGNALS = {'[CONTINUE_MODELING]', '[INITIAL_GREETING]', '[CONTINUE_AGENT]'}
        memory = []
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            
            if content.strip() in SKIP_SIGNALS:
                continue
            
            # For assistant LION responses, extract only the message text
            if role == 'assistant' and (content.startswith('message:') or content.startswith('phase:')):
                parsed = self._parse_lion(content)
                if parsed and 'message' in parsed:
                    content = parsed['message']
            
            if content.strip():
                memory.append(content)
        return memory
    
    def _build_lion_context(
        self,
        task: str,
        user_input: Optional[str],
        instruction: str,
        memory: List[Dict[str, str]],
        bpmn_model: Dict[str, Any],
    ) -> str:
        context = {
            'task': task,
            'instruction': instruction,
            'user_input': user_input or '',
            'memory': self._format_memory_lion(memory) if memory else [],
            'bpmn_model': bpmn_model or {
                'pools': [], 'lanes': [], 'tasks': [],
                'events': [], 'gateways': [], 'flows': [],
            },
        }
        return lion_dumps(context, pretty=True)

    def _handle_planning_response(self, content: str) -> Dict[str, Any]:
        """Handle Worker planning/review/feedback response — parse phase, goals, issues."""
        parsed = self._parse_lion(content)

        if not parsed or 'phase' not in parsed:
            print(f"[Worker] Warning: response not in expected LION format")
            print(f"[Worker] Raw content (first 300 chars): {content[:300]}")

            # Attempt to extract just the message field via regex before giving up
            fallback_message = ''
            quoted = re.search(r'message\s*:\s*"((?:[^"\\]|\\.)*)"', content, re.DOTALL)
            if quoted:
                fallback_message = quoted.group(1).replace('\\n', '\n').replace('\\"', '"')
            else:
                unquoted = re.search(r'message\s*:\s*([^\n,}{\[\]]+)', content)
                if unquoted:
                    fallback_message = unquoted.group(1).strip()
            if not fallback_message:
                fallback_message = content if isinstance(content, str) else str(content)
            return {
                'message': fallback_message,
                'phase': 'FEEDBACK',
                'packages': [],
                'issues': [],
                'complete': False,
                'await_feedback': True,
                'ai_type': self.ai_type,
            }

        message = parsed.get('message', '')
        if not isinstance(message, str):
            message = str(message) if message is not None else ''

        phase = parsed.get('phase', 'FEEDBACK')
        if isinstance(phase, str):
            phase = phase.upper()

        # Parse goals (PLAN phase)
        goals = []
        if phase == 'PLAN':
            raw_goals = parsed.get('goals', [])
            if isinstance(raw_goals, list):
                for i, item in enumerate(raw_goals):
                    if isinstance(item, dict):
                        goals.append({
                            'id': item.get('id', i + 1),
                            'title': str(item.get('title', f'Goal {i + 1}')),
                            'details': str(item.get('details', '')),
                            'status': 'pending',
                        })

        # Parse issues and goals_status (REVIEW phase)
        issues = []
        goals_status = []
        if phase == 'REVIEW':
            raw_issues = parsed.get('issues', [])
            if isinstance(raw_issues, list):
                issues = self._parse_issues(raw_issues)
            raw_goals_status = parsed.get('goals_status', [])
            if isinstance(raw_goals_status, list):
                for item in raw_goals_status:
                    if isinstance(item, dict):
                        goals_status.append({
                            'id': item.get('id'),
                            'done': bool(item.get('done', False)),
                        })

        is_complete = parsed.get('complete', False)
        await_feedback = parsed.get('await_feedback', False)
        if phase in ('FEEDBACK', 'ANSWER'):
            await_feedback = True

        print(f"[Worker] Phase={phase}, goals={len(goals)}, "
              f"issues={len(issues)}, complete={is_complete}, await_feedback={await_feedback}")

        return {
            'message': message,
            'phase': phase,
            'goals': goals,
            'issues': issues,
            'goals_status': goals_status,
            'complete': is_complete,
            'await_feedback': await_feedback,
            'ai_type': self.ai_type,
        }

    def _handle_worker_response(self, content: str) -> Dict[str, Any]:
        """Handle Worker response — parse actions and done flag."""
        parsed = self._parse_lion(content)

        if not parsed:
            print(f"[Worker] Warning: response not in expected LION format")
            return {
                'message': content if isinstance(content, str) else '',
                'actions': [],
                'done': True,
                'ai_type': self.ai_type,
            }

        message = parsed.get('message', '')
        if not isinstance(message, str):
            message = str(message) if message is not None else ''

        actions = []
        try:
            actions = self._convert_lion_actions(parsed.get('actions', {}))
        except Exception as e:
            print(f"[Worker] Error converting actions: {e}")

        done = parsed.get('done', True)

        completed_goals = []
        raw_completed = parsed.get('completed_goals', [])
        if isinstance(raw_completed, list):
            for x in raw_completed:
                try:
                    completed_goals.append(int(x))
                except (TypeError, ValueError):
                    pass

        print(f"[Worker] actions={len(actions)}, done={done}, completed_goals={completed_goals}")

        return {
            'message': message,
            'actions': actions,
            'done': done,
            'completed_goals': completed_goals,
            'ai_type': self.ai_type,
        }

    def _build_worker_context(
        self,
        task: str,
        goals: List[Dict[str, Any]],
        bpmn_model: Dict[str, Any],
        user_message: str = '',
        iteration: int = 1,
        memory: Optional[List[str]] = None,
        supervisor_feedback: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build LION context for Worker execution with all goals."""
        context = {
            'goals': [
                {'id': g.get('id'), 'title': g.get('title', ''), 'details': g.get('details', '')}
                for g in goals
            ],
            'iteration': iteration,
            'task': task,
            'user_message': user_message,
            'memory': memory or [],
            'bpmn_model': bpmn_model if bpmn_model else {
                'pools': [], 'lanes': [], 'tasks': [],
                'events': [], 'gateways': [], 'flows': [],
            },
        }
        if supervisor_feedback:
            context['supervisor_feedback'] = supervisor_feedback
        return lion_dumps(context, pretty=True)

    def get_worker_response(
        self,
        task_description: str,
        goals: List[Dict[str, Any]],
        current_bpmn_state: Optional[str] = None,
        user_message: str = '',
        iteration: int = 1,
        memory: Optional[List[Dict[str, str]]] = None,
        supervisor_feedback: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a Worker iteration with all goals."""
        bpmn_model = {}
        if current_bpmn_state:
            bpmn_model = self._bpmn_xml_to_lion(current_bpmn_state)

        worker_context = self._build_worker_context(
            task=task_description,
            goals=goals,
            bpmn_model=bpmn_model,
            user_message=user_message,
            iteration=iteration,
            memory=self._format_memory_lion(memory) if memory else [],
            supervisor_feedback=supervisor_feedback,
        )

        api_messages = [
            {'role': 'system', 'content': WORKER_PROMPT_EXECUTING_FINAL},
            {'role': 'user', 'content': worker_context},
        ]

        print(f"[Worker] Iteration {iteration}, goals={len(goals)}")

        _WORKER_RETRY_HINT = (
            'Your previous response could not be parsed as valid LION. '
            'Please respond again, strictly following the LION format. '
            'The response must include the "actions" and "done" fields at the top level.'
        )

        content = None
        for attempt in range(2):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=api_messages
                )
                content = response.choices[0].message.content
                if response.usage:
                    task_tracker.record_llm_call(
                        self.task_id, self.ai_type,
                        response.usage.prompt_tokens,
                        response.usage.completion_tokens,
                    )
                self._log_llm_io(f'worker_iter{iteration}', api_messages, content)

                parsed = self._parse_lion(content)
                if parsed is not None:
                    break

                if attempt == 0:
                    print(f"[Worker] Iteration {iteration}: invalid LION on attempt 1, retrying silently")
                    api_messages = api_messages + [
                        {'role': 'assistant', 'content': content},
                        {'role': 'user', 'content': _WORKER_RETRY_HINT},
                    ]
                else:
                    print(f"[Worker] Iteration {iteration}: invalid LION on attempt 2, proceeding with fallback")

            except Exception as e:
                print(f"[Worker] Iteration {iteration} API Error: {e}")
                return {
                    'message': f"Worker error: {e}",
                    'actions': [],
                    'done': True,
                    'ai_type': self.ai_type,
                    'error': str(e),
                }

        return self._handle_worker_response(content)

    _PLANNING_PHASE_PROMPTS = {
        'PLAN':     WORKER_PROMPT_PLAN_FINAL,
        'REVIEW':   WORKER_PROMPT_REVIEW_FINAL,
        'REACTION': WORKER_PROMPT_REACTION_FINAL,
    }

    def get_planning_response(
        self,
        task_description: str,
        instruction: str,
        memory: List[Dict[str, str]],
        current_bpmn_state: Optional[str] = None,
        user_message: Optional[str] = None,
        phase_hint: str = 'REACTION',
    ) -> Dict[str, Any]:
        """Call the Worker for planning/review/feedback phases with a specific instruction."""
        bpmn_model = {}
        if current_bpmn_state:
            bpmn_model = self._bpmn_xml_to_lion(current_bpmn_state)

        lion_context = self._build_lion_context(
            task=task_description,
            user_input=user_message or '',
            instruction=instruction,
            memory=memory,
            bpmn_model=bpmn_model,
        )

        system_prompt = self._PLANNING_PHASE_PROMPTS.get(phase_hint, WORKER_PROMPT_REACTION_FINAL)
        api_messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': lion_context},
        ]

        _PLANNING_RETRY_HINT = (
            'Your previous response could not be parsed as valid LION. '
            'Please respond again, strictly following the LION format. '
            'The response must include the "phase" and "message" fields at the top level.'
        )

        content = None
        for attempt in range(2):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=api_messages
                )
                content = response.choices[0].message.content
                if response.usage:
                    task_tracker.record_llm_call(
                        self.task_id, self.ai_type,
                        response.usage.prompt_tokens,
                        response.usage.completion_tokens,
                    )
                self._log_llm_io('worker_planning', api_messages, content)

                parsed = self._parse_lion(content)
                if parsed is not None and 'phase' in parsed:
                    break  # Valid LION — proceed

                if attempt == 0:
                    print(f"[Worker] Invalid LION on attempt 1, retrying silently")
                    api_messages = api_messages + [
                        {'role': 'assistant', 'content': content},
                        {'role': 'user', 'content': _PLANNING_RETRY_HINT},
                    ]
                else:
                    print(f"[Worker] Invalid LION on attempt 2, proceeding with fallback")

            except Exception as e:
                print(f"[Worker] API Error: {e}")
                return {
                    'message': f"Worker error: {e}",
                    'phase': 'FEEDBACK',
                    'packages': [],
                    'issues': [],
                    'complete': False,
                    'await_feedback': True,
                    'ai_type': self.ai_type,
                    'error': str(e),
                }

        return self._handle_planning_response(content)

    @staticmethod
    def _preprocess_lion(text: str) -> str:
        """Auto-quote unquoted string values for known scalar LION keys.

        The LION decoder reads bare identifiers token-by-token, so a value like
            message: Completed package 5 by ensuring …
        is only parsed as ``"Completed"`` — the remaining words cause a parse
        error.  This method wraps such values in double quotes before the
        decoder runs, handling optional multi-line continuations.
        """
        scalar_re = AIService._LION_SCALAR_KEY_RE
        delim_re  = AIService._LION_KEY_DELIMITER_RE
        close_re  = re.compile(r'^\s*[}\]]\s*,?\s*$')
        num_re    = re.compile(r'^-?\d')

        lines  = text.split('\n')
        result = []
        i = 0
        while i < len(lines):
            line = lines[i]
            m = scalar_re.match(line)
            if m:
                indent, key, first = m.group(1), m.group(2), m.group(3).rstrip()
                stripped = first.strip()

                if (
                    stripped.startswith('"') or
                    stripped.startswith('{') or
                    stripped.startswith('[') or
                    stripped in ('true', 'false', 'null') or
                    num_re.match(stripped)
                ):
                    result.append(line)
                    i += 1
                    continue

                # Unquoted string — collect any soft continuation lines
                parts = [stripped]
                i += 1
                while i < len(lines):
                    nxt = lines[i]
                    if delim_re.match(nxt) or close_re.match(nxt):
                        break
                    parts.append(nxt.strip())
                    i += 1
                combined = ' '.join(p for p in parts if p)
                combined = combined.rstrip(',')
                combined = combined.replace('\\', '\\\\').replace('"', '\\"')
                result.append(f'{indent}{key}: "{combined}"')
            else:
                result.append(line)
                i += 1
        return '\n'.join(result)

    def _parse_lion(self, content: str) -> Optional[Dict[str, Any]]:
        content = strip_markdown_fences(content)
        content = self._preprocess_lion(content)
        try:
            return lion_loads(content)
        except Exception as e:
            print(f"[LION Parser] Error: {e}")
            print(f"[LION Parser] Raw LLM response:\n{content}")
            return None
    
    def _convert_lion_actions(self, actions_raw: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(actions_raw, dict):
            return []
        
        actions = []
        
        for action_type in ACTION_ORDER:
            if action_type not in actions_raw:
                continue
            
            action_list = actions_raw[action_type]
            if not isinstance(action_list, list):
                continue
            
            if action_type == 'delete':
                for item in action_list:
                    if isinstance(item, str):
                        actions.append({'type': 'delete', 'elementId': item})
                continue

            if action_type == 'update':
                for item in action_list:
                    if isinstance(item, dict):
                        elem_id = item.get('id', item.get('elementId', ''))
                        prop = item.get('prop', item.get('property', ''))
                        val = item.get('val', item.get('value', ''))
                        if elem_id and prop:
                            actions.append({
                                'type': 'update',
                                'elementId': str(elem_id),
                                'property': str(prop),
                                'value': str(val) if val is not None else 'null',
                            })
                continue
            
            mapping = LION_SCHEMA_MAPPINGS.get(action_type, {})
            
            for item in action_list:
                if not isinstance(item, dict):
                    continue
                
                action = {'type': action_type}
                for lion_key, frontend_key in mapping.items():
                    if lion_key in item and item[lion_key] is not None:
                        value = item[lion_key]
                        if value != '' and not (isinstance(value, list) and len(value) == 0):
                            action[frontend_key] = value
                
                if action_type == 'participate':
                    raw_lanes = action.get('lanes')
                    if raw_lanes and isinstance(raw_lanes, list):
                        action['lanes'] = [str(l) for l in raw_lanes if l]
                    else:
                        action['lanes'] = []
                
                if self._validate_action(action):
                    actions.append(action)
        
        return actions
    
    def _validate_action(self, action: Dict[str, Any]) -> bool:
        action_type = action.get('type')
        if action_type not in self._ACTION_VALIDATION_RULES:
            return False
        required = self._ACTION_VALIDATION_RULES[action_type]
        if not all(key in action for key in required):
            return False
        
        if action_type == 'draw':
            if isinstance(action.get('elementType'), str):
                if not action['elementType'].startswith('bpmn:'):
                    action['elementType'] = f"bpmn:{action['elementType']}"
            
            if isinstance(action.get('eventDefinition'), str):
                if not action['eventDefinition'].startswith('bpmn:'):
                    action['eventDefinition'] = f"bpmn:{action['eventDefinition']}"

        if action_type == 'update':
            prop = action.get('property', '')
            val = action.get('value', '')
            if prop in ('type', 'eventDefinition') and isinstance(val, str) and val and val not in ('null', 'none', 'None'):
                if not val.startswith('bpmn:'):
                    action['value'] = f'bpmn:{val}'
        
        return True
    
    def generate_worker_greeting(self, task_description: str) -> Dict[str, Any]:
        """Worker generates a brief greeting before starting plan phase."""
        greeting_prompt = f"""A new BPMN modeling task has just arrived.

Task: {task_description}

Write a very short greeting (1–2 sentences) that:
1. Introduces yourself briefly as the BPMN Modeling Agent
2. States that you will now start analyzing and planning

Use Markdown. Be concise — no more than 2 sentences."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": WORKER_PROMPT_GREETING_FINAL},
                    {"role": "user", "content": greeting_prompt}
                ],
            )
            content = response.choices[0].message.content.strip()
            if response.usage:
                task_tracker.record_llm_call(
                    self.task_id, self.ai_type,
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                )
            self._log_llm_io('worker_greeting', [
                {"role": "system", "content": WORKER_PROMPT_GREETING_FINAL},
                {"role": "user", "content": greeting_prompt}
            ], content)

            parsed = self._parse_lion(content)
            if parsed and isinstance(parsed.get('message'), str):
                content = parsed['message']

            return {'message': content, 'ai_type': self.ai_type}

        except Exception as e:
            print(f"[Worker] Greeting error: {e}")
            return {
                'message': "Hello! I'm your BPMN Modeling Agent. I'll analyze the task now and start planning the diagram.",
                'ai_type': self.ai_type
            }
    

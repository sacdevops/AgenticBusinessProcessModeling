/**
 * Task Page JavaScript
 * Handles BPMN.io, WebSocket, Chat, AI Actions, Timer
 */

function initBPMN() {
    modeler = new BpmnJS({
        container: '#bpmn-canvas',
        keyboard: {
            bindTo: document
        }
    });

    const initialBPMN = `<?xml version="1.0" encoding="UTF-8"?>
    <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                      xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                      xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                      id="Definitions_1"
                      targetNamespace="http://bpmn.io/schema/bpmn">
      <bpmn:process id="Process_1" isExecutable="false">
      </bpmn:process>
      <bpmndi:BPMNDiagram id="BPMNDiagram_1">
        <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_1">
        </bpmndi:BPMNPlane>
      </bpmndi:BPMNDiagram>
    </bpmn:definitions>`;

    modeler.importXML(initialBPMN).catch(err => {
        console.error('Failed to load BPMN diagram', err);
    });
}

function getBPMNXML() {
    return new Promise((resolve, reject) => {
        modeler.saveXML({ format: true }).then(result => {
            resolve(result.xml);
        }).catch(err => {
            reject(err);
        });
    });
}

let laneIdMap = {};

let isExecutingActions = false;
let pendingContinuation = false;
let isModelingInProgress = false;
let isStopped = false;
let lastChatSender = null;
let pendingReviewIssues = [];
let pendingReviewMessage = '';
let lastAgentPhase = '';

const AGENT_CONTINUE_DELAY_MS = 500;
const MODELER_INIT_DELAY_MS = 1000;
const INITIAL_GREETING_SIGNAL = '[INITIAL_GREETING]';
const ACTION_ORDER = ['delete', 'resize', 'move', 'participate', 'draw', 'rename', 'update', 'connect'];

// Cached DOM references — initialized in DOMContentLoaded
let elAiCursor = null;
let elSendBtn = null;
let elSendText = null;
let elSendSpinner = null;
let elChatInput = null;
let elChatMessages = null;

function initWebSocket() {
    socket = io({
        transports: ['websocket', 'polling'],
        timeout: 300000
    });

    socket.on('connect', () => {
        socket.emit('join_task', { task_id: TASK_ID, ai_type: AI_TYPE });
    });

    socket.on('disconnect', () => {
        hideTypingIndicator();
        hideCursorThinking();
        isModelingInProgress = false;
        isExecutingActions = false;
        enableUIAfterModeling();
        addMessageToChat('ai', '\u26a0\ufe0f Connection to server lost. Please refresh the page.');
    });

    socket.on('task_joined', (data) => {
        if (IS_CUSTOM) {
            // Wait for the user to confirm the custom task description before greeting
            return;
        }
        requestInitialGreeting();
    });

    socket.on('message_sent', (data) => {
        addMessageToChat(data.sender, data.message);
    });

    socket.on('ai_typing', (data) => {
        if (data.typing) {
            showTypingIndicator(data.sender);
        } else {
            hideTypingIndicator();
        }
    });

    socket.on('ai_response', (data) => {
        if (isStopped) return;
        
        hideTypingIndicator();
        
        // Add phase badge to message if provided
        if (data.phase) {
            const phaseBadge = `<span class="chat-phase-badge phase-${data.phase.toLowerCase()}">${data.phase}</span>`;
            try {
                addMessageToChat(data.sender, data.message, phaseBadge);
            } catch (err) {
                console.error('[Frontend] Error adding message to chat:', err);
            }
        } else {
            try {
                addMessageToChat(data.sender, data.message);
            } catch (err) {
                console.error('[Frontend] Error adding message to chat:', err);
            }
        }
        
        const isComplete = data.complete !== undefined ? data.complete : true;
        const awaitFeedback = data.await_feedback || false;
        isModelingInProgress = !isComplete && !awaitFeedback;
        
        const hasActions = data.actions && (
            (Array.isArray(data.actions) && data.actions.length > 0) || 
            (typeof data.actions === 'object' && Object.keys(data.actions).length > 0)
        );
        
        if (isComplete) {
            hideCursorThinking();
            if (!hasActions) {
                if (elAiCursor) elAiCursor.classList.remove('active');
                enableUIAfterModeling();
            }
        } else if (awaitFeedback) {
            // Worker is waiting for feedback — enable chat input
            hideCursorThinking();
            if (elAiCursor) elAiCursor.classList.remove('active');
            enableChatInput();
        } else {
            if (elAiCursor) elAiCursor.classList.add('active');
            showCursorThinking();
            disableUIWhileModeling();
        }
    });
    
    socket.on('actions_generated', (data) => {
        if (isStopped) return;
        
        hideCursorThinking();
        
        const hasActions = (Array.isArray(data.actions) && data.actions.length > 0) || 
                          (typeof data.actions === 'object' && data.actions !== null && Object.keys(data.actions).length > 0);
        
        if (hasActions) {
            let actionCount = 0;
            if (Array.isArray(data.actions)) {
                actionCount = data.actions.length;
            } else if (typeof data.actions === 'object') {
                actionCount = Object.values(data.actions).reduce((sum, arr) => sum + (Array.isArray(arr) ? arr.length : 0), 0);
            }
            try {
                executeAIActions(data.actions);
            } catch (err) {
                console.error('[Frontend] Error executing actions:', err);
                isExecutingActions = false;
                if (pendingContinuation && !isStopped) {
                    pendingContinuation = false;
                    setTimeout(() => continueAgent(), AGENT_CONTINUE_DELAY_MS);
                }
            }
        }
    });

    socket.on('completion_review_result', (data) => {
        hideTypingIndicator();
        
        if (data.has_issues) {
            pendingReviewIssues = data.issues || [];
            pendingReviewMessage = data.message || '';
            document.getElementById('completionConfirmModal').style.display = 'flex';
        } else {
            completeTask();
        }
    });
    
    socket.on('reviewer_issues', (data) => {
        if (data.issues && data.issues.length > 0) {
            displayIssues(data.issues);
        }
    });

    socket.on('fix_issue_result', (data) => {
        hideTypingIndicator();
        hideCursorThinking();

        if (data.message) {
            addMessageToChat('ai', data.message);
        }

        if (data.actions && data.actions.length > 0) {
            pendingContinuation = false;
            executeAIActions(data.actions);
        } else {
            isModelingInProgress = false;
            enableUIAfterModeling();
            enableChatInput();
        }

        // Remove the fixed issue overlay
        if (data.issue) {
            const idx = currentIssues.findIndex(i =>
                i.elementId === data.issue.elementId && i.shortDesc === data.issue.shortDesc
            );
            if (idx >= 0) {
                const overlay = issueOverlays[idx];
                if (overlay && modeler) {
                    try { modeler.get('overlays').remove(overlay.id); } catch (e) {}
                }
                currentIssues.splice(idx, 1);
                issueOverlays.splice(idx, 1);
                createIssueSummary(currentIssues);
            }
        }
    });

    socket.on('agent_plan_update', (data) => {
        if (isStopped) return;
        updatePlanPanel(data.plan, data.step, data.step_status, data.phase);
    });

    socket.on('agent_iterating', (data) => {
        if (isStopped) return;
        
        lastAgentPhase = data.phase || '';
        
        if (data.phase === 'REVIEW_DONE') {
            // Modeling and review are done — stop animation and wait for user
            hideTypingIndicator();
            hideCursorThinking();
            enableChatInput();
            return;
        }
        
        if (!data.complete) {
            showCursorThinking();
            showTypingIndicator();
            if (isExecutingActions) {
                pendingContinuation = true;
            } else {
                setTimeout(() => continueAgent(), AGENT_CONTINUE_DELAY_MS);
            }
        }
    });

    socket.on('error', (data) => {
        console.error('Socket error:', data);
        addMessageToChat('ai', `\u26a0\ufe0f ${data.message || 'An unexpected error occurred.'}`);
        
        isModelingInProgress = false;
        hideTypingIndicator();
        hideCursorThinking();
        enableUIAfterModeling();
        enableChatInput();
        
        if (elAiCursor) elAiCursor.classList.remove('active');
    });
}

function requestInitialGreeting() {
    isStopped = false;
    
    showStopButton();
    showTypingIndicator();
    
    isModelingInProgress = true;
    disableUIWhileModeling();
    
    // At greeting time the diagram is always empty — emit immediately without reading XML
    socket.emit('send_message', {
        task_id: TASK_ID,
        message: INITIAL_GREETING_SIGNAL,
        ai_type: AI_TYPE,
        bpmn_xml: ''
    });
}

function sendMessage() {
    const message = elChatInput ? elChatInput.value.trim() : '';
    
    if (!message) return;
    
    isStopped = false;
    
    addMessageToChat('user', message);
    showTypingIndicator();
    
    if (elChatInput) {
        elChatInput.disabled = true;
        elChatInput.value = '';
    }
    
    showStopButton();
    disableCompleteButton();
    
    isModelingInProgress = true;
    disableUIWhileModeling();
    
    getBPMNXML().then(xml => {
        socket.emit('send_message', {
            task_id: TASK_ID,
            message: message,
            ai_type: AI_TYPE,
            bpmn_xml: xml
        });
    }).catch(err => console.error('[Frontend] Could not read BPMN XML:', err));
}

function stopAI() {
    isStopped = true;
    isModelingInProgress = false;
    isExecutingActions = false;
    pendingContinuation = false;
    
    if (elAiCursor) {
        elAiCursor.classList.remove('active');
        hideCursorThinking();
    }
    
    hideTypingIndicator();
    hideStopButton();
    enableUIAfterModeling();
    
    socket.emit('stop_ai', { task_id: TASK_ID });
}

function showStopButton() {
    if (elSendBtn) {
        elSendBtn.disabled = false;
        elSendBtn.classList.add('stop-mode');
        elSendBtn.onclick = stopAI;
    }
    if (elSendText) {
        elSendText.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>';
        elSendText.style.display = 'inline-flex';
    }
    if (elSendSpinner) elSendSpinner.style.display = 'none';
}

function hideStopButton() {
    if (elSendBtn) {
        elSendBtn.classList.remove('stop-mode');
        elSendBtn.onclick = sendMessage;
    }
    if (elSendText) elSendText.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>';
}

function enableChatInput() {
    if (elChatInput) {
        elChatInput.disabled = false;
        elChatInput.focus();
    }
    if (elSendBtn) elSendBtn.disabled = false;
    hideStopButton();
    
    enableCompleteButton();

    const exportBtn = document.getElementById('exportBtn');
    if (exportBtn) {
        exportBtn.disabled = false;
        exportBtn.style.opacity = '1';
        exportBtn.style.cursor = 'pointer';
    }
}

function handleChatKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

function addMessageToChat(sender, message, phaseBadge) {
    const chatMessages = elChatMessages;
    
    // Coerce message to string to prevent TypeError on .trim()
    if (message !== null && message !== undefined && typeof message !== 'string') {
        message = String(message);
    }
    
    if (!message || message.trim() === '') {
        return;
    }
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message ${sender}`;
    
    const showSender = lastChatSender !== sender;
    lastChatSender = sender;
    
    // Resolve display name for each sender type
    const senderDisplayName = sender === 'user' ? 'You' : AI_TYPE;
    
    if (showSender) {
        const senderDiv = document.createElement('div');
        senderDiv.className = 'message-sender';
        senderDiv.textContent = senderDisplayName;
        messageDiv.appendChild(senderDiv);
        // Phase badge goes below sender name as a separate element
        if (phaseBadge && sender !== 'user') {
            const badgeDiv = document.createElement('div');
            badgeDiv.className = 'message-phase-badge-row';
            badgeDiv.innerHTML = phaseBadge;
            messageDiv.appendChild(badgeDiv);
        }
    } else if (phaseBadge && sender !== 'user') {
        const badgeDiv = document.createElement('div');
        badgeDiv.className = 'message-phase-only';
        badgeDiv.innerHTML = phaseBadge;
        messageDiv.appendChild(badgeDiv);
        messageDiv.classList.add('consecutive');
    } else {
        messageDiv.classList.add('consecutive');
    }
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.innerHTML = formatMarkdown(message);
    
    const timestampDiv = document.createElement('div');
    timestampDiv.className = 'message-timestamp';
    timestampDiv.textContent = new Date().toLocaleTimeString('en-US');
    
    messageDiv.appendChild(contentDiv);
    messageDiv.appendChild(timestampDiv);
    
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function formatMarkdown(text) {
    if (!text) return '';
    
    let formatted = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    
    formatted = formatted.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    formatted = formatted.replace(/__(.+?)__/g, '<strong>$1</strong>');
    
    formatted = formatted.replace(/\*(.+?)\*/g, '<em>$1</em>');
    formatted = formatted.replace(/_(.+?)_/g, '<em>$1</em>');
    
    formatted = formatted.replace(/~~(.+?)~~/g, '<s>$1</s>');
    
    formatted = formatted.replace(/^[\s]*--\s+(.+)$/gm, '<li class="nested-li">$1</li>');
    formatted = formatted.replace(/^[\s]*[-*•]\s+(.+)$/gm, '<li>$1</li>');
    formatted = formatted.replace(/^[\s]*\d+\)\s+(.+)$/gm, '<li>$1</li>');
    
    formatted = formatted.replace(/(<li[^>]*>.*?<\/li>[\n]*)+/g, (match) => {
        const cleanedMatch = match.replace(/\n/g, '');
        
        let processed = cleanedMatch.replace(/(<li class="nested-li">.*?<\/li>)+/g, (nestedMatch) => {
            return '<ul class="nested-ul">' + nestedMatch + '</ul>';
        });
        
        return '<ul>' + processed + '</ul>';
    });
    
    formatted = formatted.replace(/<\/ul>\n+/g, '</ul>\n');
    
    formatted = formatted.replace(/\n\n+/g, '<br><br>');
    
    formatted = formatted.replace(/\n/g, '<br>');
    
    return formatted;
}

function showTypingIndicator(sender) {
    const existing = document.getElementById('typingIndicator');
    if (existing) return;
    
    if (!elChatMessages) return;
    const chatMessages = elChatMessages;
    
    const displayName = AI_TYPE || 'AI';
    const indicatorClass = 'chat-message ai';
    
    const indicator = document.createElement('div');
    indicator.id = 'typingIndicator';
    indicator.className = indicatorClass;
    indicator.innerHTML = `
        <div class="message-sender">${displayName}</div>
        <div class="message-content">
            <div class="chat-typing-indicator">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        </div>
    `;
    
    chatMessages.appendChild(indicator);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function hideTypingIndicator() {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) {
        indicator.remove();
    }
}

function showCursorThinking() {
    if (elAiCursor) elAiCursor.classList.add('thinking');
}

function hideCursorThinking() {
    if (elAiCursor) elAiCursor.classList.remove('thinking');
}

function optimizeActionOrder(actions) {
    const buckets = Object.fromEntries(ACTION_ORDER.map(t => [t, []]));
    actions.forEach(action => { if (action.type in buckets) buckets[action.type].push(action); });
    const [deletes, resizes, moves, participants, shapes, renames, updates, connections] = ACTION_ORDER.map(t => buckets[t]);

    const result = [...deletes, ...resizes, ...moves, ...participants];
    const createdElements = new Set(participants.map(p => p.elementId));
    const remainingConnections = [...connections];

    shapes.forEach(shape => {
        result.push(shape);
        createdElements.add(shape.elementId);

        for (let i = remainingConnections.length - 1; i >= 0; i--) {
            const conn = remainingConnections[i];
            if (createdElements.has(conn.sourceId) && createdElements.has(conn.targetId)) {
                result.push(conn);
                remainingConnections.splice(i, 1);
            }
        }
    });

    result.push(...renames);
    result.push(...updates);
    result.push(...remainingConnections);

    return result;
}

const ACTION_SCHEMAS = {
    "delete": ["type", "elementId"],
    "resize": ["type", "elementId", "width", "height"],
    "move": ["type", "elementId", "x", "y"],
    "participate": ["type", "x", "y", "width", "height", "label", "elementId", "isExpanded", "lanes"],
    "draw": ["type", "elementType", "x", "y", "label", "elementId", "parentId", "connectTo", "eventDefinition"],
    "rename": ["type", "elementId", "label"],
    "update": ["type", "elementId", "property", "value"],
    "connect": ["type", "sourceId", "targetId"]
};

function arrayToActionDict(actionArray) {
    if (!Array.isArray(actionArray)) {
        return actionArray;
    }
    
    if (actionArray.length === 0) {
        return {};
    }
    
    const actionType = actionArray[0];
    const schema = ACTION_SCHEMAS[actionType];
    
    if (!schema) {
        return {};
    }
    
    const actionDict = {};
    schema.forEach((key, index) => {
        if (index < actionArray.length) {
            const value = actionArray[index];
            if (value !== null && value !== undefined && value !== "") {
                actionDict[key] = value;
            }
        }
    });
    
    return actionDict;
}

function expandConnectToActions(actions) {
    const expandedActions = [];
    const generatedConnections = new Set();
    
    actions.forEach(action => {
        if (action.type === 'draw' && action.connectTo && Array.isArray(action.connectTo) && action.connectTo.length > 0) {
            action.connectTo.forEach(targetId => {
                if (targetId && targetId !== '') {
                    const connectionKey = `${action.elementId}->${targetId}`;
                    generatedConnections.add(connectionKey);
                }
            });
        }
    });
    
    actions.forEach(action => {
        if (action.type === 'draw' && action.connectTo && Array.isArray(action.connectTo) && action.connectTo.length > 0) {
            const drawAction = { ...action };
            delete drawAction.connectTo;
            
            expandedActions.push(drawAction);
            
            action.connectTo.forEach(targetId => {
                if (targetId && targetId !== '') {
                    expandedActions.push({
                        type: 'connect',
                        sourceId: action.elementId,
                        targetId: targetId
                    });
                }
            });
        } else if (action.type === 'connect') {
            const connectionKey = `${action.sourceId}->${action.targetId}`;
            
            if (!generatedConnections.has(connectionKey)) {
                expandedActions.push(action);
            }
        } else {
            expandedActions.push(action);
        }
    });
    
    return expandedActions;
}

function executeAIActions(actions) {
    if (!actions) return;
    
    let actionArray = [];
    
    if (Array.isArray(actions)) {
        if (actions.length === 0) return;
        
        // Check if actions are already dict objects (from backend _convert_lion_actions)
        if (actions.length > 0 && typeof actions[0] === 'object' && !Array.isArray(actions[0]) && actions[0].type) {
            actionArray = actions;
        } else {
            actionArray = actions;
        }
    } else if (typeof actions === 'object' && actions !== null) {
        
        const actionOrder = ['delete', 'resize', 'move', 'participate', 'draw', 'rename', 'update', 'connect'];
        
        for (const actionType of actionOrder) {
            if (actions[actionType] && Array.isArray(actions[actionType])) {
                if (actionType === 'delete') {
                    for (const item of actions[actionType]) {
                        if (typeof item === 'string') {
                            actionArray.push(['delete', item]);
                        }
                        else if (Array.isArray(item) && item.length > 0) {
                            actionArray.push(['delete', item[0]]);
                        }
                    }
                } else {
                    for (const actionData of actions[actionType]) {
                        if (Array.isArray(actionData)) {
                            actionArray.push([actionType, ...actionData]);
                        } else if (typeof actionData === 'object' && actionData !== null) {
                            // Support dict-format actions in grouped format too
                            actionArray.push({type: actionType, ...actionData});
                        }
                    }
                }
            }
        }
        
    } else {
        console.error('[Frontend] Invalid actions format:', actions);
        return;
    }
    
    if (actionArray.length === 0) {
        return;
    }
    
    const dictActions = actionArray.map(action => arrayToActionDict(action));
    
    const expandedActions = expandConnectToActions(dictActions);
    
    const optimizedActions = optimizeActionOrder(expandedActions);
    
    // Safety: if no actions remain after processing, don't lock the UI
    if (optimizedActions.length === 0) {
        return;
    }
    
    laneIdMap = {};
    
    const modeling = modeler.get('modeling');
    const elementFactory = modeler.get('elementFactory');
    const elementRegistry = modeler.get('elementRegistry');
    const canvas = modeler.get('canvas');
    
    const aiCursor = elAiCursor;
    if (aiCursor) aiCursor.classList.add('active');
    
    isExecutingActions = true;
    
    let delay = 0;
    const totalActions = optimizedActions.length;
    
    optimizedActions.forEach((action, index) => {
        setTimeout(() => {
            try {
                executeAction(action, modeling, elementFactory, elementRegistry, canvas, aiCursor);
            } catch (err) {
                console.error(`[Frontend] Error executing action ${index + 1}:`, err, action);
            }
            
            if (index === totalActions - 1) {
                // Wait 1500ms (> inner draw animation delay of 1200ms) so all
                // draw/participate inner setTimeout callbacks have fired and
                // bpmn.io has registered every element before we read the XML.
                setTimeout(() => {
                    if (!isModelingInProgress) {
                        aiCursor.classList.remove('active');
                        hideCursorThinking();
                        enableUIAfterModeling();
                    } else {
                        showCursorThinking();
                    }
                    
                    isExecutingActions = false;
                    
                    if (pendingContinuation && !isStopped) {
                        pendingContinuation = false;
                        setTimeout(() => continueAgent(), AGENT_CONTINUE_DELAY_MS);
                    }
                }, 1500);
            }
        }, delay);

        delay += 1000;
    });
}

function executeAction(action, modeling, elementFactory, elementRegistry, canvas, aiCursor) {
    try {
        if (action.parentId && laneIdMap[action.parentId]) {
            action.parentId = laneIdMap[action.parentId];
        }
        
        switch (action.type) {
            case 'delete':
                deleteElement(action, modeling, elementRegistry);
                break;
            
            case 'resize':
                resizeElement(action, modeling, elementRegistry, aiCursor);
                break;
            
            case 'move':
                moveElement(action, modeling, elementRegistry, aiCursor);
                break;
            
            case 'participate':
                participate(action, modeling, elementFactory, canvas, aiCursor, elementRegistry);
                break;
            
            case 'draw':
                draw(action, modeling, elementFactory, canvas, aiCursor, elementRegistry);
                break;
            
            case 'rename':
                rename(action, modeling, elementRegistry);
                break;
            
            case 'update':
                updateElement(action, modeling, elementRegistry);
                break;
            
            case 'connect':
                connectElements(action, modeling, elementRegistry, aiCursor);
                break;
            
            default:
                break;
        }
    } catch (err) {
        console.error('Error executing action:', err);
    }
}

function draw(action, modeling, elementFactory, canvas, aiCursor, elementRegistry) {
    animateCursor(aiCursor, action.x, action.y);
    
    setTimeout(() => {
        if (action.elementId) {
            const existingElement = elementRegistry.get(action.elementId);
            if (existingElement) {
                modeling.removeElements([existingElement]);
            }
        }
        
        const shapeConfig = {
            type: action.elementType
        };
        
        const isEvent = action.elementType && action.elementType.includes('Event');
        
        if (action.eventDefinition && isEvent) {
            shapeConfig.eventDefinitionType = action.eventDefinition;
        }
        
        const shape = elementFactory.createShape(shapeConfig);
        
        let parent = canvas.getRootElement();
        
        if (action.parentId) {
            const parentElement = elementRegistry.get(action.parentId);
            if (parentElement) {
                parent = parentElement;
            }
        } else {
            const allElements = elementRegistry.getAll();
            for (let element of allElements) {
                if (element.type === 'bpmn:Participant') {
                    const bounds = element;
                    if (action.x >= bounds.x && action.x <= bounds.x + bounds.width &&
                        action.y >= bounds.y && action.y <= bounds.y + bounds.height) {
                        parent = element;
                        break;
                    }
                }
            }
        }
        
        const createdShape = modeling.createShape(
            shape,
            { x: action.x, y: action.y },
            parent
        );
        
        if (action.eventDefinition && isEvent) {
            const bpmnFactory = modeler.get('bpmnFactory');
            const eventDefinition = bpmnFactory.create(action.eventDefinition);
            
            modeling.updateProperties(createdShape, {
                eventDefinitions: [eventDefinition]
            });
        }
        
        if (action.label) {
            modeling.updateLabel(createdShape, action.label);
        }
        
        if (action.elementId) {
            modeling.updateProperties(createdShape, {
                id: action.elementId
            });
        }
    }, 1200);
}

function participate(action, modeling, elementFactory, canvas, aiCursor, elementRegistry) {
    animateCursor(aiCursor, action.x + action.width / 2, action.y + action.height / 2);
    
    setTimeout(() => {
        if (action.elementId) {
            const existingElement = elementRegistry.get(action.elementId);
            if (existingElement) {
                modeling.removeElements([existingElement]);
            }
        }
        
        const isExpanded = action.isExpanded !== undefined ? action.isExpanded : true;
        
        const participant = elementFactory.createParticipantShape({
            type: 'bpmn:Participant',
            isExpanded: isExpanded
        });
        
        const createdParticipant = modeling.createShape(
            participant,
            { 
                x: action.x + action.width / 2, 
                y: action.y + action.height / 2 
            },
            canvas.getRootElement()
        );
        
        modeling.resizeShape(createdParticipant, {
            x: action.x,
            y: action.y,
            width: action.width,
            height: action.height
        });
        
        if (action.label) {
            modeling.updateLabel(createdParticipant, action.label);
        }
        
        if (action.elementId) {
            modeling.updateProperties(createdParticipant, {
                id: action.elementId
            });
        }
        
        // Inline lane creation — split if lanes list has ≥2 entries
        const laneLabelList = Array.isArray(action.lanes) ? action.lanes.filter(l => l) : [];
        if (laneLabelList.length >= 2) {
            modeling.splitLane(createdParticipant, laneLabelList.length);
            const laneElements = createdParticipant.children.filter(
                child => child.type === 'bpmn:Lane'
            );
            laneElements.forEach((laneShape, index) => {
                const rawLabel = String(laneLabelList[index] || `Lane${index}`);
                const sanitized = rawLabel
                    .replace(/[^a-zA-Z0-9\s]/g, '')
                    .trim()
                    .split(/\s+/)
                    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
                    .join('');
                const laneId = `Lane${sanitized}`;
                
                modeling.updateProperties(laneShape, { name: rawLabel });
                
                try {
                    laneShape.businessObject.id = laneId;
                    elementRegistry.updateId(laneShape, laneId);
                } catch (e) {
                    console.warn('Could not update lane ID:', e);
                }
                
                laneIdMap[laneId] = laneShape.id;
                laneIdMap[`${action.elementId}_${index}`] = laneShape.id;
            });
        }
        
    }, 1200);
}

function splitLanes(action, modeling, elementRegistry, aiCursor) {
    try {
        const participant = elementRegistry.get(action.participantId);
        
        if (!participant) {
            console.error('Participant not found:', action.participantId);
            return;
        }
        
        if (participant.type !== 'bpmn:Participant') {
            console.error('Element is not a participant:', action.participantId);
            return;
        }
        
        // Support both new format (lanes: [{label, id}, ...]) and old format (labels: [str, ...])
        let lanePairs = [];
        if (action.lanes && Array.isArray(action.lanes) && action.lanes.length >= 2) {
            // New format: [{label: '...', id: '...'}, ...] or [[label, id], ...]
            for (const entry of action.lanes) {
                if (Array.isArray(entry) && entry.length >= 2) {
                    lanePairs.push({ label: String(entry[0]), id: String(entry[1]) });
                } else if (entry && typeof entry === 'object') {
                    lanePairs.push({ label: String(entry.label || ''), id: String(entry.id || '') });
                } else if (typeof entry === 'string') {
                    lanePairs.push({ label: entry, id: '' });
                }
            }
        } else if (action.labels && Array.isArray(action.labels) && action.labels.length >= 2) {
            // Old format: plain label strings
            lanePairs = action.labels.map(l => ({ label: String(l), id: '' }));
        } else {
            console.error('Invalid lanes/labels. Must have at least 2 entries:', action);
            return;
        }
        
        modeling.splitLane(participant, lanePairs.length);
        
        const lanes = participant.children.filter(child => child.type === 'bpmn:Lane');
        
        lanes.forEach((laneShape, index) => {
            const pair = lanePairs[index];
            if (!pair) return;
            
            // Set lane name
            if (pair.label) {
                modeling.updateProperties(laneShape, { name: pair.label });
            }
            
            // Determine ID: use explicit id if provided, otherwise auto-generate from label
            let meaningfulId;
            if (pair.id) {
                meaningfulId = pair.id;
            } else {
                const sanitized = (pair.label || `Lane${index}`)
                    .replace(/[^a-zA-Z0-9\s]/g, '')
                    .trim()
                    .split(/\s+/)
                    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
                    .join('');
                meaningfulId = `Lane${sanitized}`;
            }
            
            // Update the element ID in registry and business object
            try {
                laneShape.businessObject.id = meaningfulId;
                elementRegistry.updateId(laneShape, meaningfulId);
            } catch (e) {
                console.warn('Could not update lane ID:', e);
            }
            
            // Store both old-style and new-style mappings for parent resolution
            const tempId = `${action.participantId}_${index}`;
            laneIdMap[tempId] = laneShape.id;
            if (pair.id) {
                laneIdMap[pair.id] = laneShape.id;  // identity mapping for explicit IDs
            }
        });
        
    } catch (err) {
        console.error('Error splitting lanes:', err);
    }
}

function connectElements(action, modeling, elementRegistry, aiCursor) {
    setTimeout(() => {
        const source = elementRegistry.get(action.sourceId);
        const target = elementRegistry.get(action.targetId);
        
        if (source && target) {
            const existingConnections = elementRegistry.filter(element => {
                if (element.type === 'bpmn:SequenceFlow' || element.type === 'bpmn:MessageFlow') {
                    if (element.source && element.target) {
                        return (element.source.id === action.sourceId && element.target.id === action.targetId);
                    }
                }
                return false;
            });
            
            if (existingConnections.length > 0) {
                existingConnections.forEach(conn => {
                    modeling.removeElements([conn]);
                });
            }
            
            const sourcePos = { x: source.x + source.width / 2, y: source.y + source.height / 2 };
            const targetPos = { x: target.x + target.width / 2, y: target.y + target.height / 2 };
            const midX = (sourcePos.x + targetPos.x) / 2;
            const midY = (sourcePos.y + targetPos.y) / 2;
            
            animateCursor(aiCursor, midX, midY);
            
            setTimeout(() => {
                function findTopLevelPool(element) {
                    if (element.type === 'bpmn:Participant') {
                        return element;
                    }
                    
                    let current = element;
                    
                    while (current) {
                        if (current.parent && current.parent.type === 'bpmn:Participant') {
                            return current.parent;
                        }
                        current = current.parent;
                    }
                    
                    return null;
                }
                
                const sourcePool = findTopLevelPool(source);
                const targetPool = findTopLevelPool(target);
                
                let flowType = 'bpmn:SequenceFlow';
                
                if (sourcePool && targetPool && sourcePool.id !== targetPool.id) {
                    flowType = 'bpmn:MessageFlow';
                }
                else if ((sourcePool && !targetPool) || (!sourcePool && targetPool)) {
                    flowType = 'bpmn:MessageFlow';
                }
                
                const connection = modeling.connect(source, target, { type: flowType });
                const flowId = `${action.sourceId}_${action.targetId}_flow`;
                modeling.updateProperties(connection, { id: flowId });
                
                if (action.label) {
                    modeling.updateLabel(connection, action.label);
                }
            }, 800);
        }
    }, 500);
}

function rename(action, modeling, elementRegistry) {
    const element = elementRegistry.get(action.elementId);
    
    if (element) {
        modeling.updateLabel(element, action.label);
    }
}

function updateElement(action, modeling, elementRegistry) {
    const element = elementRegistry.get(action.elementId);
    if (!element) {
        console.warn('[update] Element not found:', action.elementId);
        return;
    }

    const property = action.property;
    const value = action.value;

    if (property === 'type') {
        // Replace element type while preserving all connections
        const bpmnType = (typeof value === 'string' && value.startsWith('bpmn:')) ? value : `bpmn:${value}`;
        try {
            const bpmnReplace = modeler.get('bpmnReplace');
            bpmnReplace.replaceElement(element, { type: bpmnType });
        } catch (err) {
            console.error('[update] Failed to replace element type:', err);
        }
    } else if (property === 'eventDefinition') {
        const bpmnFactory = modeler.get('bpmnFactory');
        if (!value || value === 'null' || value === 'none') {
            modeling.updateProperties(element, { eventDefinitions: [] });
        } else {
            const defType = (typeof value === 'string' && value.startsWith('bpmn:')) ? value : `bpmn:${value}`;
            try {
                const eventDef = bpmnFactory.create(defType);
                modeling.updateProperties(element, { eventDefinitions: [eventDef] });
            } catch (err) {
                console.error('[update] Failed to set eventDefinition:', err);
            }
        }
    } else {
        console.warn('[update] Unsupported property:', property);
    }
}

function moveElement(action, modeling, elementRegistry, aiCursor) {
    const element = elementRegistry.get(action.elementId);
    
    if (element) {
        animateCursor(aiCursor, action.x, action.y);
        
        setTimeout(() => {
            modeling.moveElements([element], { x: action.x - element.x, y: action.y - element.y });
        }, 1200);
    }
}

function resizeElement(action, modeling, elementRegistry, aiCursor) {
    const element = elementRegistry.get(action.elementId);
    
    if (element) {
        const centerX = element.x + element.width / 2;
        const centerY = element.y + element.height / 2;
        animateCursor(aiCursor, centerX, centerY);
        
        setTimeout(() => {
            const newBounds = {
                x: element.x,
                y: element.y,
                width: action.width,
                height: action.height
            };
            
            modeling.resizeShape(element, newBounds);
        }, 1200);
    }
}

function deleteElement(action, modeling, elementRegistry) {
    const element = elementRegistry.get(action.elementId);
    
    if (element) {
        modeling.removeElements([element]);
    }
}

function animateCursor(cursor, bpmnX, bpmnY) {
    if (!cursor || !modeler) return;
    
    try {
        const canvas = modeler.get('canvas');
        const viewbox = canvas.viewbox();
        
        const scale = viewbox.scale;
        const canvasX = (bpmnX - viewbox.x) * scale;
        const canvasY = (bpmnY - viewbox.y) * scale;
        
        const bpmnContainer = document.querySelector('.bpmn-container');
        const canvasElement = document.querySelector('#bpmn-canvas');
        
        if (!bpmnContainer || !canvasElement) {
            return;
        }
        
        const containerRect = bpmnContainer.getBoundingClientRect();
        const canvasRect = canvasElement.getBoundingClientRect();
        
        const finalX = (canvasRect.left - containerRect.left) + canvasX;
        const finalY = (canvasRect.top - containerRect.top) + canvasY;
        
        cursor.style.left = finalX + 'px';
        cursor.style.top = finalY + 'px';
        
    } catch (err) {
        console.error('Error animating cursor:', err);
    }
}

function requestCompletion() {
    const completeBtn = document.getElementById('completeTaskBtn');
    const completeText = document.getElementById('completeText');
    const completeSpinner = document.getElementById('completeSpinner');
    
    completeBtn.disabled = true;
    completeText.style.display = 'none';
    completeSpinner.style.display = 'inline-block';
    
    disableChatInput();
    
    showTypingIndicator();
    
    getBPMNXML().then(xml => {
        socket.emit('request_completion', {
            task_id: TASK_ID,
            ai_type: AI_TYPE,
            bpmn_xml: xml
        });
    });
}

function cancelCompletion() {
    document.getElementById('completionConfirmModal').style.display = 'none';
    enableCompleteButton();
    enableChatInput();
}

function confirmCompletion() {
    document.getElementById('completionConfirmModal').style.display = 'none';
    completeTask();
}

function enableCompleteButton() {
    const completeBtn = document.getElementById('completeTaskBtn');
    const completeText = document.getElementById('completeText');
    const completeSpinner = document.getElementById('completeSpinner');
    
    if (completeBtn) {
        completeBtn.disabled = false;
        completeText.style.display = 'inline';
        completeSpinner.style.display = 'none';
    }
}

function disableCompleteButton() {
    const completeBtn = document.getElementById('completeTaskBtn');
    const completeText = document.getElementById('completeText');
    const completeSpinner = document.getElementById('completeSpinner');
    
    if (completeBtn) {
        completeBtn.disabled = true;
        completeText.style.display = 'none';
        completeSpinner.style.display = 'inline-block';
    }
}

function disableUIWhileModeling() {
    const completeBtn = document.getElementById('completeTaskBtn');
    if (completeBtn) {
        completeBtn.disabled = true;
    }
    
    const exportBtn = document.getElementById('exportBtn');
    if (exportBtn) {
        exportBtn.disabled = true;
        exportBtn.style.opacity = '0.5';
        exportBtn.style.cursor = 'not-allowed';
    }
    
    if (elSendBtn) elSendBtn.disabled = true;
    if (elChatInput) {
        elChatInput.disabled = true;
        elChatInput.placeholder = 'Please wait while modeling...';
    }
}

function enableUIAfterModeling() {
    const completeBtn = document.getElementById('completeTaskBtn');
    const completeText = document.getElementById('completeText');
    const completeSpinner = document.getElementById('completeSpinner');
    if (completeBtn) {
        completeBtn.disabled = false;
        if (completeText) completeText.style.display = 'inline';
        if (completeSpinner) completeSpinner.style.display = 'none';
    }
    
    const exportBtn = document.getElementById('exportBtn');
    if (exportBtn) {
        exportBtn.disabled = false;
        exportBtn.style.opacity = '1';
        exportBtn.style.cursor = 'pointer';
    }
    
    if (elSendBtn) elSendBtn.disabled = false;
    if (elChatInput) {
        elChatInput.disabled = false;
        elChatInput.placeholder = 'Type your message...';
    }
    
    hideStopButton();
}

function disableChatInput() {
    if (elChatInput) elChatInput.disabled = true;
    if (elSendBtn) elSendBtn.disabled = true;
}

async function completeTask() {
    const completeBtn = document.getElementById('completeTaskBtn');
    const completeText = document.getElementById('completeText');
    const completeSpinner = document.getElementById('completeSpinner');
    
    try {
        if (completeBtn) completeBtn.disabled = true;
        if (completeText) completeText.style.display = 'none';
        if (completeSpinner) completeSpinner.style.display = 'inline-block';
        
        const xml = await getBPMNXML();
        
        const response = await fetch('/api/save-bpmn', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                task_id: TASK_ID,
                bpmn_xml: xml
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            window.location.href = '/';
        } else {
            alert('Error completing task: ' + (data.message || 'Unknown error'));
        }
    } catch (err) {
        console.error('Error completing task:', err);
        alert('Error completing task. Please try again.');
    } finally {
        if (completeBtn) completeBtn.disabled = false;
        if (completeText) completeText.style.display = 'inline';
        if (completeSpinner) completeSpinner.style.display = 'none';
    }
}

async function exportBPMN() {
    const xml = await getBPMNXML();
    
    const blob = new Blob([xml], { type: 'application/xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${TASK_ID}.bpmn`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

let currentZoom = 0.9;
const ZOOM_STEP = 0.1;
const MIN_ZOOM = 0.3;
const MAX_ZOOM = 3.0;

function updateZoomLevel() {
    const zoomPercent = Math.round(currentZoom * 100);
    document.getElementById('zoomLevel').textContent = zoomPercent + '%';
    
    const zoomInBtn = document.getElementById('zoomInBtn');
    const zoomOutBtn = document.getElementById('zoomOutBtn');
    
    if (zoomInBtn && zoomOutBtn) {
        zoomInBtn.disabled = currentZoom >= MAX_ZOOM;
        zoomOutBtn.disabled = currentZoom <= MIN_ZOOM;
    }
}

function zoomIn() {
    if (currentZoom < MAX_ZOOM) {
        currentZoom = Math.min(currentZoom + ZOOM_STEP, MAX_ZOOM);
        applyZoom();
    }
}

function zoomOut() {
    if (currentZoom > MIN_ZOOM) {
        currentZoom = Math.max(currentZoom - ZOOM_STEP, MIN_ZOOM);
        applyZoom();
    }
}

function applyZoom() {
    if (modeler) {
        const canvas = modeler.get('canvas');
        canvas.zoom(currentZoom, 'auto');
        updateZoomLevel();
    }
}

let currentIssues = [];
let issueOverlays = [];
let activeIssuePopup = null;

function displayIssues(issues) {
    currentIssues = issues;
    
    clearIssues();
    
    if (!modeler) {
        return;
    }
    
    const overlays = modeler.get('overlays');
    const elementRegistry = modeler.get('elementRegistry');
    
    createIssueSummary(issues);
    
    issues.forEach((issue, index) => {
        addIssueOverlay(issue, index, overlays, elementRegistry);
    });
}

function addIssueOverlay(issue, index, overlays, elementRegistry) {
    const element = elementRegistry.get(issue.elementId);
    if (!element) {
        return;
    }
    
    const severity = issue.severity.toLowerCase();
    const isConnection = element.waypoints && element.waypoints.length > 0;
    
    const overlayHtml = document.createElement('div');
    
    if (isConnection) {
        overlayHtml.className = `issue-overlay-flow`;
    } else {
        overlayHtml.className = `issue-overlay-box`;
        overlayHtml.style.width = `${element.width + 10}px`;
        overlayHtml.style.height = `${element.height + 10}px`;
    }
    
    const badge = document.createElement('div');
    badge.className = `issue-badge ${severity}`;
    badge.innerHTML = '!';
    badge.dataset.issueIndex = index;
    
    badge.addEventListener('mouseenter', (e) => showIssueHoverTooltip(issue, e));
    badge.addEventListener('mouseleave', hideIssueHoverTooltip);
    
    badge.addEventListener('click', (e) => {
        e.stopPropagation();
        showIssueDetailPopup(issue, index, e);
    });
    
    overlayHtml.appendChild(badge);
    
    let overlayPosition;
    if (isConnection) {
        const wp = element.waypoints;
        const midIdx = Math.floor(wp.length / 2);
        const midPoint = wp[midIdx];
        const sourceX = wp[0].x;
        const sourceY = wp[0].y;
        overlayPosition = {
            top: midPoint.y - sourceY - 12,
            left: midPoint.x - sourceX - 12
        };
    } else {
        overlayPosition = { top: -5, left: -5 };
    }
    
    try {
        const overlayId = overlays.add(issue.elementId, `issue-${severity}`, {
            position: overlayPosition,
            html: overlayHtml
        });
        
        issueOverlays.push({
            id: overlayId,
            elementId: issue.elementId
        });
        
    } catch (err) {
        console.error(`[Issues] Failed to add overlay to ${issue.elementId}:`, err);
    }
}

function showIssueHoverTooltip(issue, event) {
    hideIssueHoverTooltip();
    
    const tooltip = document.createElement('div');
    tooltip.id = 'issueHoverTooltip';
    tooltip.className = `issue-hover-tooltip ${issue.severity.toLowerCase()}`;
    tooltip.textContent = issue.shortDesc || issue.message || 'Issue detected';
    
    const bpmnContainer = document.getElementById('bpmn-container');
    if (!bpmnContainer) return;
    
    bpmnContainer.appendChild(tooltip);
    
    const rect = event.target.getBoundingClientRect();
    const containerRect = bpmnContainer.getBoundingClientRect();
    
    let tooltipX = rect.right - containerRect.left + 10;
    let tooltipY = rect.top - containerRect.top;
    
    tooltip.style.left = `${tooltipX}px`;
    tooltip.style.top = `${tooltipY}px`;
    
    requestAnimationFrame(() => {
        const tooltipRect = tooltip.getBoundingClientRect();
        if (tooltipRect.right > containerRect.right) {
            tooltipX = rect.left - containerRect.left - tooltipRect.width - 10;
            tooltip.style.left = `${tooltipX}px`;
        }
        tooltip.classList.add('visible');
    });
}

function hideIssueHoverTooltip() {
    const existing = document.getElementById('issueHoverTooltip');
    if (existing) {
        existing.remove();
    }
}

function showIssueDetailPopup(issue, issueIndex, event) {
    closeIssueDetailPopup();
    
    const backdrop = document.createElement('div');
    backdrop.className = 'issue-popup-backdrop';
    backdrop.id = 'issuePopupBackdrop';
    backdrop.addEventListener('click', closeIssueDetailPopup);
    document.body.appendChild(backdrop);
    
    const popup = document.createElement('div');
    popup.className = 'issue-detail-popup';
    popup.id = 'issueDetailPopup';
    
    const severity = issue.severity.toLowerCase();
    const severityIcons = {
        critical: '⛔',
        warning: '⚠️',
        info: 'ℹ️'
    };
    const severityLabels = {
        critical: 'Critical Issue',
        warning: 'Warning',
        info: 'Information'
    };
    
    popup.innerHTML = `
        <div class="issue-detail-popup-header ${severity}">
            <div class="issue-detail-popup-title">
                <span class="severity-icon">${severityIcons[severity] || '!'}</span>
                <span class="severity-label">${severityLabels[severity] || 'Issue'}</span>
            </div>
            <button class="issue-detail-popup-close" onclick="closeIssueDetailPopup()">×</button>
        </div>
        <div class="issue-detail-popup-body">
            <div class="issue-detail-short">${formatMarkdown(issue.shortDesc || 'Issue detected')}</div>
            <div class="issue-detail-long">${formatMarkdown(issue.longDesc || issue.message || 'No additional details available.')}</div>
            <div class="issue-detail-meta">
                <div class="issue-detail-meta-item">
                    <span class="meta-label">Element:</span>
                    <span>${issue.elementId}</span>
                </div>
                <div class="issue-detail-meta-item">
                    <span class="meta-label">Category:</span>
                    <span>${issue.category || 'General'}</span>
                </div>
            </div>
        </div>
        <div class="issue-popup-footer">
            <button class="issue-action-btn ignore .btn-primary" id="issueIgnoreBtn">Ignore</button>
            <button class="issue-action-btn fix" id="issueFixBtn">Confirm</button>
        </div>
    `;
    
    document.body.appendChild(popup);
    
    document.getElementById('issueIgnoreBtn').addEventListener('click', (e) => {
        e.stopPropagation();
        ignoreIssue(issueIndex);
    });
    document.getElementById('issueFixBtn').addEventListener('click', (e) => {
        e.stopPropagation();
        fixIssue(issue);
    });
    
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const popupRect = popup.getBoundingClientRect();
    
    let left = event.clientX + 20;
    let top = event.clientY - 20;
    
    if (left + popupRect.width > viewportWidth - 20) {
        left = event.clientX - popupRect.width - 20;
    }
    if (top + popupRect.height > viewportHeight - 20) {
        top = viewportHeight - popupRect.height - 20;
    }
    if (top < 20) {
        top = 20;
    }
    
    popup.style.left = `${left}px`;
    popup.style.top = `${top}px`;
    
    activeIssuePopup = popup;
    
    highlightElement(issue.elementId);
}

function closeIssueDetailPopup() {
    const popup = document.getElementById('issueDetailPopup');
    const backdrop = document.getElementById('issuePopupBackdrop');
    
    if (popup) popup.remove();
    if (backdrop) backdrop.remove();
    
    activeIssuePopup = null;
}

function ignoreIssue(issueIndex) {
    const issue = currentIssues[issueIndex];
    if (!issue) return;
    closeIssueDetailPopup();
    
    // Remove the overlay from the canvas
    const overlay = issueOverlays[issueIndex];
    if (overlay && modeler) {
        try { modeler.get('overlays').remove(overlay.id); } catch (e) {}
    }
    
    currentIssues.splice(issueIndex, 1);
    issueOverlays.splice(issueIndex, 1);
    
    // Tell backend so the AI forgets this issue
    socket.emit('ignore_issue', { task_id: TASK_ID, issue_index: issueIndex });
    
    createIssueSummary(currentIssues);
}

function fixIssue(issue) {
    closeIssueDetailPopup();
    
    showStopButton();
    showTypingIndicator();
    isModelingInProgress = true;
    disableUIWhileModeling();
    
    getBPMNXML().then(xml => {
        socket.emit('fix_issue', {
            task_id: TASK_ID,
            issue: issue,
            bpmn_xml: xml
        });
    }).catch(err => console.error('[Frontend] Could not read BPMN XML for fix:', err));
}

function createIssueSummary(issues) {
    const bpmnContainer = document.getElementById('bpmn-container');
    if (!bpmnContainer) return;
    
    const existing = document.getElementById('issueSummary');
    if (existing) existing.remove();
    
    const counts = {
        critical: 0,
        warning: 0,
        info: 0
    };
    
    issues.forEach(issue => {
        const severity = issue.severity.toLowerCase();
        if (counts.hasOwnProperty(severity)) {
            counts[severity]++;
        }
    });
    
    const summary = document.createElement('div');
    summary.className = 'annotation-summary';
    summary.id = 'issueSummary';
    summary.innerHTML = `
        <div class="annotation-summary-title">Review Findings</div>
        <div class="annotation-summary-counts">
            ${counts.critical > 0 ? `
            <div class="annotation-count-row">
                <span class="annotation-count-label">
                    <span class="annotation-count-dot critical"></span>
                    Critical
                </span>
                <span class="annotation-count-number">${counts.critical}</span>
            </div>` : ''}
            ${counts.warning > 0 ? `
            <div class="annotation-count-row">
                <span class="annotation-count-label">
                    <span class="annotation-count-dot warning"></span>
                    Warning
                </span>
                <span class="annotation-count-number">${counts.warning}</span>
            </div>` : ''}
            ${counts.info > 0 ? `
            <div class="annotation-count-row">
                <span class="annotation-count-label">
                    <span class="annotation-count-dot info"></span>
                    Info
                </span>
                <span class="annotation-count-number">${counts.info}</span>
            </div>` : ''}
        </div>
    `;
    
    bpmnContainer.appendChild(summary);
}

function clearIssues() {
    closeIssueDetailPopup();
    hideIssueHoverTooltip();
    
    if (modeler) {
        try {
            const overlays = modeler.get('overlays');
            issueOverlays.forEach(overlay => {
                try {
                    overlays.remove(overlay.id);
                } catch (e) {
                }
            });
        } catch (e) {
        }
    }
    
    issueOverlays = [];
    currentIssues = [];
    
    const summary = document.getElementById('issueSummary');
    if (summary) summary.remove();
}



function highlightElement(elementId) {
    if (!modeler) return;
    
    const elementRegistry = modeler.get('elementRegistry');
    const canvas = modeler.get('canvas');
    
    const element = elementRegistry.get(elementId);
    if (!element) return;
    
    document.querySelectorAll('.bpmn-element-highlighted').forEach(el => {
        el.classList.remove('bpmn-element-highlighted');
    });
    
    const gfx = elementRegistry.getGraphics(element);
    if (gfx) {
        gfx.classList.add('bpmn-element-highlighted');
        
        setTimeout(() => {
            gfx.classList.remove('bpmn-element-highlighted');
        }, 3000);
    }
    
    canvas.scrollToElement(element);
}



function continueAgent() {
    showTypingIndicator();
    getBPMNXML().then(xml => {
        socket.emit('agent_continue', {
            task_id: TASK_ID,
            bpmn_xml: xml,
            ai_type: AI_TYPE,
            last_phase: lastAgentPhase
        });
        lastAgentPhase = '';
    }).catch(err => console.error('[Frontend] Could not read BPMN XML for agent continue:', err));
}

// ─── Agent Plan Panel ────────────────────────────────────────────────
function updatePlanPanel(plan, currentStep, stepStatus, phase) {
    const panel = document.getElementById('agentPlanPanel');
    if (!panel) return;

    panel.style.display = 'block';

    // Update phase badge
    const phaseBadge = document.getElementById('phaseBadge');
    if (phaseBadge) {
        phaseBadge.textContent = phase || '—';
        phaseBadge.className = 'phase-badge phase-' + (phase || '').toLowerCase();
    }

    const container = document.getElementById('planSteps');
    if (!container) return;

    container.innerHTML = '';

    plan.forEach(item => {
        const stepDiv = document.createElement('div');
        stepDiv.className = 'plan-step';

        // Determine icon and state class
        let icon = '○';
        let stateClass = 'step-pending';
        if (item.status === 'complete') {
            icon = '✓';
            stateClass = 'step-complete';
        } else if (item.status === 'in_progress' || item.id === currentStep) {
            icon = '◉';
            stateClass = 'step-active';
        }

        stepDiv.classList.add(stateClass);
        const label = item.label || item.title || `Goal ${item.id || ''}`;
        const description = item.instruction || item.description || '';
        stepDiv.title = description; // tooltip with full description
        stepDiv.innerHTML = `
            <span class="step-icon">${icon}</span>
            <span class="step-title">${label}</span>
        `;
        container.appendChild(stepDiv);
    });
}

// ── Custom Task ───────────────────────────────────────────────────────────────

var _customFileContent = '';

function handleCustomFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    const uploadBtn = document.getElementById('customUploadBtn');
    if (uploadBtn) uploadBtn.textContent = '📎 ' + file.name;

    const formData = new FormData();
    formData.append('file', file);

    fetch('/api/extract-file-content', { method: 'POST', body: formData })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                _customFileContent = data.content || '';
            } else {
                alert('Error reading file: ' + (data.message || 'Unknown error'));
                _customFileContent = '';
                if (uploadBtn) uploadBtn.textContent = '📎 Upload Document';
                const fileInput = document.getElementById('customFileInput');
                if (fileInput) fileInput.value = '';
            }
        })
        .catch(() => {
            alert('File could not be uploaded.');
            _customFileContent = '';
            if (uploadBtn) uploadBtn.textContent = '📎 Upload Document';
        });
}

function confirmCustomTask() {
    const textarea = document.getElementById('customTaskTextarea');
    const typed = textarea ? textarea.value.trim() : '';
    const parts = [];
    if (typed) parts.push(typed);
    if (_customFileContent.trim()) parts.push(_customFileContent.trim());

    const description = parts.join('\n\n');
    if (!description) {
        alert('Please enter a task description or upload a document.');
        return;
    }

    // Tell the backend the custom description
    socket.emit('set_custom_task', { task_id: TASK_ID, description: description });

    // Swap buttons: hide custom, show normal
    const customUploadBtn = document.getElementById('customUploadBtn');
    const customConfirmBtn = document.getElementById('customConfirmBtn');
    if (customUploadBtn) customUploadBtn.style.display = 'none';
    if (customConfirmBtn) customConfirmBtn.style.display = 'none';
    const exportBtn = document.getElementById('exportBtn');
    const completeTaskBtn = document.getElementById('completeTaskBtn');
    if (exportBtn) exportBtn.style.display = '';
    if (completeTaskBtn) completeTaskBtn.style.display = '';

    // Restore scroll on task-content so description can scroll
    const taskContent = document.querySelector('.task-content');
    if (taskContent) taskContent.classList.remove('custom-mode');

    // Hide form, show task info
    const setup = document.getElementById('customTaskSetup');
    if (setup) setup.style.display = 'none';

    const titleEl = document.getElementById('taskTitle');
    if (titleEl) {
        titleEl.textContent = 'Custom Task';
        titleEl.style.display = '';
    }

    const descEl = document.getElementById('taskDescription');
    if (descEl) {
        descEl.innerHTML = description.replace(/\n/g, '<br>');
        descEl.style.display = '';
    }

    // Now trigger the initial greeting (worker analyzes the task)
    requestInitialGreeting();
}

document.addEventListener('DOMContentLoaded', () => {
    elAiCursor = document.getElementById('aiCursor');
    elSendBtn = document.getElementById('sendBtn');
    elSendText = document.getElementById('sendText');
    elSendSpinner = document.getElementById('sendSpinner');
    elChatInput = document.getElementById('chatInput');
    elChatMessages = document.getElementById('chatMessages');

    initBPMN();
    updateZoomLevel();
    initWebSocket();
    
    // Show typing indicator immediately for non-custom tasks so the user sees
    // activity right away, before the socket round-trip for the greeting completes.
    if (!IS_CUSTOM) {
        showStopButton();
        showTypingIndicator();
        disableUIWhileModeling();
        isModelingInProgress = true;
    }
    
    setTimeout(() => {
        if (modeler) {
            const eventBus = modeler.get('eventBus');
            
            eventBus.on('commandStack.changed', () => {
                if (!isExecutingActions && currentIssues.length > 0) {
                    clearIssues();
                }
            });
        }
    }, MODELER_INIT_DELAY_MS);
    
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && activeIssuePopup) {
            closeIssueDetailPopup();
        }
    });
});

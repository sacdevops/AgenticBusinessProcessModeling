"""
Benchmark Prompts Module

Contains all prompt templates specific to benchmark evaluation.
Imports shared blocks (GENERAL_RULES, BPMN_STANDARDS, etc.) from the central prompts module.
"""

import sys
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from prompts import (
    GENERAL_RULES,
    BPMN_STANDARDS,
    BPMN_ELEMENTS_REFERENCE,
    ACTION_TYPES_REFERENCE,
    LION_FORMAT_RULES
)

# ============================================================================
# 1. BENCHMARK-SPECIFIC BLOCKS
# ============================================================================

ONE_SHOT_RULES = """
Single-Response Modeling Rules
- You MUST model the ENTIRE process in this ONE response — there are no follow-up turns
- Analyze the full task description before writing any output
- Plan the complete model mentally first: all participants, pools, lanes, elements, and flows
- Never ask questions or request clarification — infer from context and decide yourself
- Use meaningful, readable IDs (e.g., TaskReviewClaim, GwApproved, StartOrderReceived)
- Follow all layout rules strictly: left-to-right flow, no overlapping elements, parallel branches offset on Y-axis

Self-Check Before Output
1. Every EXPANDED pool has exactly one StartEvent and at least one EndEvent?
2. Every COLLAPSED pool has NO internal elements — only message flows to/from the pool ID?
3. All sequence flows are within the same pool; cross-pool connections use message flows?
4. Every gateway has at least 3 connected flows (e.g., 1 incoming + 2 outgoing)?
5. Exclusive/Inclusive gateway outgoing branches are labeled with conditions?
6. No isolated elements; every element reachable from StartEvent and leading to EndEvent?
7. If lanes are used: pool has ≥2 lanes (single-lane pools are invalid BPMN)?
8. All elements have a valid parent pool or lane ID?
9. Coordinates are plausible — elements inside their parent pool bounds, no overlaps?
10. Message-related events/tasks have the correct event type specified?
"""

ACTION_TYPES_REFERENCE_JSON = """
Action Types (JSON format)
- "participate": create pools — always do this FIRST before drawing any elements
    Fields: x, y, w (width), h (height), label, id, expanded (true/false), lanes (list of lane labels or [])
    lanes: provide ≥2 label strings to create lanes (e.g. ["Barista", "Manager"]) — lane IDs are auto-derived:
      "Claims Handler" → "LaneClaimsHandler", "Accounting" → "LaneAccounting"
    Use exactly these derived IDs as "parent" when drawing elements inside that lane.
    Leave lanes as [] if no lanes are needed.

- "draw": draw an element
    Fields: type, x, y, label, id, parent (pool or lane ID), connectTo (list of target IDs for same-pool sequence flows), eventDef

- "connect": create a connection between any two elements
    Automatically MessageFlow if source and target are in different pools; SequenceFlow if same pool.
    For collapsed pools: connect directly to the pool ID.
    Fields: src, tgt, label (optional — use for gateway branch conditions)

- "delete": ["id1", "id2"] — delete elements by ID
- "rename": [{"id": ..., "label": ...}] — rename an element
- "move": [{"id": ..., "x": ..., "y": ...}] — move an element

Key Rules
- Use "connectTo" in draw ONLY for same-pool sequence flows (shorthand at creation time)
- Use "connect" for ALL cross-pool message flows and for gateway condition labels
- NEVER use "connectTo" for cross-pool connections — always use "connect"
- "eventDef": "MessageEventDefinition" | "TimerEventDefinition" | "SignalEventDefinition" |
  "ErrorEventDefinition" | "TerminateEventDefinition" | "ConditionalEventDefinition" — or omit/null for plain events

Coordinates and Layout
- First pool: x=160, y=80
- Subsequent pools: y = previous_pool_y + previous_pool_h + 50
- Typical pool dimensions: 1200–1600px wide, 200–400px tall
- Elements at least 100px from pool edges; minimum 150px horizontal spacing between elements
- Parallel branches offset on Y-axis by ≈120px so they don't overlap
- Lane IDs: derive by removing non-alphanumeric chars from label, capitalizing each word, prefixing "Lane"
  e.g. "Claims Handler" → LaneClaimsHandler, "IT Support" → LaneItSupport
"""

JSON_EXAMPLES = """
JSON Response Examples

Example — Two expanded pools, event-based gateway, typed events, cross-pool message flows:
{
  "message": "Modeled the café ordering process: expanded Customer pool with event-based gateway routing between rejection and drink-received; expanded Barista pool with availability check, preparation, and payment.",
  "actions": {
    "participate": [
      {"x": 160, "y": 80, "w": 1028, "h": 270, "label": "Customer", "id": "PoolCustomer", "expanded": true, "lanes": []},
      {"x": 160, "y": 400, "w": 1028, "h": 340, "label": "Barista", "id": "PoolBarista", "expanded": true, "lanes": []}
    ],
    "draw": [
      {"type": "StartEvent", "x": 222, "y": 192, "label": "Enter café", "id": "StartEnterCafe", "parent": "PoolCustomer", "connectTo": ["TaskPlaceOrder"]},
      {"type": "SendTask", "x": 310, "y": 170, "label": "Place order", "id": "TaskPlaceOrder", "parent": "PoolCustomer", "connectTo": ["GwEventBased"]},
      {"type": "EventBasedGateway", "x": 465, "y": 185, "label": null, "id": "GwEventBased", "parent": "PoolCustomer", "connectTo": []},
      {"type": "IntermediateCatchEvent", "x": 572, "y": 122, "label": "Rejection received", "id": "CatchRejection", "parent": "PoolCustomer", "connectTo": ["EndOrderCancelled"], "eventDef": "MessageEventDefinition"},
      {"type": "EndEvent", "x": 672, "y": 122, "label": "Order cancelled", "id": "EndOrderCancelled", "parent": "PoolCustomer", "connectTo": []},
      {"type": "IntermediateCatchEvent", "x": 622, "y": 272, "label": "Drink received", "id": "CatchDrinkReceived", "parent": "PoolCustomer", "connectTo": ["EndDrinkPaid"], "eventDef": "MessageEventDefinition"},
      {"type": "EndEvent", "x": 712, "y": 272, "label": "Drink paid", "id": "EndDrinkPaid", "parent": "PoolCustomer", "connectTo": [], "eventDef": "MessageEventDefinition"},
      {"type": "StartEvent", "x": 222, "y": 522, "label": "Order received", "id": "StartOrderReceived", "parent": "PoolBarista", "connectTo": ["TaskCheckAvail"], "eventDef": "MessageEventDefinition"},
      {"type": "UserTask", "x": 310, "y": 500, "label": "Check availability", "id": "TaskCheckAvail", "parent": "PoolBarista", "connectTo": ["GwAvailable"]},
      {"type": "ExclusiveGateway", "x": 465, "y": 515, "label": "Drink available?", "id": "GwAvailable", "parent": "PoolBarista", "connectTo": []},
      {"type": "EndEvent", "x": 572, "y": 432, "label": "Order rejected", "id": "EndOrderRejected", "parent": "PoolBarista", "connectTo": [], "eventDef": "MessageEventDefinition"},
      {"type": "UserTask", "x": 570, "y": 580, "label": "Prepare drink", "id": "TaskPrepareDrink", "parent": "PoolBarista", "connectTo": ["TaskHandOver"]},
      {"type": "SendTask", "x": 730, "y": 580, "label": "Hand over drink", "id": "TaskHandOver", "parent": "PoolBarista", "connectTo": ["TaskReceivePayment"]},
      {"type": "ReceiveTask", "x": 890, "y": 580, "label": "Receive payment", "id": "TaskReceivePayment", "parent": "PoolBarista", "connectTo": ["EndOrderCompleted"]},
      {"type": "EndEvent", "x": 1052, "y": 602, "label": "Order completed", "id": "EndOrderCompleted", "parent": "PoolBarista", "connectTo": []}
    ],
    "connect": [
      {"src": "GwEventBased", "tgt": "CatchRejection"},
      {"src": "GwEventBased", "tgt": "CatchDrinkReceived"},
      {"src": "GwAvailable", "tgt": "TaskPrepareDrink", "label": "Yes"},
      {"src": "GwAvailable", "tgt": "EndOrderRejected", "label": "No"},
      {"src": "TaskPlaceOrder", "tgt": "StartOrderReceived"},
      {"src": "TaskHandOver", "tgt": "CatchDrinkReceived"},
      {"src": "EndOrderRejected", "tgt": "CatchRejection"},
      {"src": "EndDrinkPaid", "tgt": "TaskReceivePayment"}
    ]
  }
}

Example — No lanes, single expanded pool:
{
  "message": "Modeled the claims process with decision gateway and two outcome paths.",
  "actions": {
    "participate": [
      {"x": 160, "y": 80, "w": 1400, "h": 280, "label": "Insurance Company", "id": "PoolInsurance", "expanded": true, "lanes": []},
      {"x": 160, "y": 410, "w": 1400, "h": 60, "label": "Customer", "id": "PoolCustomer", "expanded": false, "lanes": []}
    ],
    "draw": [
      {"type": "StartEvent", "x": 250, "y": 200, "label": "Claim received", "id": "StartClaim", "parent": "PoolInsurance", "connectTo": ["TaskReview"], "eventDef": "MessageEventDefinition"},
      {"type": "UserTask", "x": 400, "y": 200, "label": "Review claim", "id": "TaskReview", "parent": "PoolInsurance", "connectTo": ["GwDecision"]},
      {"type": "ExclusiveGateway", "x": 560, "y": 200, "label": "Approved?", "id": "GwDecision", "parent": "PoolInsurance", "connectTo": []},
      {"type": "ServiceTask", "x": 720, "y": 160, "label": "Process payment", "id": "TaskPayment", "parent": "PoolInsurance", "connectTo": ["EndApproved"]},
      {"type": "SendTask", "x": 720, "y": 260, "label": "Send rejection", "id": "TaskReject", "parent": "PoolInsurance", "connectTo": ["EndRejected"]},
      {"type": "EndEvent", "x": 900, "y": 160, "label": "Claim settled", "id": "EndApproved", "parent": "PoolInsurance", "connectTo": []},
      {"type": "EndEvent", "x": 900, "y": 260, "label": "Claim rejected", "id": "EndRejected", "parent": "PoolInsurance", "connectTo": []}
    ],
    "connect": [
      {"src": "GwDecision", "tgt": "TaskPayment", "label": "Yes"},
      {"src": "GwDecision", "tgt": "TaskReject", "label": "No"},
      {"src": "PoolCustomer", "tgt": "StartClaim"},
      {"src": "TaskReject", "tgt": "PoolCustomer"}
    ]
  }
}
"""

XML_ELEMENT_GUIDANCE = """
BPMN 2.0 XML Element Reference

Use these XML element types for each BPMN construct:

Events:
  <bpmn:startEvent>            — optional child: <bpmn:messageEventDefinition />, <bpmn:timerEventDefinition />, <bpmn:signalEventDefinition />, <bpmn:conditionalEventDefinition />
  <bpmn:endEvent>              — optional child: <bpmn:messageEventDefinition />, <bpmn:terminateEventDefinition />, <bpmn:errorEventDefinition />, <bpmn:signalEventDefinition />
  <bpmn:intermediateCatchEvent>  — requires exactly one event definition child (message/timer/signal/conditional)
  <bpmn:intermediateThrowEvent>  — requires exactly one event definition child (message or signal)

Each incoming/outgoing flow must be declared:
  <bpmn:incoming>FlowId</bpmn:incoming>   inside the element
  <bpmn:outgoing>FlowId</bpmn:outgoing>   inside the element

Tasks — choose the most specific type:
  <bpmn:userTask>         — human uses software/interface
  <bpmn:manualTask>       — human, fully offline, no software
  <bpmn:serviceTask>      — fully automated system-to-system
  <bpmn:sendTask>         — sends a message to another pool (also add a messageFlow!)
  <bpmn:receiveTask>      — waits for a message from another pool (also add a messageFlow!)
  <bpmn:businessRuleTask> — evaluates a formal rule or decision table automatically
  <bpmn:scriptTask>       — executes a script or program
  <bpmn:task>             — generic, use only when no specific type fits

Gateways:
  <bpmn:exclusiveGateway>  — XOR: one outgoing path, label each outgoing flow
  <bpmn:parallelGateway>   — AND: all paths simultaneously; every split needs a join
  <bpmn:inclusiveGateway>  — OR: one or more paths, label each outgoing flow
  <bpmn:eventBasedGateway> — only IntermediateCatchEvents may follow

Pools and Lanes:
  <bpmn:collaboration id="Collaboration_1">
    <bpmn:participant id="PoolA" name="..." processRef="Process_PoolA" />
    <bpmn:messageFlow id="MF_1" sourceRef="..." targetRef="..." />
  </bpmn:collaboration>

  <bpmn:process id="Process_PoolA" isExecutable="false">
    <!-- Lanes (only when ≥2 distinct roles): -->
    <bpmn:laneSet id="LaneSet_PoolA">
      <bpmn:lane id="LaneRole1" name="Role 1">
        <bpmn:flowNodeRef>StartA</bpmn:flowNodeRef>
        <bpmn:flowNodeRef>TaskA</bpmn:flowNodeRef>
      </bpmn:lane>
      <bpmn:lane id="LaneRole2" name="Role 2">
        <bpmn:flowNodeRef>TaskB</bpmn:flowNodeRef>
      </bpmn:lane>
    </bpmn:laneSet>
    <bpmn:startEvent id="StartA" name="...">
      <bpmn:outgoing>Flow_1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartA" targetRef="TaskA" />
  </bpmn:process>

Diagram Section (bpmndi) — EVERY element and flow must appear here:
  Pool shape:       <bpmndi:BPMNShape bpmnElement="PoolA" isHorizontal="true"> with <dc:Bounds />
  Lane shape:       <bpmndi:BPMNShape bpmnElement="LaneRole1" isHorizontal="true"> with <dc:Bounds />
  Element shape:    <bpmndi:BPMNShape bpmnElement="TaskA"> with <dc:Bounds /> and optional <bpmndi:BPMNLabel />
  Flow/edge:        <bpmndi:BPMNEdge bpmnElement="Flow_1"> with two or more <di:waypoint x="..." y="..." />

Standard Element Dimensions (use exactly these in dc:Bounds):
  Task (any type):                width="100" height="80"
  ExclusiveGateway:               width="50"  height="50"
  ParallelGateway:                width="50"  height="50"
  InclusiveGateway:               width="50"  height="50"
  EventBasedGateway:              width="50"  height="50"
  StartEvent / EndEvent:          width="36"  height="36"
  IntermediateCatchEvent:         width="36"  height="36"
  IntermediateThrowEvent:         width="36"  height="36"
  Pool shape:                     match the pool's actual x, y, width, height
  Lane shape:                     same x and width as pool; height = pool_height / lane_count; y offset stacked from top

Coordinate Conventions:
  First pool shape: x="160" y="80"
  Subsequent pools: y = previous_pool_y + previous_pool_height + 50
  Pool width: 1200–1600; pool height: 200–400 per pool
  Elements: ≥100px from pool edges; ≥150px horizontal spacing between elements
  Parallel branches: stagger y by ≈120px per branch
  Lane IDs: derive from name by removing non-alphanumeric chars, capitalizing each word, prefixing "Lane"
    e.g. "Claims Handler" → LaneClaimsHandler
"""

# ============================================================================
# 1b. SCENARIO EXAMPLES
# ============================================================================

SCENARIO_EXAMPLES_LION = """
Complete Modeling Examples (LION format)

Example 1 — Two expanded pools, event-based gateway, typed events, cross-pool message flows:
message: "Modeled the café ordering process: expanded Customer pool with event-based gateway routing between rejection and drink-received; expanded Barista pool with availability check, preparation, and payment.",
actions: {
  participate(x, y, w, h, label, id, expanded, lanes): [
    {160, 80, 1028, 270, Customer, PoolCustomer, true, []},
    {160, 400, 1028, 340, Barista, PoolBarista, true, []}
  ],
  draw(type, x, y, label, id, parent, connectTo, eventDef): [
    {StartEvent, 222, 192, "Enter café", StartEnterCafe, PoolCustomer, [TaskPlaceOrder], null},
    {SendTask, 310, 170, "Place order", TaskPlaceOrder, PoolCustomer, [GwEventBased], null},
    {EventBasedGateway, 465, 185, null, GwEventBased, PoolCustomer, [], null},
    {IntermediateCatchEvent, 572, 122, "Rejection received", CatchRejection, PoolCustomer, [EndOrderCancelled], MessageEventDefinition},
    {EndEvent, 672, 122, "Order cancelled", EndOrderCancelled, PoolCustomer, [], null},
    {IntermediateCatchEvent, 622, 272, "Drink received", CatchDrinkReceived, PoolCustomer, [EndDrinkPaid], MessageEventDefinition},
    {EndEvent, 712, 272, "Drink paid", EndDrinkPaid, PoolCustomer, [], MessageEventDefinition},
    {StartEvent, 222, 522, "Order received", StartOrderReceived, PoolBarista, [TaskCheckAvail], MessageEventDefinition},
    {UserTask, 310, 500, "Check availability", TaskCheckAvail, PoolBarista, [GwAvailable], null},
    {ExclusiveGateway, 465, 515, "Drink available?", GwAvailable, PoolBarista, [], null},
    {EndEvent, 572, 432, "Order rejected", EndOrderRejected, PoolBarista, [], MessageEventDefinition},
    {UserTask, 570, 580, "Prepare drink", TaskPrepareDrink, PoolBarista, [TaskHandOver], null},
    {SendTask, 730, 580, "Hand over drink", TaskHandOver, PoolBarista, [TaskReceivePayment], null},
    {ReceiveTask, 890, 580, "Receive payment", TaskReceivePayment, PoolBarista, [EndOrderCompleted], null},
    {EndEvent, 1052, 602, "Order completed", EndOrderCompleted, PoolBarista, [], null}
  ],
  connect(src, tgt, label): [
    {GwEventBased, CatchRejection, null},
    {GwEventBased, CatchDrinkReceived, null},
    {GwAvailable, TaskPrepareDrink, Yes},
    {GwAvailable, EndOrderRejected, No},
    {TaskPlaceOrder, StartOrderReceived, null},
    {TaskHandOver, CatchDrinkReceived, null},
    {EndOrderRejected, CatchRejection, null},
    {EndDrinkPaid, TaskReceivePayment, null}
  ]
}

Example 2 — No lanes, single expanded pool:
message: "Modeled the claims process with decision gateway and two outcome paths.",
actions: {
  participate(x, y, w, h, label, id, expanded, lanes): [
    {160, 80, 1400, 280, "Insurance Company", PoolInsurance, true, []},
    {160, 410, 1400, 60, Customer, PoolCustomer, false, []}
  ],
  draw(type, x, y, label, id, parent, connectTo, eventDef): [
    {StartEvent, 250, 200, "Claim received", StartClaim, PoolInsurance, [TaskReview], MessageEventDefinition},
    {UserTask, 400, 200, "Review claim", TaskReview, PoolInsurance, [GwDecision], null},
    {ExclusiveGateway, 560, 200, "Approved?", GwDecision, PoolInsurance, [], null},
    {ServiceTask, 720, 160, "Process payment", TaskPayment, PoolInsurance, [EndApproved], null},
    {SendTask, 720, 260, "Send rejection", TaskReject, PoolInsurance, [EndRejected], null},
    {EndEvent, 900, 160, "Claim settled", EndApproved, PoolInsurance, [], null},
    {EndEvent, 900, 260, "Claim rejected", EndRejected, PoolInsurance, [], null}
  ],
  connect(src, tgt, label): [
    {GwDecision, TaskPayment, Yes},
    {GwDecision, TaskReject, No},
    {PoolCustomer, StartClaim, null},
    {TaskReject, PoolCustomer, null}
  ]
}
"""

SCENARIO_EXAMPLES_XML = """
Complete Modeling Examples (BPMN 2.0 XML format)

The following XML goes inside the "bpmn_xml" field of your JSON output.

Example 1 — Two expanded pools, event-based gateway, typed events, cross-pool message flows:

<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
  xmlns:di="http://www.omg.org/spec/DD/20100524/DI"
  id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:collaboration id="Collaboration_1">
    <bpmn:participant id="PoolCustomer" name="Customer" processRef="Process_PoolCustomer" />
    <bpmn:participant id="PoolBarista" name="Barista" processRef="Process_PoolBarista" />
    <bpmn:messageFlow id="MF_PlaceOrder" sourceRef="TaskPlaceOrder" targetRef="StartOrderReceived" />
    <bpmn:messageFlow id="MF_HandOver" sourceRef="TaskHandOver" targetRef="CatchDrinkReceived" />
    <bpmn:messageFlow id="MF_Rejected" sourceRef="EndOrderRejected" targetRef="CatchRejection" />
    <bpmn:messageFlow id="MF_Payment" sourceRef="EndDrinkPaid" targetRef="TaskReceivePayment" />
  </bpmn:collaboration>
  <bpmn:process id="Process_PoolCustomer" isExecutable="true">
    <bpmn:startEvent id="StartEnterCafe" name="Enter caf\u00e9">
      <bpmn:outgoing>Flow_C1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:sendTask id="TaskPlaceOrder" name="Place order">
      <bpmn:incoming>Flow_C1</bpmn:incoming>
      <bpmn:outgoing>Flow_C2</bpmn:outgoing>
    </bpmn:sendTask>
    <bpmn:eventBasedGateway id="GwEventBased">
      <bpmn:incoming>Flow_C2</bpmn:incoming>
      <bpmn:outgoing>Flow_C3</bpmn:outgoing>
      <bpmn:outgoing>Flow_C4</bpmn:outgoing>
    </bpmn:eventBasedGateway>
    <bpmn:intermediateCatchEvent id="CatchRejection" name="Rejection received">
      <bpmn:incoming>Flow_C3</bpmn:incoming>
      <bpmn:outgoing>Flow_C5</bpmn:outgoing>
      <bpmn:messageEventDefinition id="MED_Rejection" />
    </bpmn:intermediateCatchEvent>
    <bpmn:endEvent id="EndOrderCancelled" name="Order cancelled">
      <bpmn:incoming>Flow_C5</bpmn:incoming>
    </bpmn:endEvent>
    <bpmn:intermediateCatchEvent id="CatchDrinkReceived" name="Drink received">
      <bpmn:incoming>Flow_C4</bpmn:incoming>
      <bpmn:outgoing>Flow_C6</bpmn:outgoing>
      <bpmn:messageEventDefinition id="MED_DrinkReceived" />
    </bpmn:intermediateCatchEvent>
    <bpmn:endEvent id="EndDrinkPaid" name="Drink paid">
      <bpmn:incoming>Flow_C6</bpmn:incoming>
      <bpmn:messageEventDefinition id="MED_Payment" />
    </bpmn:endEvent>
    <bpmn:sequenceFlow id="Flow_C1" sourceRef="StartEnterCafe" targetRef="TaskPlaceOrder" />
    <bpmn:sequenceFlow id="Flow_C2" sourceRef="TaskPlaceOrder" targetRef="GwEventBased" />
    <bpmn:sequenceFlow id="Flow_C3" sourceRef="GwEventBased" targetRef="CatchRejection" />
    <bpmn:sequenceFlow id="Flow_C4" sourceRef="GwEventBased" targetRef="CatchDrinkReceived" />
    <bpmn:sequenceFlow id="Flow_C5" sourceRef="CatchRejection" targetRef="EndOrderCancelled" />
    <bpmn:sequenceFlow id="Flow_C6" sourceRef="CatchDrinkReceived" targetRef="EndDrinkPaid" />
  </bpmn:process>
  <bpmn:process id="Process_PoolBarista" isExecutable="false">
    <bpmn:startEvent id="StartOrderReceived" name="Order received">
      <bpmn:outgoing>Flow_B1</bpmn:outgoing>
      <bpmn:messageEventDefinition id="MED_OrderReceived" />
    </bpmn:startEvent>
    <bpmn:userTask id="TaskCheckAvail" name="Check availability">
      <bpmn:incoming>Flow_B1</bpmn:incoming>
      <bpmn:outgoing>Flow_B2</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:exclusiveGateway id="GwAvailable" name="Drink available?">
      <bpmn:incoming>Flow_B2</bpmn:incoming>
      <bpmn:outgoing>Flow_B3</bpmn:outgoing>
      <bpmn:outgoing>Flow_B4</bpmn:outgoing>
    </bpmn:exclusiveGateway>
    <bpmn:userTask id="TaskPrepareDrink" name="Prepare drink">
      <bpmn:incoming>Flow_B3</bpmn:incoming>
      <bpmn:outgoing>Flow_B5</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:sendTask id="TaskHandOver" name="Hand over drink">
      <bpmn:incoming>Flow_B5</bpmn:incoming>
      <bpmn:outgoing>Flow_B6</bpmn:outgoing>
    </bpmn:sendTask>
    <bpmn:receiveTask id="TaskReceivePayment" name="Receive payment">
      <bpmn:incoming>Flow_B6</bpmn:incoming>
      <bpmn:outgoing>Flow_B7</bpmn:outgoing>
    </bpmn:receiveTask>
    <bpmn:endEvent id="EndOrderCompleted" name="Order completed">
      <bpmn:incoming>Flow_B7</bpmn:incoming>
    </bpmn:endEvent>
    <bpmn:endEvent id="EndOrderRejected" name="Order rejected">
      <bpmn:incoming>Flow_B4</bpmn:incoming>
      <bpmn:messageEventDefinition id="MED_Rejected" />
    </bpmn:endEvent>
    <bpmn:sequenceFlow id="Flow_B1" sourceRef="StartOrderReceived" targetRef="TaskCheckAvail" />
    <bpmn:sequenceFlow id="Flow_B2" sourceRef="TaskCheckAvail" targetRef="GwAvailable" />
    <bpmn:sequenceFlow id="Flow_B3" name="Yes" sourceRef="GwAvailable" targetRef="TaskPrepareDrink" />
    <bpmn:sequenceFlow id="Flow_B4" name="No" sourceRef="GwAvailable" targetRef="EndOrderRejected" />
    <bpmn:sequenceFlow id="Flow_B5" sourceRef="TaskPrepareDrink" targetRef="TaskHandOver" />
    <bpmn:sequenceFlow id="Flow_B6" sourceRef="TaskHandOver" targetRef="TaskReceivePayment" />
    <bpmn:sequenceFlow id="Flow_B7" sourceRef="TaskReceivePayment" targetRef="EndOrderCompleted" />
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Collaboration_1">
      <bpmndi:BPMNShape id="PoolCustomer_di" bpmnElement="PoolCustomer" isHorizontal="true">
        <dc:Bounds x="160" y="80" width="1028" height="270" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="StartEnterCafe_di" bpmnElement="StartEnterCafe">
        <dc:Bounds x="222" y="192" width="36" height="36" />
        <bpmndi:BPMNLabel><dc:Bounds x="207" y="235" width="67" height="14" /></bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="TaskPlaceOrder_di" bpmnElement="TaskPlaceOrder">
        <dc:Bounds x="310" y="170" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="GwEventBased_di" bpmnElement="GwEventBased">
        <dc:Bounds x="465" y="185" width="50" height="50" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="CatchRejection_di" bpmnElement="CatchRejection">
        <dc:Bounds x="572" y="122" width="36" height="36" />
        <bpmndi:BPMNLabel><dc:Bounds x="556" y="86" width="68" height="27" /></bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="EndOrderCancelled_di" bpmnElement="EndOrderCancelled">
        <dc:Bounds x="672" y="122" width="36" height="36" />
        <bpmndi:BPMNLabel><dc:Bounds x="651" y="165" width="78" height="27" /></bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="CatchDrinkReceived_di" bpmnElement="CatchDrinkReceived">
        <dc:Bounds x="622" y="272" width="36" height="36" />
        <bpmndi:BPMNLabel><dc:Bounds x="599" y="315" width="82" height="14" /></bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="EndDrinkPaid_di" bpmnElement="EndDrinkPaid">
        <dc:Bounds x="712" y="272" width="36" height="36" />
        <bpmndi:BPMNLabel><dc:Bounds x="695" y="315" width="70" height="14" /></bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="PoolBarista_di" bpmnElement="PoolBarista" isHorizontal="true">
        <dc:Bounds x="160" y="380" width="1028" height="320" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="StartOrderReceived_di" bpmnElement="StartOrderReceived">
        <dc:Bounds x="222" y="522" width="36" height="36" />
        <bpmndi:BPMNLabel><dc:Bounds x="207" y="565" width="65" height="27" /></bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="TaskCheckAvail_di" bpmnElement="TaskCheckAvail">
        <dc:Bounds x="310" y="500" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="GwAvailable_di" bpmnElement="GwAvailable" isMarkerVisible="true">
        <dc:Bounds x="465" y="515" width="50" height="50" />
        <bpmndi:BPMNLabel><dc:Bounds x="455" y="572" width="70" height="27" /></bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="EndOrderRejected_di" bpmnElement="EndOrderRejected">
        <dc:Bounds x="572" y="432" width="36" height="36" />
        <bpmndi:BPMNLabel><dc:Bounds x="557" y="475" width="66" height="27" /></bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="TaskPrepareDrink_di" bpmnElement="TaskPrepareDrink">
        <dc:Bounds x="570" y="580" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="TaskHandOver_di" bpmnElement="TaskHandOver">
        <dc:Bounds x="730" y="580" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="TaskReceivePayment_di" bpmnElement="TaskReceivePayment">
        <dc:Bounds x="890" y="580" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="EndOrderCompleted_di" bpmnElement="EndOrderCompleted">
        <dc:Bounds x="1052" y="602" width="36" height="36" />
        <bpmndi:BPMNLabel><dc:Bounds x="1030" y="645" width="80" height="27" /></bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="Flow_C1_di" bpmnElement="Flow_C1">
        <di:waypoint x="258" y="210" /><di:waypoint x="310" y="210" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_C2_di" bpmnElement="Flow_C2">
        <di:waypoint x="410" y="210" /><di:waypoint x="465" y="210" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_C3_di" bpmnElement="Flow_C3">
        <di:waypoint x="490" y="185" /><di:waypoint x="490" y="140" /><di:waypoint x="572" y="140" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_C4_di" bpmnElement="Flow_C4">
        <di:waypoint x="490" y="235" /><di:waypoint x="490" y="290" /><di:waypoint x="622" y="290" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_C5_di" bpmnElement="Flow_C5">
        <di:waypoint x="608" y="140" /><di:waypoint x="672" y="140" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_C6_di" bpmnElement="Flow_C6">
        <di:waypoint x="658" y="290" /><di:waypoint x="712" y="290" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_B1_di" bpmnElement="Flow_B1">
        <di:waypoint x="258" y="540" /><di:waypoint x="310" y="540" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_B2_di" bpmnElement="Flow_B2">
        <di:waypoint x="410" y="540" /><di:waypoint x="465" y="540" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_B3_di" bpmnElement="Flow_B3">
        <di:waypoint x="490" y="565" /><di:waypoint x="490" y="620" /><di:waypoint x="570" y="620" />
        <bpmndi:BPMNLabel><dc:Bounds x="496" y="583" width="20" height="14" /></bpmndi:BPMNLabel>
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_B4_di" bpmnElement="Flow_B4">
        <di:waypoint x="490" y="515" /><di:waypoint x="490" y="450" /><di:waypoint x="572" y="450" />
        <bpmndi:BPMNLabel><dc:Bounds x="495" y="480" width="22" height="14" /></bpmndi:BPMNLabel>
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_B5_di" bpmnElement="Flow_B5">
        <di:waypoint x="670" y="620" /><di:waypoint x="730" y="620" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_B6_di" bpmnElement="Flow_B6">
        <di:waypoint x="830" y="620" /><di:waypoint x="890" y="620" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_B7_di" bpmnElement="Flow_B7">
        <di:waypoint x="990" y="620" /><di:waypoint x="1052" y="620" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="MF_PlaceOrder_di" bpmnElement="MF_PlaceOrder">
        <di:waypoint x="360" y="250" /><di:waypoint x="360" y="360" /><di:waypoint x="240" y="360" /><di:waypoint x="240" y="522" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="MF_HandOver_di" bpmnElement="MF_HandOver">
        <di:waypoint x="780" y="580" /><di:waypoint x="780" y="370" /><di:waypoint x="640" y="370" /><di:waypoint x="640" y="308" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="MF_Rejected_di" bpmnElement="MF_Rejected">
        <di:waypoint x="590" y="432" /><di:waypoint x="590" y="158" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="MF_Payment_di" bpmnElement="MF_Payment">
        <di:waypoint x="730" y="308" /><di:waypoint x="730" y="360" /><di:waypoint x="940" y="360" /><di:waypoint x="940" y="580" />
      </bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>

Example 2 — No lanes, single expanded pool:

<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
  xmlns:di="http://www.omg.org/spec/DD/20100524/DI"
  id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:collaboration id="Collaboration_1">
    <bpmn:participant id="PoolInsurance" name="Insurance Company" processRef="Process_PoolInsurance" />
    <bpmn:participant id="PoolCustomer" name="Customer" processRef="Process_PoolCustomer" />
    <bpmn:messageFlow id="MF_1" sourceRef="PoolCustomer" targetRef="StartClaim" />
    <bpmn:messageFlow id="MF_2" sourceRef="TaskReject" targetRef="PoolCustomer" />
  </bpmn:collaboration>
  <bpmn:process id="Process_PoolInsurance" isExecutable="false">
    <bpmn:startEvent id="StartClaim" name="Claim received">
      <bpmn:messageEventDefinition id="MEDStartClaim" />
      <bpmn:outgoing>Flow_1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:userTask id="TaskReview" name="Review claim">
      <bpmn:incoming>Flow_1</bpmn:incoming>
      <bpmn:outgoing>Flow_2</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:exclusiveGateway id="GwDecision" name="Approved?">
      <bpmn:incoming>Flow_2</bpmn:incoming>
      <bpmn:outgoing>Flow_3</bpmn:outgoing>
      <bpmn:outgoing>Flow_4</bpmn:outgoing>
    </bpmn:exclusiveGateway>
    <bpmn:serviceTask id="TaskPayment" name="Process payment">
      <bpmn:incoming>Flow_3</bpmn:incoming>
      <bpmn:outgoing>Flow_5</bpmn:outgoing>
    </bpmn:serviceTask>
    <bpmn:sendTask id="TaskReject" name="Send rejection">
      <bpmn:incoming>Flow_4</bpmn:incoming>
      <bpmn:outgoing>Flow_6</bpmn:outgoing>
    </bpmn:sendTask>
    <bpmn:endEvent id="EndApproved" name="Claim settled">
      <bpmn:incoming>Flow_5</bpmn:incoming>
    </bpmn:endEvent>
    <bpmn:endEvent id="EndRejected" name="Claim rejected">
      <bpmn:incoming>Flow_6</bpmn:incoming>
    </bpmn:endEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartClaim" targetRef="TaskReview" />
    <bpmn:sequenceFlow id="Flow_2" sourceRef="TaskReview" targetRef="GwDecision" />
    <bpmn:sequenceFlow id="Flow_3" sourceRef="GwDecision" targetRef="TaskPayment" name="Yes" />
    <bpmn:sequenceFlow id="Flow_4" sourceRef="GwDecision" targetRef="TaskReject" name="No" />
    <bpmn:sequenceFlow id="Flow_5" sourceRef="TaskPayment" targetRef="EndApproved" />
    <bpmn:sequenceFlow id="Flow_6" sourceRef="TaskReject" targetRef="EndRejected" />
  </bpmn:process>
  <bpmn:process id="Process_PoolCustomer" isExecutable="false" />
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Collaboration_1">
      <bpmndi:BPMNShape id="PoolInsurance_di" bpmnElement="PoolInsurance" isHorizontal="true" isExpanded="true">
        <dc:Bounds x="160" y="80" width="1400" height="280" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="PoolCustomer_di" bpmnElement="PoolCustomer" isHorizontal="true">
        <dc:Bounds x="160" y="410" width="1400" height="60" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="StartClaim_di" bpmnElement="StartClaim">
        <dc:Bounds x="232" y="202" width="36" height="36" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="TaskReview_di" bpmnElement="TaskReview">
        <dc:Bounds x="320" y="180" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="GwDecision_di" bpmnElement="GwDecision">
        <dc:Bounds x="475" y="195" width="50" height="50" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="TaskPayment_di" bpmnElement="TaskPayment">
        <dc:Bounds x="590" y="140" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="TaskReject_di" bpmnElement="TaskReject">
        <dc:Bounds x="590" y="240" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="EndApproved_di" bpmnElement="EndApproved">
        <dc:Bounds x="752" y="162" width="36" height="36" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="EndRejected_di" bpmnElement="EndRejected">
        <dc:Bounds x="752" y="262" width="36" height="36" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="Flow_1_di" bpmnElement="Flow_1">
        <di:waypoint x="268" y="220" /><di:waypoint x="320" y="220" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_2_di" bpmnElement="Flow_2">
        <di:waypoint x="420" y="220" /><di:waypoint x="475" y="220" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_3_di" bpmnElement="Flow_3">
        <di:waypoint x="525" y="220" /><di:waypoint x="590" y="180" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_4_di" bpmnElement="Flow_4">
        <di:waypoint x="525" y="220" /><di:waypoint x="590" y="280" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_5_di" bpmnElement="Flow_5">
        <di:waypoint x="690" y="180" /><di:waypoint x="752" y="180" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_6_di" bpmnElement="Flow_6">
        <di:waypoint x="690" y="280" /><di:waypoint x="752" y="280" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="MF_1_di" bpmnElement="MF_1">
        <di:waypoint x="860" y="410" /><di:waypoint x="250" y="238" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="MF_2_di" bpmnElement="MF_2">
        <di:waypoint x="640" y="320" /><di:waypoint x="640" y="410" />
      </bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""

# ============================================================================
# 2. BENCHMARK PROMPT TEMPLATES
# ============================================================================

BENCHMARK_XML_PROMPT = """Role and Responsibility
You are an autonomous BPMN modeler. You produce a COMPLETE, VALID BPMN 2.0 XML model in a single response.
You are NOT interactive. Model everything yourself. Do not ask questions or wait for user input.

{general_rules}

{one_shot_rules}

{bpmn_standards}

{bpmn_elements}

{xml_element_guidance}

{xml_examples}

Output Format
CRITICAL: Respond ONLY with a single valid JSON object containing two fields:
  "message": brief explanation of what you modeled (2–4 sentences)
  "bpmn_xml": the complete BPMN 2.0 XML as a string

Do NOT include any XML comments (<!-- -->), JSON comments, markdown fences, or text outside the JSON object.
Do NOT include any explanatory annotations inside the XML itself.

Required JSON wrapper:
{
  "message": "Your explanation here.",
  "bpmn_xml": "<?xml version=\\"1.0\\" encoding=\\"UTF-8\\"?>\\n<bpmn:definitions ...>...</bpmn:definitions>"
}
"""

BENCHMARK_JSON_PROMPT = """Role and Responsibility
You are an autonomous BPMN modeler producing structured JSON modeling commands.
You are NOT interactive. Model everything yourself. Do not ask questions or wait for user input.
You MUST model the ENTIRE process in a single JSON response.

{general_rules}

{one_shot_rules}

{bpmn_standards}

{bpmn_elements}

{action_types_json}

{json_examples}

Output Format
CRITICAL: Respond ONLY with a single raw JSON object. No markdown fences, no text outside the JSON, no comments.
Do NOT wrap your response in ```json ... ```.

Required structure:
{
  "message": "Brief explanation of what you modeled (2–4 sentences).",
  "actions": {
    "participate": [...],
    "draw": [...],
    "connect": [...],
    "rename": [...],
    "move": [...],
    "delete": [...]
  }
}
"""

BENCHMARK_LION_PROMPT = """Role and Responsibility
You are an autonomous BPMN modeler producing structured LION modeling commands.
You are NOT interactive. Model everything yourself. Do not ask questions or wait for user input.
You MUST model the ENTIRE process in a single LION response.
Do NOT include any comments, annotations, or text outside the LION structure.

{general_rules}

{one_shot_rules}

{bpmn_standards}

{bpmn_elements}

{lion_rules}

{action_types}

{lion_examples}

Output Format
Respond ONLY with valid LION notation. No markdown fences, no text outside the structure, no comments.

Required structure:
message: "Brief explanation of what you modeled (2–4 sentences).",
actions: {
    participate(x, y, w, h, label, id, expanded, lanes): [{...}, {...}],
    draw(type, x, y, label, id, parent, connectTo, eventDef): [{...}, {...}],
    connect(src, tgt, label): [{...}],
    rename(id, label): [{...}],
    move(id, x, y): [{...}],
    delete: [...]
}
"""


# ============================================================================
# 3. PROMPT ASSEMBLY
# ============================================================================

def get_benchmark_prompt(base_prompt: str) -> str:
    """
    Inserts all shared and benchmark-specific blocks into a prompt template.
    Placeholders that do not appear in the template are silently skipped.
    """
    replacements = {
        "{general_rules}": GENERAL_RULES,
        "{bpmn_standards}": BPMN_STANDARDS,
        "{bpmn_elements}": BPMN_ELEMENTS_REFERENCE,
        "{action_types}": ACTION_TYPES_REFERENCE,
        "{action_types_json}": ACTION_TYPES_REFERENCE_JSON,
        "{lion_rules}": LION_FORMAT_RULES,
        "{json_examples}": JSON_EXAMPLES,
        "{lion_examples}": SCENARIO_EXAMPLES_LION,
        "{xml_examples}": SCENARIO_EXAMPLES_XML,
        "{xml_element_guidance}": XML_ELEMENT_GUIDANCE,
        "{one_shot_rules}": ONE_SHOT_RULES,
    }
    result = base_prompt
    for key, value in replacements.items():
        result = result.replace(key, value)
    return result


# ============================================================================
# 4. EXPORT FINAL PROMPTS
# ============================================================================

BENCHMARK_XML_PROMPT_FINAL = get_benchmark_prompt(BENCHMARK_XML_PROMPT)
BENCHMARK_JSON_PROMPT_FINAL = get_benchmark_prompt(BENCHMARK_JSON_PROMPT)
BENCHMARK_LION_PROMPT_FINAL = get_benchmark_prompt(BENCHMARK_LION_PROMPT)

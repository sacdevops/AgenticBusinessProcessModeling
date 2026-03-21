# Deductive Scoring Schema for BPMN Evaluation

The evaluation of the generated business process models follows a strict deductive scoring methodology. Each modeling task possesses a predefined maximum score based on structural complexity. Evaluators deduct specific point values for missing elements, syntactic flaws, logical errors, and violations of modeling best practices. 

## Maximum Baselines per Task
* **Task 1:** 50.0 points
* **Task 2:** 67.5 points
* **Task 3:** 60.0 points
* **Task 4:** 70.0 points
* **Task 5:** 60.0 points

---

## Category 1: Major Element Omissions (-2.5 points per instance)
Deductions apply when essential BPMN objects required to fulfill the task description are completely missing.
* Missing Pool
* Missing Lane
* Missing Task
* Missing Gateway
* Missing Event

---

## Category 2: Minor Structural and Syntactic Flaws (-0.5 points per instance)
Deductions apply when a required element exists in the model but contains inaccuracies.
* **Typing errors:** Missing or incorrect element type.
* **Placement errors:** Element assigned to the wrong Pool/Lane or placed entirely outside a valid boundary.
* **Labeling errors:** Missing text label (excluding elements where labels are conventionally omitted, such as synchronizing Gateways or Event-Based Gateways).
* **Connection errors:** Missing, incorrect, or invalidly routed connecting objects (e.g., Sequence Flows crossing Pool boundaries inappropriately). Valid Message Flows between differing Pools are excluded from this penalty.

---

## Category 3: Severe Logical Errors (-5.0 points per instance)
Deductions apply for critical flaws disrupting the fundamental execution logic of the process.
* **Unresolved deadlocks:** Failing to implement safeguards against infinite waiting states (e.g., missing a Timer Event attached to an Event-Based Gateway alongside a Message Event).

---

## Category 4: Best Practices and Aesthetics (One-time -1.0 point penalty per violation type)
Deductions in this category apply only once per model for each broken convention, regardless of the total number of occurrences.
* **Overlapping:** Sequence Flows or Message Flows crossing visually over other BPMN elements.
* **Gateway elegance:** Using standard Exclusive Gateways for external accept/reject decisions instead of utilizing the more precise Event-Based Gateway.
* **Event integration:** Using separate elements instead of integrated typed Start/End Events (e.g., drawing a standard End Event plus a Send Task instead of a single Message End Event).
* **Semantic precision:** Failing to differentiate correctly between catching/throwing Events and Send/Receive Tasks.
* **Directionality:** Violating the strict left-to-right modeling convention by routing Sequence Flows backward (right-to-left) within the same Lane or Pool.

---

## General Evaluation Guideline
Business processes inherently allow for multiple syntactically valid modeling approaches. Evaluators must thoroughly analyze the underlying logic of the submitted model before applying deductions. Alternative but logically sound solutions fulfilling the task requirements must not receive unjustified penalties.
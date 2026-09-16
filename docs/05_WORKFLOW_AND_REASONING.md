# BoberAgent Core — Workflow and Reasoning Model v1

**Status:** Initial normative specification
**Document:** `docs/05_WORKFLOW_AND_REASONING.md`
**Related:** `01_SYSTEM_ARCHITECTURE.md`, `02_CAPABILITY_CONTRACT.md`, `03_CAPABILITY_SDK.md`, `04_WORLD_STATE_MODEL.md`

---

# 1. Purpose

This document defines how BoberAgent decides:

* what should happen next;
* when a Capability is applicable;
* when deterministic logic is sufficient;
* when LLM reasoning is justified;
* how Procedures and Workflows are represented;
* how Coverage is measured;
* how Goals are evaluated;
* how retries and duplicate actions are avoided;
* how asynchronous Events affect execution;
* how Human Interaction participates in a running workflow;
* how failures and unknown results are handled;
* when an assessment branch is considered complete, blocked or exhausted.

This document defines orchestration and reasoning semantics.

It does not define individual capability implementation details.

---

# 2. Core Principle

BoberAgent SHOULD use the least complex decision mechanism capable of making a reliable decision.

Preferred order:

```text
deterministic rule
        ↓
structured Procedure logic
        ↓
Coverage / Goal evaluation
        ↓
knowledge retrieval
        ↓
LLM reasoning
        ↓
human assistance where necessary
```

The LLM MUST NOT be used merely because it is available.

---

# 3. Separation of Responsibilities

The following responsibilities MUST remain distinct:

```text
Capability
= what the system can do

Procedure
= reusable operational knowledge describing how to pursue a bounded goal

Workflow
= one executing orchestration instance

Coverage Engine
= what required knowledge is still missing

Goal Engine
= whether a desired state has been reached

Reasoner
= adaptive decision-making where deterministic logic is insufficient

Knowledge System
= reusable technical information

World State
= mission-specific operational facts
```

No one component SHOULD silently absorb the responsibilities of another.

---

# 4. Procedure

A Procedure is a reusable declarative or semi-declarative description of how to pursue a technical objective.

A Procedure MAY define:

```text
goal
preconditions
required state
candidate capabilities
decision branches
coverage requirements
success criteria
failure handling
fallbacks
completion criteria
```

A Procedure MUST NOT embed tool-specific execution syntax when a Capability abstraction exists.

Preferred:

```text
invoke network.service_discovery
```

Avoid:

```text
run "nmap -sV ..."
```

---

# 5. Workflow

A Workflow is a runtime execution instance of one or more Procedures.

A Workflow belongs to a Mission.

A Workflow has its own state and lifecycle.

Suggested lifecycle:

```text
CREATED
ACTIVE
WAITING
BLOCKED
COMPLETED
FAILED
CANCELLED
EXHAUSTED
```

`EXHAUSTED` means:

> the workflow has no currently known valid path toward its goal, but execution infrastructure itself did not fail.

This distinction is important.

---

# 6. Workflow State

A Workflow SHOULD track:

```text
workflow_run_id
procedure_ref
mission_ref
goal_refs
current phase
active capability runs
waiting conditions
completed steps
attempt history references
decisions
blocked reasons
completion status
```

Workflow-local orchestration state is distinct from World State.

World State contains facts about the assessment.

Workflow state contains progress through one orchestration process.

---

# 7. Goal

A Goal describes a desired state rather than a required sequence of actions.

Examples:

```text
discover network services on asset X

determine whether application Y uses vulnerable JWT signing

obtain authenticated access to application Z

obtain command execution on host X

obtain administrative access on host X

complete Active Directory baseline coverage
```

Goal satisfaction SHOULD be expressed against World State where practical.

---

# 8. State-Based Goal Satisfaction

Preferred:

```text
Goal:
administrative access on host X
```

Satisfied when World State contains:

```text
active AccessContext
asset = X
administrative = true
```

The Goal SHOULD NOT require:

```text
exploit A executed
then command B executed
then shell C created
```

unless those exact steps are themselves the objective.

This makes Goals independent of implementation mechanism.

---

# 9. Goal Status

Goals SHOULD support:

```text
PENDING
ACTIVE
SATISFIED
BLOCKED
IMPOSSIBLE
ABANDONED
```

`IMPOSSIBLE` SHOULD be used cautiously.

Lack of a currently known path does not necessarily mean impossibility.

In many cases:

```text
BLOCKED
```

or:

```text
EXHAUSTED
```

is more accurate.

---

# 10. Preconditions

A Procedure or capability invocation MAY define Preconditions.

Preconditions are predicates over:

```text
World State
Mission
Scope
available capabilities
Resources
Sessions
Policy
```

Example:

```text
linux.local_baseline requires:

active Session
+
command execution support
+
target likely Linux
```

Precondition evaluation SHOULD be deterministic whenever possible.

---

# 11. Applicability

A Capability may exist but not currently be applicable.

Applicability is determined by:

```text
required input availability
preconditions
scope
policy
resource/session state
dependency availability
attempt history
```

The Capability Registry answers:

> What exists?

Applicability logic answers:

> What can usefully be invoked now?

These are different questions.

---

# 12. Procedure Registry

Procedures MUST be discoverable through a Procedure Registry.

The Registry SHOULD support querying by:

```text
goal type
environment
required state
produced state
technology
service family
workflow phase
```

Procedure identity SHOULD be stable and versioned.

Example:

```text
procedure.ad.baseline@1
procedure.web.jwt_assessment@1
procedure.poc.evaluate_candidate@1
```

---

# 13. Procedure Representation

Initial Procedures SHOULD use a structured declarative format.

Example conceptual structure:

```yaml
id: procedure.ad.baseline
version: 1

goal:
  type: coverage
  profile: active_directory_baseline

preconditions:
  - probable_active_directory

steps:

  - ensure:
      observation: smb.baseline
    using:
      capability: ad.smb_baseline

  - ensure:
      observation: ldap.baseline
    using:
      capability: ad.ldap_baseline

  - ensure:
      observation: kerberos.baseline
    using:
      capability: ad.kerberos_baseline

completion:
  coverage_profile: active_directory_baseline
```

Exact syntax MAY evolve.

The semantics SHOULD remain declarative.

---

# 14. Procedure vs Hard-Coded Python

Core orchestration SHOULD NOT be implemented as a growing collection of:

```python
if port_445:
    ...
if ldap:
    ...
if credential:
    ...
```

inside one central Python function.

Stable generic orchestration logic belongs in code.

Pentest-specific operational sequences SHOULD preferentially live in Procedures and registered rules.

---

# 15. Deterministic Rules

Not all behavior requires a Procedure.

Simple event-to-action rules MAY exist.

Example:

```text
new candidate credential
+
known compatible service
→ credential validation becomes applicable
```

Rules SHOULD produce:

```text
candidate action
```

rather than silently executing high-risk behavior.

Policy and orchestration still apply.

---

# 16. Coverage Engine

Coverage answers:

> Do we know enough about this assessment profile?

Coverage is based on required facts, not only executed tools.

Example:

```yaml
profile: active_directory_baseline

requirements:
  domain_identity:
    required: true

  smb_signing:
    required: true

  ldap_reachability:
    required: true

  kerberos_reachability:
    required: true
```

---

# 17. Coverage States

Each requirement SHOULD support:

```text
UNKNOWN
KNOWN
CONFLICTING
NOT_APPLICABLE
UNAVAILABLE
```

`UNAVAILABLE` means the system attempted reasonable methods but cannot currently obtain the information.

This is distinct from `UNKNOWN`.

---

# 18. Coverage Completion

A Coverage profile is complete when its completion policy is satisfied.

For strict profiles:

```text
all required facts =
KNOWN or NOT_APPLICABLE
```

Some profiles MAY allow:

```text
UNAVAILABLE
```

with explicit explanation.

The LLM MUST NOT arbitrarily declare Coverage complete.

---

# 19. Coverage vs Reasoning

Coverage decides:

> What facts are missing?

Reasoning decides:

> Which useful path should we pursue next?

Example:

```text
Coverage:
LDAP signing status unknown.

Reasoner:
Use capability A because existing credential and service state make it the most informative next action.
```

These responsibilities MUST remain distinct.

---

# 20. Event-Driven Reevaluation

Meaningful World State changes SHOULD trigger workflow reevaluation.

Examples:

```text
credential.available
session.created
access_context.elevated
service.discovered
finding.confirmed
resource.ready
interaction.resolved
```

The Workflow Engine SHOULD determine whether these events:

```text
satisfy goals
unlock new capabilities
invalidate pending actions
complete coverage
activate new procedures
```

---

# 21. Event Processing

Events are notifications.

World State remains authoritative.

A Workflow SHOULD NOT assume that an Event payload alone represents canonical truth.

Preferred flow:

```text
Event received
    ↓
query current World State
    ↓
evaluate implications
```

This prevents stale or duplicated events from corrupting orchestration.

---

# 22. Scheduler

The Workflow Engine MAY schedule multiple independent CapabilityRuns concurrently.

Concurrency SHOULD be allowed when operations:

```text
have satisfied preconditions
do not conflict on Resources/Sessions
do not violate policy
do not create unacceptable target load
```

Concurrency MUST respect Resource and Session leases.

---

# 23. Deterministic Decision Boundary

The system SHOULD prefer deterministic behavior when a rule can reliably produce one correct action.

Examples:

```text
Capability input missing
→ do not invoke

Session closed
→ do not schedule session-dependent capability

Required coverage fact already known
→ avoid duplicate test

Credential already validated against same service
→ suppress equivalent retry
```

LLM reasoning is unnecessary for these decisions.

---

# 24. LLM Reasoner Role

The Reasoner is used for decisions requiring interpretation or adaptation.

Examples:

```text
ambiguous technology identification

choosing among several plausible investigation paths

interpreting unstructured tool output

unknown PoC analysis

forming a diagnostic hypothesis

selecting a useful alternative after structured fallbacks fail

combining several weak signals

mapping documentation to current state
```

The Reasoner MUST operate through structured Core interfaces.

---

# 25. Reasoner Inputs

The LLM SHOULD receive a task-specific Context Projection.

Inputs MAY include:

```text
goal
relevant World State
available applicable capabilities
attempt history
relevant Procedure state
relevant knowledge retrieval
policy constraints
recent diagnostics
```

The LLM SHOULD NOT receive the entire Mission database automatically.

---

# 26. Reasoner Outputs

The Reasoner SHOULD return structured Decisions or Action Proposals.

Conceptually:

```yaml
decision:
  action: invoke_capability

  capability: web.technology_identification

  inputs:
    application_ref: app-17

  rationale:
    summary: >
      Current framework identification is ambiguous and this capability
      can resolve the missing version evidence.

  confidence: 0.84
```

The Core validates the proposal before execution.

---

# 27. LLM Cannot Execute Directly

The LLM MUST NOT directly:

```text
launch tools
open arbitrary shells
write World State
resolve unrestricted secrets
override policy
modify scope
```

It proposes platform actions.

Those actions pass through ordinary validation.

---

# 28. Reasoning Confidence

Reasoner decisions MAY include confidence.

Confidence MAY influence:

```text
automatic execution
request for additional evidence
human interaction
fallback behavior
```

Confidence MUST NOT override policy.

---

# 29. Decision Recording

Material decisions SHOULD be persisted.

A Decision record SHOULD include:

```text
decision_id
workflow_ref
goal
decision type
selected action
relevant evidence/state refs
source
timestamp
short rationale
```

Source may be:

```text
deterministic_rule
procedure
coverage_engine
llm
human
```

---

# 30. Human Decisions

When a human materially changes execution direction, the resulting choice SHOULD be recorded as a Decision.

Example:

```text
Human selected custom PoC payload variant.
```

The platform does not need to treat the resulting successful state differently from autonomous success.

Provenance does.

---

# 31. Attempt History

Before scheduling a meaningful action, the Workflow Engine SHOULD inspect Attempt history.

Attempt equivalence SHOULD consider meaningful normalized parameters.

Example:

```text
credential.validation

credential A
service B
protocol SMB
```

An identical previous successful or definitive negative Attempt may suppress re-execution.

---

# 32. Attempt Fingerprint

The system SHOULD derive an Attempt fingerprint from:

```text
capability
operation
subject/target
material input references
relevant normalized parameters
relevant state version/context
```

Secrets SHOULD be represented by references or safe hashes, not plaintext.

---

# 33. Changed-State Retry

A previous Attempt does not automatically forbid retry.

Retry may be valid when:

```text
parameters changed
credential changed
target state changed
AccessContext changed
implementation changed
new evidence exists
human explicitly requested retry
```

The Decision explaining the retry SHOULD be auditable.

---

# 34. Retry Safety

Capability-declared idempotency and side-effect semantics MUST influence retry.

Example:

```text
safe read operation
→ automatic retry may be reasonable

unknown PoC
→ automatic blind retry is not reasonable
```

Workflow logic MUST NOT override unsafe capability retry semantics without policy authorization.

---

# 35. Failure Categories

Workflow behavior depends on why an action failed.

Relevant categories include:

```text
execution failure
dependency failure
policy denial
scope denial
resource unavailable
target unreachable
authentication failure
negative assessment outcome
unknown result
human cancellation
```

These categories MUST NOT all collapse into:

```text
"step failed"
```

---

# 36. Execution Failure

Execution failure means the requested Capability operation could not be performed correctly.

Possible responses:

```text
retry where safe
choose alternate implementation
repair dependency
request human assistance
mark branch blocked
```

---

# 37. Negative Outcome

A negative outcome means the test completed correctly and did not confirm the expected condition.

Example:

```text
tested candidate exploit
→ target not vulnerable
```

This SHOULD usually advance reasoning rather than trigger execution-error handling.

---

# 38. Unknown Outcome

Unknown means evidence exists but its meaning is insufficiently determined.

The preferred escalation path is:

```text
preserve evidence
    ↓
deterministic interpretation if possible
    ↓
knowledge retrieval
    ↓
LLM interpretation
    ↓
additional diagnostic action
    ↓
human assistance if still unresolved
```

The system MUST NOT invent success or failure merely to close a branch.

---

# 39. Diagnostic Hypothesis Loop

For unresolved technical failures, Reasoner SHOULD prefer one diagnostic hypothesis at a time.

Example:

```text
Observation:
PoC executed but no callback.

Hypothesis:
target lacks bash.

Test:
check alternate execution primitive.
```

Then update World State/Attempt history and reevaluate.

This is preferable to uncontrolled random retries.

---

# 40. Bounded Exploration

Autonomous reasoning MUST be bounded.

A Procedure, Mission policy or Workflow MAY define limits such as:

```text
maximum retries
maximum equivalent attempts
maximum reasoning cycles
maximum runtime
maximum active branches
maximum human-interaction requests
```

The system SHOULD terminate or block branches that repeatedly fail without generating new information.

---

# 41. Progress

A Workflow SHOULD measure progress through state change or information gain.

Useful progress includes:

```text
new Observation
new Service
new Technology
new Credential
new Secret
new Session
new AccessContext
new Finding
new Effect
new ExploitCandidate
resolved uncertainty
completed Coverage requirement
```

Merely executing another command is not inherently progress.

---

# 42. Information Gain

When choosing among several safe investigation actions, the Reasoner MAY consider expected information gain.

Example:

```text
Action A likely confirms OS family.

Action B repeats an already weak fingerprint.

→ Action A preferred.
```

This may later become a formal scoring mechanism.

Workflow v1 does not require numeric utility scoring.

---

# 43. Capability Selection

Candidate capability selection SHOULD occur in stages:

```text
Goal / missing state
      ↓
find capabilities that can produce relevant result types
      ↓
filter by applicability
      ↓
filter by policy
      ↓
filter by attempt history
      ↓
deterministic preference if clear
      ↓
Reasoner if multiple meaningful candidates remain
```

The LLM SHOULD NOT search the entire capability universe blindly.

---

# 44. Capability Metadata for Planning

Capability definitions SHOULD expose enough semantic metadata for planning.

Future metadata MAY include:

```text
consumes
produces
requires
likely information produced
risk
cost
expected duration class
```

This metadata MUST remain declarative.

It MUST NOT guarantee actual target outcomes.

---

# 45. Procedure Nesting

A Procedure MAY invoke another Procedure.

Example:

```text
procedure.web.full_baseline
    ↓
procedure.web.technology_baseline
procedure.web.authentication_baseline
```

Nested procedures MUST retain separate runtime identity for audit and debugging.

Recursive procedure invocation SHOULD be prohibited unless explicitly designed and bounded.

---

# 46. Dynamic Procedure Activation

A Procedure MAY become applicable based on World State.

Example:

```text
Technology = JWT-based authentication
+
captured token available
→ activate JWT assessment procedure
```

Another:

```text
active command Session
+
OS likely Linux
→ activate Linux post-access baseline
```

Activation does not necessarily mean immediate execution.

Policy, Goals and scheduling still apply.

---

# 47. Discovery Can Create New Goals

A workflow MAY generate new subordinate Goals from discoveries.

Example:

```text
service discovery
→ web application identified
→ create goal: web baseline assessment
```

or:

```text
new Session obtained
→ create goal: establish AccessContext
→ create goal: post-access baseline
```

Goal creation SHOULD be rule- or procedure-driven where predictable.

LLM-created Goals MUST be validated by Core policy.

---

# 48. Goal Hierarchy

Goals MAY have parent-child relationships.

Example:

```text
Mission goal:
assess host X

    ├── discover services
    ├── assess web application
    └── assess local privilege state
```

A parent Goal may define completion as:

```text
all mandatory child goals satisfied
```

or another declared completion policy.

---

# 49. Strategic vs Tactical Reasoning

The system SHOULD distinguish:

```text
Strategic reasoning:
Which assessment branch should be pursued?

Tactical reasoning:
How should this specific current obstacle be handled?
```

Example strategic:

```text
SMB path or web path next?
```

Example tactical:

```text
Which payload family should this PoC try next?
```

These decisions may use different Context Projections and knowledge.

---

# 50. Capability-Local Adaptation

A capability MAY contain bounded local adaptation when that adaptation is intrinsic to the ability.

Example:

```text
network scanner may adjust timeout based on transport conditions
```

A capability SHOULD NOT contain broad strategic assessment branching.

Example of inappropriate capability-local behavior:

```text
service discovery found HTTP
→ automatically launch full web exploitation chain
```

That belongs to orchestration.

---

# 51. Human Interaction

Human Interaction is available to active CapabilityRuns and Workflows.

The system MUST support human assistance without terminating the Mission or losing current state.

Human interaction MAY be triggered when:

```text
structured automation reaches ambiguity
known fallbacks are exhausted
manual parameter choice is useful
artifact modification is required
operator judgment is explicitly configured
```

---

# 52. Workflow-Level Human Interaction

Not every InteractionRequest belongs to one capability.

A Workflow MAY itself request input.

Example:

```text
Two meaningful high-cost branches remain.

Which assessment path should receive priority?
```

Workflow-level interactions use the same Interaction Router concept but reference the Workflow instead of a CapabilityRun.

---

# 53. Human Interaction Is Not Failure

Entering:

```text
WAITING_INPUT
```

is not:

```text
FAILED
```

A Mission may continue other independent workflows while one branch waits for human input.

---

# 54. Interaction Routing

Interaction Router MAY support:

```text
human only
LLM first
human fallback
automatic default
policy-configured routing
```

The InteractionRequest itself does not decide who answers it.

---

# 55. Human Response Validation

Responses MUST be validated against the InteractionRequest schema.

Free-form human input SHOULD be normalized before becoming operational input.

If parsing fails, the Interaction remains unresolved rather than silently guessing.

---

# 56. Policy Approval

Policy Approval MUST remain separate from assistance.

Example:

```text
Assistance:
"What parameter should I use?"

Approval:
"May I perform this state-changing action?"
```

A human answer to an InteractionRequest MUST NOT bypass required approval.

---

# 57. Waiting for External Events

A Workflow MAY wait on a condition.

Examples:

```text
listener receives connection
resource becomes ready
credential becomes available
human response arrives
session becomes active
```

This should be represented as:

```text
WAITING
+
condition
```

rather than polling arbitrary runtime state from application code.

---

# 58. Wait Conditions

A WaitCondition SHOULD be serializable.

Example:

```yaml
type: event_or_state

event:
  type: session.created

state_predicate:
  session:
    source_resource_ref: listener-17
    state: ACTIVE

timeout: 600
```

After restart, the Workflow Engine can reconstruct the wait.

---

# 59. Workflow Checkpointing

Workflow runtime state MUST be persistable.

The engine SHOULD be able to recover after Core restart without losing:

```text
active goals
completed steps
waiting conditions
decision history
active CapabilityRun references
attempt relationships
```

The system MUST NOT rely solely on one long-lived Python coroutine representing an entire Mission.

---

# 60. Workflow Engine Architecture

The Workflow Engine SHOULD be designed as a persistent state machine / orchestration engine.

Initial implementation MAY be simple.

It does not require Temporal, Airflow or another external workflow product.

Core requirements are:

```text
persist state
evaluate transitions
start CapabilityRuns
wait on events/state
resume after restart
record decisions
```

---

# 61. Knowledge Router

The Workflow/Reasoning layer SHOULD access knowledge through a Knowledge Router.

The caller describes its information need.

The router decides whether to use:

```text
Procedure Registry
Curated Documentation
Semantic Retrieval
possibly external research
```

The Reasoner SHOULD NOT need direct knowledge of vector-database implementation details.

---

# 62. Procedural Knowledge Priority

When an authoritative Procedure exists for the current situation, it SHOULD generally take priority over free-form LLM planning.

Example:

```text
known AD baseline procedure
```

does not require the LLM to reinvent AD enumeration from scratch.

The Reasoner may still handle exceptions and ambiguity.

---

# 63. Curated Knowledge

Curated documentation supports questions such as:

```text
What does this protocol behavior imply?

What are common causes of this error?

What prerequisites does this technique require?
```

Retrieved documentation is evidence for reasoning.

It does not directly mutate World State.

---

# 64. Semantic Retrieval

Semantic retrieval SHOULD be used when:

```text
exact procedure lookup is insufficient
wording differs
the problem is contextual
multiple technical notes may be relevant
```

Semantic search SHOULD NOT replace deterministic lookup for known canonical Procedure IDs.

---

# 65. External Research

External research is conceptually different from internal knowledge retrieval.

Example:

```text
latest CVEs
GitHub PoCs
vendor advisories
current exploit repositories
```

Such actions SHOULD use explicit research capabilities/services.

External research results enter the system as:

```text
Artifacts
Observations
ExploitCandidates
```

rather than becoming invisible LLM knowledge.

---

# 66. Unknown PoC Procedure

A general reusable procedure SHOULD eventually represent:

```text
candidate vulnerability
        ↓
research candidate PoCs
        ↓
acquire artifact
        ↓
inspect artifact
        ↓
assess applicability
        ↓
construct ExecutionPlan
        ↓
validate/policy
        ↓
prepare runtime
        ↓
execute
        ↓
interpret result
```

The Procedure does not assume the PoC's language or execution behavior.

---

# 67. PoC Adaptation Loop

When a PoC does not achieve the desired effect:

```text
result
 ↓
classify failure/unknown state
 ↓
inspect evidence
 ↓
known deterministic fallback?
 ├── yes → attempt
 └── no
      ↓
knowledge + reasoner
      ↓
bounded adaptation
      ↓
human assistance if needed
```

Every materially different attempt SHOULD be represented in Attempt history.

---

# 68. Session Establishment as Goal

Many exploitation workflows SHOULD target:

```text
usable Session
```

or:

```text
desired AccessContext
```

rather than a specific payload.

Example:

```text
Goal:
active command-capable Session on host X
```

Then:

```text
bash reverse shell
Python callback
existing SSH credential
other execution channel
```

are alternative mechanisms.

This prevents workflows from becoming unnecessarily payload-specific.

---

# 69. Privilege Extension Procedure

A privilege procedure SHOULD focus on state transition.

Conceptually:

```text
current AccessContext
      ↓
local enumeration / evidence collection
      ↓
candidate privilege paths
      ↓
select applicable transition capability
      ↓
execute / verify
      ↓
new AccessContext
```

Completion:

```text
desired authority state reached
```

not:

```text
specific escalation command executed
```

---

# 70. Horizontal Access Procedure

Similarly:

```text
Credential / Session / Identity
        ↓
known reachable assets/services
        ↓
candidate access validation
        ↓
new Session
        ↓
new AccessContext
```

Horizontal and vertical transitions use the same orchestration primitives.

---

# 71. Cleanup Workflow

Effects with:

```text
cleanup.required = true
```

SHOULD be consumable by cleanup Procedures.

Mission completion policy MAY require:

```text
all mandatory cleanup Effects resolved
```

unless explicitly waived.

Cleanup is therefore an orchestration concern, not only reporting metadata.

---

# 72. Branching

A Workflow MAY have multiple simultaneous candidate branches.

Example:

```text
web application
SMB
SSH
```

The engine SHOULD distinguish:

```text
candidate branch
active branch
blocked branch
completed branch
abandoned branch
```

Branch management SHOULD be explicit enough to avoid repeated rediscovery of dead ends.

---

# 73. Branch Exhaustion

A branch may become EXHAUSTED when:

```text
all known applicable methods attempted
+
no new information generated
+
no reasonable knowledge-backed alternative remains
```

Exhaustion is not proof that no unknown solution exists.

The state SHOULD reflect this distinction.

---

# 74. Global Mission Continuation

One exhausted branch MUST NOT terminate the Mission while independent viable branches remain.

Example:

```text
web exploit branch exhausted
but SMB credential path remains
```

The scheduler continues other work.

---

# 75. Workflow Priority

Initial Workflow priority MAY be simple.

Factors MAY later include:

```text
Mission objective relevance
risk
cost
expected information gain
confidence
operator preference
required human interaction
```

Numeric optimization is not required for v1.

Deterministic priority classes are sufficient initially.

---

# 76. Safety and Scope in Planning

No Procedure, rule or LLM decision can make an otherwise invalid action valid.

Every proposed capability invocation still passes:

```text
input validation
scope validation
policy evaluation
dependency checks
```

Reasoning therefore operates within platform constraints.

---

# 77. Reasoning Failure

If the LLM is unavailable or fails:

```text
deterministic workflows
coverage
state management
capability execution
```

MUST remain functional.

Only adaptive reasoning-dependent branches may become blocked.

This is a fundamental architecture requirement.

---

# 78. LLM Replacement

Reasoning interfaces MUST NOT depend on one model vendor or one prompt format.

A Reasoner Provider abstraction SHOULD support:

```text
local LM Studio model
future larger local model
OpenAI model
other provider
```

Provider replacement MUST NOT change Workflow semantics.

---

# 79. Structured Reasoning Contract

The Reasoner SHOULD communicate through versioned structured schemas.

Example output classes:

```text
ActionProposal
InterpretationResult
Hypothesis
CandidateRanking
ExecutionPlanDraft
```

Free-form prose MAY accompany these objects.

Free-form prose MUST NOT be the only machine-consumed output.

---

# 80. Invalid Reasoner Output

Reasoner output MUST be validated.

If invalid:

```text
retry structured generation where reasonable
or
record Diagnostic
or
request human assistance
```

The Core MUST NOT infer arbitrary execution intent from malformed model prose.

---

# 81. Reasoner Hallucination Boundary

An LLM-proposed reference to:

```text
nonexistent Capability
nonexistent Session
nonexistent Artifact
out-of-scope target
```

MUST be rejected during validation.

The model is advisory, not authoritative.

---

# 82. Reasoning and Secrets

Reasoning Context SHOULD use SecretRefs unless plaintext is necessary for the reasoning task.

Secret resolution for model context MUST be explicit and policy-controlled.

The Reasoner MUST NOT automatically receive all available credential material.

---

# 83. Procedure Failure Handling

Procedures SHOULD explicitly describe common failure branches.

Example:

```text
operation failed because dependency unavailable
→ repair/alternate implementation

operation completed negative
→ mark condition disproven

operation result unknown
→ interpretation procedure

human input requested
→ wait
```

This reduces unnecessary LLM use.

---

# 84. Generic Unknown-Handling Procedure

The platform SHOULD provide a reusable unknown-result procedure.

Conceptual sequence:

```text
preserve raw evidence
      ↓
collect exit status/stdout/stderr
      ↓
check known error patterns
      ↓
search curated knowledge
      ↓
semantic retrieval
      ↓
LLM interpretation
      ↓
form diagnostic hypothesis
      ↓
test one hypothesis
      ↓
human assistance if unresolved
```

Identical blind execution MUST NOT be the default fallback.

---

# 85. Procedure Versioning

Procedures MUST be versioned independently from capabilities.

Changing a Procedure does not necessarily change Capability contracts.

Historical WorkflowRuns SHOULD retain which Procedure version they used.

---

# 86. Procedure Validation

Procedure definitions SHOULD be validated before activation.

Validation SHOULD detect:

```text
unknown capability IDs
invalid state predicates
unreachable declared steps where detectable
invalid completion conditions
invalid reference types
unsupported procedure version
```

---

# 87. Workflow Observability

The platform SHOULD expose a human-readable explanation of current orchestration state.

Examples:

```text
Current goal
Current branch
Why this capability is running
What it is waiting for
What was tried previously
Why a branch is blocked
Which Coverage facts remain unknown
```

This should be derivable from persisted Workflow/Decision state.

---

# 88. Explainability

The system does not require hidden LLM chain-of-thought for explainability.

Useful explanation consists of:

```text
facts considered
procedure/rule applied
selected action
short rationale
relevant evidence references
```

This information SHOULD be auditable without storing private model reasoning traces.

---

# 89. First Bootstrap Workflow

The first end-to-end Workflow SHOULD remain intentionally simple.

Input:

```text
one scoped IPv4 Asset
optional Credential
```

Goal:

```text
discover network services
```

Flow:

```text
Mission created
      ↓
Goal created
      ↓
network.service_discovery applicable
      ↓
CapabilityRun
      ↓
Observations
      ↓
World State updated
      ↓
Goal predicate evaluated
      ↓
service discovery Goal SATISFIED
```

No LLM is required.

---

# 90. Second Bootstrap Layer

Once service discovery is stable:

```text
World State services
      ↓
deterministic environment classification
      ↓
classification observations / derived state
      ↓
activate appropriate baseline Procedure
```

Again, LLM SHOULD only participate when deterministic classification is insufficient.

---

# 91. Reasoning Introduction

LLM reasoning SHOULD be introduced early enough to validate architecture, but not made mandatory for the first deterministic flow.

An early Reasoner use case may be:

```text
multiple ambiguous service/technology observations
        ↓
knowledge retrieval
        ↓
structured hypothesis
        ↓
proposed next capability
```

The deterministic platform remains responsible for execution.

---

# 92. Workflow Engine Persistence

Workflow state MUST survive application restart.

At minimum persist:

```text
WorkflowRun
Goal states
Procedure version
active CapabilityRun refs
waiting conditions
branches
Decisions
Attempts
completion state
```

The engine reconstructs active orchestration from persistence and World State.

---

# 93. Idempotent Workflow Reevaluation

Workflow reevaluation MUST tolerate duplicate Events.

Given unchanged World State and workflow state, repeated reevaluation SHOULD NOT create duplicate equivalent CapabilityRuns.

Attempt suppression and active-run checks are required.

---

# 94. Race Conditions

Before starting a proposed CapabilityRun, the engine SHOULD revalidate:

```text
goal still unsatisfied
preconditions still true
equivalent run not already active/completed
required Session/Resource still valid
policy still permits execution
```

This prevents asynchronous races.

---

# 95. Human Override

Mission policy MAY permit a human operator to:

```text
pause workflow
resume workflow
cancel branch
prioritize branch
request retry
supply interaction response
```

Human override actions SHOULD generate Decision/Audit records.

Human override MUST NOT silently bypass scope enforcement.

---

# 96. Completion

Mission completion is distinct from Workflow completion.

A Workflow completes when its Goal/completion policy is satisfied.

A Mission may contain multiple Workflows.

Mission completion policy MAY require:

```text
mandatory goals satisfied
mandatory coverage complete
no required cleanup pending
no critical active runs
```

Exact Mission completion policy is configurable.

---

# 97. Autonomous Run Boundary

"Run until it cannot continue" means:

```text
continue while at least one valid, policy-permitted,
non-duplicate action can make useful progress
```

The system SHOULD stop or wait when:

```text
all branches complete
all branches blocked
human input required
policy approval required
required external condition absent
bounded exploration exhausted
```

It MUST NOT generate arbitrary activity merely to remain busy.

---

# 98. Intelligence Growth Model

BoberAgent's effective capability grows through:

```text
more Capabilities
better Procedures
better Coverage definitions
better normalization
better knowledge
better Reasoning
better failure handling
```

The platform should therefore become more useful without requiring architectural redesign.

This is a primary success criterion.

---

# 99. Workflow and Reasoning Invariants

The following invariants MUST hold:

```text
Capabilities provide abilities; Workflows sequence them.

World State is authoritative for assessment facts.

Procedures are preferred over free-form planning where available.

Coverage is deterministic where possible.

LLM reasoning is advisory and structured.

LLM proposals pass ordinary validation.

Attempt history prevents blind repetition.

Unknown outcomes remain unknown until resolved.

Human interaction does not equal failure.

Policy approval is separate from assistance.

Goal satisfaction is preferably state-based.

No single exhausted branch ends the Mission if alternatives remain.

No LLM is required for deterministic platform operation.
```

---

# 100. Workflow v1 Acceptance Cases

The orchestration model MUST support without special-case architecture:

```text
service discovery → environment classification

new credential → validation workflow

web technology → vulnerability research

candidate CVE → PoC workflow

PoC failure → structured adaptation → human assistance

listener → incoming session → post-access procedure

new remote session → local enumeration

user-level session → privilege transition → elevated session

credential obtained on host A → access validation on host B

hash/JWT processing → new credential → authenticated session

target-side Effect → cleanup workflow
```

---

# 101. Implementation Rule for Coding Agents

A coding agent implementing orchestration MUST NOT introduce shortcuts such as:

```text
capability-specific hard-coded Core branches
tool-specific workflow logic in the central engine
LLM directly launching tools
workflow directly editing World State
retry loops that ignore Attempt history
busy polling where serializable wait conditions can be used
```

If a required behavior cannot be represented through:

```text
Goal
Procedure
Workflow
World State
Capability
Event
Decision
Attempt
WaitCondition
```

the architecture should be reviewed before adding a one-off exception.

---

# 102. Workflow and Reasoning v1 Acceptance Goal

The architecture is successful when BoberAgent can answer continuously:

```text
What is the current goal?

What facts do we already know?

What facts are missing?

What capabilities are applicable now?

What has already been attempted?

Which deterministic rule or Procedure applies?

Is reasoning actually necessary?

What useful action can make progress?

What are we waiting for?

Why did we choose this action?

When is the goal satisfied?
```

If these questions can only be answered by re-reading raw tool output or relying on undocumented LLM intuition, the orchestration model is insufficient.

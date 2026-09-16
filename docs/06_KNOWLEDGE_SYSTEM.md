# BoberAgent Core — Knowledge System v1

**Status:** Initial normative specification
**Document:** `docs/06_KNOWLEDGE_SYSTEM.md`
**Related:** `00_PROJECT_CONTEXT.md`, `01_SYSTEM_ARCHITECTURE.md`, `04_WORLD_STATE_MODEL.md`, `05_WORKFLOW_AND_REASONING.md`

---

# 1. Purpose

This document defines the BoberAgent Knowledge System.

The Knowledge System provides reusable technical knowledge to:

* Procedures;
* Workflows;
* Coverage logic;
* Reasoning;
* diagnostics;
* unknown-output interpretation;
* PoC inspection;
* capability selection.

The Knowledge System is not Mission state.

It does not represent what is currently true about a target.

---

# 2. Core Separation

The following concepts MUST remain distinct:

```text
World State
= What is currently known about this Mission and target.

Knowledge
= Reusable technical information applicable across Missions.

Procedure
= Operationally authoritative instructions for pursuing a bounded task.

Reasoner
= Uses World State + Knowledge + Procedures to make adaptive decisions.
```

Example:

```text
World State:
host-17 has SMB signing required.

Knowledge:
what SMB signing means and what assessment consequences it has.

Procedure:
how to perform the SMB baseline assessment.

Reasoner:
how that fact affects the current investigation.
```

Knowledge MUST NOT directly mutate World State.

---

# 3. Initial Knowledge Architecture

BoberAgent v1 contains four internal knowledge/reasoning layers:

```text
1. Procedure Registry
2. Curated Documentation
3. Semantic Retrieval
4. LLM Reasoner
```

A separate external research path exists for current public information.

GraphRAG is explicitly NOT required for v1.

---

# 4. Knowledge Authority Hierarchy

Knowledge sources have different authority.

Default precedence:

```text
Procedure Registry
        ↓
Canonical Curated Documentation
        ↓
Structured internal reference data
        ↓
Semantic retrieval results
        ↓
External research
        ↓
LLM prior knowledge
```

This ordering does not mean that a higher source is always more current.

It means that when BoberAgent has an explicitly maintained authoritative procedure or canonical project document, the LLM SHOULD NOT silently replace it with remembered model knowledge.

---

# 5. Procedure Registry

The Procedure Registry is the highest-authority operational knowledge source.

A Procedure describes how BoberAgent should pursue a bounded technical objective.

Procedures MAY define:

```text
goal
preconditions
required observations
required state
candidate capabilities
decision branches
fallbacks
known failure modes
completion conditions
coverage requirements
```

Procedures MUST be versioned.

---

# 6. Procedure Registry Is Not RAG

Procedure lookup SHOULD be deterministic.

Preferred:

```text
procedure ID
goal type
environment
technology
required/produced state
```

A known canonical Procedure MUST NOT depend solely on semantic-vector similarity to be found.

Semantic retrieval MAY help discover candidate Procedures when the caller does not know the exact identity.

The final selected Procedure remains a structured Registry object.

---

# 7. Procedure Canonicality

For one defined operational task, BoberAgent SHOULD prefer one canonical current Procedure.

Historical versions MAY remain available for:

```text
audit
replay
migration
historical WorkflowRuns
```

Multiple contradictory Procedures SHOULD NOT silently coexist as equally authoritative.

If alternatives intentionally exist, their applicability conditions MUST distinguish them.

---

# 8. Curated Documentation

Curated Documentation contains reusable explanatory and technical knowledge.

Examples:

```text
protocol behavior
tool behavior
common failure modes
technology characteristics
security concepts
known attack prerequisites
interpretation guidance
internal implementation notes
```

Curated Documentation should be deliberately maintained rather than accumulated indiscriminately.

---

# 9. Canonical Source Principle

BoberAgent SHOULD prefer:

> one canonical source of truth per maintained concept.

Unnecessary duplication harms:

```text
retrieval precision
maintenance
LLM interpretation
conflict resolution
```

Cross-references are preferred over copying the same explanation into multiple documents.

---

# 10. Documentation Format

Markdown is the preferred human-maintained source format for v1.

Documents SHOULD use predictable structure:

```text
title
purpose
scope
concepts
prerequisites
procedure/reference material
failure conditions
related knowledge
metadata
```

Machine-readable metadata MAY be stored in front matter.

---

# 11. Knowledge Metadata

Knowledge items SHOULD contain metadata such as:

```yaml
id: knowledge.smb.signing
version: 2

title: SMB Signing

type: reference

domains:
  - active_directory
  - smb

tags:
  - signing
  - relay

status: canonical

created_at: ...
updated_at: ...
```

Useful metadata MAY also include:

```text
technology
platform
tool
protocol
CVE
capability IDs
procedure IDs
OS family
version applicability
```

---

# 12. Stable Knowledge Identity

Canonical knowledge MUST use stable logical IDs.

File paths MAY be implementation details.

Preferred:

```text
knowledge.ldap.signing
procedure.ad.baseline
knowledge.jwt.hmac_signing
```

rather than using:

```text
Wiki/foo/bar/note-final-2.md
```

as the permanent identity.

---

# 13. Knowledge Versioning

Maintained Knowledge SHOULD support version metadata.

Material semantic changes SHOULD update the knowledge version or revision metadata.

Historical Mission Decisions SHOULD be able to preserve which source revision materially influenced them where practical.

---

# 14. Knowledge Lifecycle

Canonical items SHOULD support status such as:

```text
DRAFT
CANONICAL
DEPRECATED
ARCHIVED
```

Retrieval SHOULD prefer `CANONICAL`.

Deprecated content MAY remain retrievable when explicitly requested or when interpreting historical decisions.

---

# 15. Knowledge Provenance

Knowledge SHOULD retain source provenance.

Possible provenance:

```text
author-maintained
vendor documentation
project documentation
tool documentation
research publication
assessment-derived curated note
external source
```

Imported information MUST NOT lose knowledge of where it originated.

---

# 16. Observation Is Not Knowledge

Target-specific observations MUST NOT automatically enter reusable Knowledge.

Example:

```text
Host X accepts anonymous SMB
```

belongs to World State.

It does not automatically become reusable documentation.

Knowledge promotion requires an explicit curation process.

---

# 17. Assessment Learning

A Mission may expose a useful new pattern.

Example:

```text
unexpected tool error
specific workaround
new procedural branch
```

This MAY later become:

```text
Curated Documentation
Procedure update
failure pattern
```

but promotion MUST be deliberate.

BoberAgent v1 does not autonomously rewrite its authoritative Knowledge after every Mission.

---

# 18. Knowledge Promotion Pipeline

Recommended future flow:

```text
Mission experience
      ↓
candidate knowledge
      ↓
review
      ↓
canonicalization
      ↓
versioned knowledge update
      ↓
reindex
```

This avoids contaminating authoritative knowledge with incorrect one-off interpretations.

---

# 19. Semantic Retrieval

Semantic Retrieval provides fuzzy/contextual access to curated knowledge.

It is appropriate when:

```text
exact terminology is unknown
several documents may contribute
error wording differs
concepts are described indirectly
reasoning needs contextual reference material
```

Semantic Retrieval is not the canonical source itself.

It is a discovery mechanism.

---

# 20. Retrieval Backend Independence

The public Knowledge API MUST NOT depend on one specific vector database.

The initial implementation MAY use a local vector store.

The architecture MUST allow later replacement without changing:

```text
Workflow
Reasoner
Procedure
Capability
```

interfaces.

---

# 21. Embedding Provider Independence

Embedding generation MUST also be abstracted.

The Knowledge System SHOULD expose an embedding-provider interface.

A future change from one embedding model to another MUST NOT require rewriting semantic consumers.

Index metadata MUST identify the embedding configuration used.

---

# 22. Index Versioning

Semantic indexes are derived data.

They MUST be reproducible from canonical Knowledge sources.

The system SHOULD record:

```text
index version
embedding provider/model
chunking version
source revision
creation timestamp
```

Deleting/rebuilding a semantic index MUST NOT destroy canonical Knowledge.

---

# 23. Structural Chunking

Semantic indexing SHOULD preserve document structure.

Preferred chunk boundaries:

```text
headings
subheadings
procedure steps
concept sections
failure-mode sections
```

Arbitrary fixed-size slicing SHOULD NOT be the only chunking strategy for structured Markdown.

A chunk SHOULD retain:

```text
knowledge item ID
section path
source revision
metadata
```

---

# 24. Chunk Identity

Chunks SHOULD have stable or reproducibly generated identifiers.

Example:

```text
knowledge.jwt.hmac_signing
  /verification
  /chunk-2
```

This improves:

```text
provenance
debugging
cache behavior
reindex comparison
```

---

# 25. Retrieval Request

The Knowledge Router SHOULD accept structured retrieval requests.

Conceptually:

```yaml
purpose: interpret_failure

query: >
  LDAP connection resets while TLS negotiation starts.

context:
  tool: certipy
  protocol: ldaps

filters:
  domains:
    - active_directory
```

The caller SHOULD describe the knowledge need rather than vector-store implementation details.

---

# 26. Retrieval Response

A retrieval response SHOULD return structured results.

Conceptually:

```yaml
results:
  - knowledge_ref: knowledge.ldap.tls_failures
    section: certificate_requirements
    relevance: 0.91
    excerpt: ...
    provenance: ...
```

The Reasoner SHOULD receive source identities alongside retrieved text.

---

# 27. Hybrid Retrieval

The Knowledge Router SHOULD support combining:

```text
exact ID lookup
metadata filtering
lexical matching
semantic similarity
```

where useful.

Known identifiers SHOULD prefer exact lookup.

Semantic similarity SHOULD not override explicit exact constraints.

---

# 28. Retrieval Filtering

Useful filters MAY include:

```text
domain
technology
protocol
tool
OS
capability
procedure
document status
version applicability
```

Filtering before or during semantic retrieval SHOULD be preferred over retrieving unrelated material and asking the LLM to discard it.

---

# 29. Retrieval Quantity

The system SHOULD retrieve the smallest useful context rather than indiscriminately supplying entire documents.

Retrieval quantity may depend on task type.

Example:

```text
simple error interpretation
→ few focused sections

PoC/source analysis
→ larger supporting context
```

---

# 30. Context Quality Over Volume

More retrieved text is not automatically better.

BoberAgent SHOULD optimize for:

```text
relevance
authority
non-duplication
coverage
provenance
```

rather than raw token count.

---

# 31. Knowledge Router

Consumers SHOULD access internal knowledge through a Knowledge Router.

Conceptual API:

```text
lookup_procedure(...)
get_canonical(...)
search(...)
retrieve(...)
```

The Knowledge Router decides which internal mechanism is appropriate.

Callers SHOULD NOT directly manipulate vector-database queries.

---

# 32. Router Decision Order

For a knowledge request, the default resolution strategy SHOULD be:

```text
1. Explicit Procedure ID?
   → Procedure Registry

2. Explicit canonical Knowledge ID?
   → exact Knowledge lookup

3. Structured metadata query sufficient?
   → filtered lookup

4. Contextual/fuzzy query?
   → Semantic Retrieval

5. Current/external information required?
   → External Research path
```

The LLM MUST NOT decide to use stale internal material when the task explicitly requires current external information.

---

# 33. Procedure Retrieval

The Workflow Engine MAY ask:

```text
Which Procedure can pursue Goal X under State Y?
```

This SHOULD primarily use Procedure Registry metadata.

The LLM MAY help select among applicable Procedures when deterministic applicability does not identify a clear choice.

---

# 34. Knowledge and Coverage

Coverage definitions are structured operational metadata.

They SHOULD NOT be reconstructed from RAG text during every Mission.

Example:

```text
AD baseline requires LDAP signing state
```

belongs in:

```text
Coverage Profile / Procedure
```

not only in explanatory documentation.

---

# 35. Knowledge and Capability Metadata

Capability requirements and outputs belong in CapabilityDefinition.

They MUST NOT depend solely on Knowledge retrieval.

Knowledge can explain:

```text
why a capability is useful
what a result means
```

but the executable platform contract remains structured.

---

# 36. Knowledge and Tool Documentation

Tool-specific usage information MAY exist in Curated Documentation.

However, Capability implementations SHOULD encapsulate stable tool-specific invocation details.

The Reasoner SHOULD NOT have to retrieve an Nmap manual every time normal service discovery runs.

---

# 37. Failure Knowledge

Known failure patterns are highly valuable knowledge.

A curated failure item MAY define:

```text
symptoms
likely causes
discriminating tests
known fixes/workarounds
affected tools/versions
```

Example conceptual structure:

```yaml
symptoms:
  - TLS handshake reset

possible_causes:
  - service not actually speaking TLS
  - certificate/configuration issue
  - network device reset

diagnostic_tests:
  - ...
```

This supports bounded diagnostic reasoning.

---

# 38. Failure Knowledge vs Procedure Logic

If failure handling is deterministic and operationally authoritative, it SHOULD be encoded in a Procedure.

If it is explanatory or contains multiple contextual possibilities, it MAY remain Curated Documentation.

The two MAY reference each other.

---

# 39. External Research

External Research is separate from internal Knowledge.

It is used for information whose value depends on current external sources.

Examples:

```text
new CVEs
vendor advisories
GitHub PoCs
current exploit repositories
current tool documentation
recent security research
```

External Research SHOULD use explicit research capabilities or services.

---

# 40. External Research Is Observable Work

External research results MUST NOT exist only inside transient LLM context.

Material results SHOULD become:

```text
Artifact
Observation
ExploitCandidate
structured research result
```

with provenance.

---

# 41. Research Source Provenance

External research results SHOULD record:

```text
source URI/reference
retrieval timestamp
publisher/source identity
relevant version/date
Artifact reference where captured
```

The system SHOULD distinguish:

```text
vendor/primary source
maintainer source
third-party research
community discussion
unknown provenance
```

---

# 42. CVE Research

CVE research should be representable as a structured operation.

Inputs MAY include:

```text
Technology
version
platform
observed configuration
```

Outputs MAY include:

```text
candidate Vulnerabilities
external source Artifacts
applicability constraints
ExploitCandidates
```

A CVE match based only on a version string SHOULD remain a candidate until target applicability is established.

---

# 43. PoC Research

PoC discovery is distinct from PoC execution.

Research produces candidates and Artifacts.

Example:

```text
Vulnerability candidate
        ↓
external research
        ↓
ExploitCandidate
        ↓
repository/source Artifact
```

No discovered PoC becomes trusted executable code merely because it appeared in a search result.

---

# 44. PoC Knowledge Boundary

README or repository documentation is source material associated with an ExploitCandidate.

It is not automatically promoted into global canonical Knowledge.

It may be temporarily used for:

```text
inspection
ExecutionPlan generation
applicability reasoning
```

during that Mission.

---

# 45. Dynamic Mission Knowledge

Some retrieved information is useful only during one Mission.

Examples:

```text
PoC README
temporary vendor advisory
target-specific API documentation
downloaded source
```

This SHOULD be represented as Mission Artifacts and Context rather than being automatically ingested into the permanent curated Knowledge base.

---

# 46. LLM Reasoner

The LLM Reasoner consumes selected:

```text
Goal
World State projection
Procedure state
Capability metadata
Attempt history
Knowledge retrieval
Diagnostics
```

and produces structured reasoning outputs.

The Reasoner MUST NOT own canonical Knowledge.

---

# 47. Model Prior Knowledge

The LLM's pretrained/internal knowledge is the lowest-authority implicit knowledge source.

It MAY be useful for:

```text
general interpretation
hypothesis generation
connecting concepts
```

It MUST NOT silently override:

```text
current Procedure
canonical project documentation
current external source
structured World State evidence
```

---

# 48. Grounding Requirement

When a reasoning task depends materially on internal maintained knowledge, the Reasoner SHOULD receive retrieved source material.

When a task depends on current external facts, it SHOULD use External Research.

The Reasoner SHOULD NOT pretend current verification occurred when it did not.

---

# 49. Reasoning Provenance

Material Decisions influenced by Knowledge SHOULD record relevant knowledge references.

Example:

```yaml
decision:
  source: llm
  knowledge_refs:
    - knowledge.ldap.tls_failures@3
    - procedure.ldap.diagnostics@1
```

The full model prompt does not need to be persisted as the canonical explanation.

---

# 50. Context Builder

A Context Builder prepares model input.

It SHOULD combine only relevant:

```text
Goal
World State projection
active Workflow state
available applicable Capabilities
retrieved Knowledge
Attempt history
Diagnostics
```

It SHOULD NOT simply concatenate entire databases or vaults.

---

# 51. Context Budgeting

The Context Builder SHOULD manage a token/content budget.

Priority order SHOULD generally favor:

```text
current Goal
critical World State
applicable Procedure
recent relevant Attempts
high-authority Knowledge
supporting semantic results
```

Lower-relevance material SHOULD be omitted before higher-authority material.

---

# 52. Context Deduplication

Retrieved or assembled context SHOULD be deduplicated.

The same concept appearing in:

```text
Procedure
canonical documentation
several semantic chunks
```

SHOULD NOT necessarily be repeated verbatim.

The Context Builder MAY preserve references while reducing redundant text.

---

# 53. Conflict Handling

If retrieved Knowledge conflicts, the Reasoner SHOULD be informed of the conflict rather than receiving a falsely unified answer.

Conflict resolution SHOULD consider:

```text
authority
version
freshness
applicability
provenance
```

Canonical maintained sources generally outrank non-canonical internal notes.

Current primary external sources may supersede stale internal documentation for time-sensitive facts.

---

# 54. Freshness

Knowledge items MAY declare freshness characteristics.

Examples:

```text
stable concept
tool-version-sensitive
CVE/current-research-sensitive
volatile
```

The Knowledge Router SHOULD avoid serving obviously stale material for requests requiring current information.

---

# 55. Staleness Policy

A stale canonical document SHOULD remain identifiable as stale.

The system MUST NOT silently present stale material as current merely because it has high semantic similarity.

The Router MAY:

```text
warn
retrieve newer external source
request refresh
```

depending on task requirements.

---

# 56. Tool Version Applicability

Tool-specific Knowledge SHOULD identify version applicability where important.

Example:

```yaml
tool: netexec
versions:
  min: ...
  max: ...
```

If the active tool version falls outside that range, the result SHOULD be treated cautiously.

---

# 57. Knowledge Ingestion

Permanent Knowledge ingestion MUST be explicit.

A source passes through:

```text
source acquisition
      ↓
normalization
      ↓
metadata assignment
      ↓
structural validation
      ↓
canonical storage
      ↓
indexing
```

Semantic indexing alone MUST NOT constitute successful canonical ingestion.

---

# 58. Ingestion Validation

Ingestion SHOULD reject or quarantine malformed canonical content.

Examples:

```text
missing identity
invalid metadata
unsupported Procedure schema
broken references
duplicate canonical ID
```

Failing semantic embedding generation MUST NOT destroy the canonical source.

---

# 59. File Change Tracking

For file-backed Knowledge, the system SHOULD track:

```text
content hash
revision
last indexed revision
```

Only changed sources need reprocessing.

This is preferable to blind full-vault rebuilding.

---

# 60. Knowledge Storage

Canonical v1 Knowledge MAY live in a repository-backed directory structure.

Example:

```text
knowledge/
├── procedures/
├── reference/
├── failures/
├── technologies/
├── protocols/
└── tools/
```

The exact directory layout is secondary to stable Knowledge IDs and metadata.

---

# 61. Suggested Procedure Layout

Example:

```text
knowledge/procedures/
├── network/
├── active_directory/
├── web/
├── post_access/
├── credentials/
├── vulnerability_research/
└── poc/
```

Procedures SHOULD remain readable by humans and machines.

---

# 62. Suggested Reference Layout

Example:

```text
knowledge/reference/
├── protocols/
├── technologies/
├── vulnerability_classes/
├── authentication/
├── operating_systems/
└── concepts/
```

Tool-specific references MAY live separately.

---

# 63. Semantic Index Content

The semantic index SHOULD initially include:

```text
canonical Curated Documentation
selected Procedure descriptions/sections
known failure documentation
```

Highly structured Procedure execution data SHOULD remain directly queryable outside semantic retrieval.

---

# 64. What Should Not Be Permanently Indexed by Default

The permanent Semantic Knowledge index SHOULD NOT automatically absorb:

```text
raw Mission Artifacts
all scanner output
temporary PoC repositories
all shell output
every external web result
private Mission state
plaintext secrets
```

These belong to other storage domains.

---

# 65. Mission-Scoped Retrieval

Mission Artifacts MAY support temporary scoped retrieval when useful.

For example:

```text
large PoC repository
target API documentation
downloaded source tree
```

This retrieval MUST remain distinguishable from permanent global Knowledge.

---

# 66. Global vs Mission Knowledge Namespace

The Knowledge Router SHOULD distinguish:

```text
global curated knowledge
mission-scoped temporary reference material
external research material
```

Queries MAY explicitly select one or more scopes.

---

# 67. Sensitive Knowledge

Permanent Knowledge SHOULD generally avoid containing secrets.

Mission-scoped retrieval MUST respect SecretRef and Artifact access policy.

Embedding plaintext secrets into general vector indexes is prohibited.

---

# 68. Knowledge API

The Core SHOULD expose a service similar conceptually to:

```python
knowledge.get(ref)
knowledge.find_procedures(...)
knowledge.search(...)
knowledge.retrieve(...)
```

Consumers MUST NOT depend directly on:

```text
Qdrant client
embedding implementation
filesystem traversal
Obsidian API
```

---

# 69. Existing Obsidian Knowledge

Obsidian may continue to serve as a human-friendly authoring environment.

BoberAgent MUST NOT require Obsidian-specific semantics inside Workflow or Reasoning code.

If Obsidian is used, an ingestion layer maps maintained notes into the canonical Knowledge model.

The vault is a source/content-authoring surface, not the runtime architecture itself.

---

# 70. Existing GraphRAG System

The existing GraphRAG project MAY be used as a design/reference source for:

```text
provenance
structured retrieval responses
source hydration
versioned schemas
deterministic planning
hybrid retrieval
change detection
```

BoberAgent v1 MUST NOT depend on the existing GraphRAG service as a required runtime component.

Graph-specific entity/relationship extraction is not required initially.

---

# 71. Why GraphRAG Is Deferred

BoberAgent already has strong relationship-rich data in World State.

A separate Knowledge Graph should only be introduced when a demonstrated reusable-knowledge retrieval problem requires relationship traversal beyond what:

```text
structured metadata
Procedure Registry
Curated Documentation
Semantic Retrieval
```

can solve.

Architecture SHOULD be driven by observed need rather than technology availability.

---

# 72. LLM Provider Independence

Knowledge reasoning MUST not assume LM Studio specifically.

A provider adapter SHOULD support model invocation.

Initial deployment MAY use LM Studio.

Future providers MAY include:

```text
larger local model
different local runtime
external model provider
```

Knowledge retrieval and Procedure semantics remain unchanged.

---

# 73. Model Capability Limits

The system SHOULD assume the LLM can fail to:

```text
follow long instructions
interpret noisy data
select correct source
produce valid structured output
```

Architecture compensates through:

```text
focused context
schemas
retrieval filtering
validation
Procedures
deterministic rules
```

The Knowledge System must not rely on model perfection.

---

# 74. Structured Reasoning Outputs

Knowledge-assisted Reasoning SHOULD return typed outputs such as:

```text
InterpretationResult
Hypothesis
ActionProposal
CandidateAssessment
ExecutionPlanDraft
```

rather than relying only on prose.

These outputs remain subject to Core validation.

---

# 75. Knowledge Does Not Authorize Action

Retrieved Knowledge may recommend an operation.

It cannot bypass:

```text
Capability availability
Scope
Policy
Approval
Attempt history
Resource constraints
```

Knowledge answers:

> what may make technical sense.

The platform decides:

> what may actually execute.

---

# 76. RAG Failure

Semantic Retrieval failure MUST NOT break deterministic platform operation.

If the semantic backend is unavailable:

```text
Procedure Registry
exact canonical lookup
Capabilities
World State
deterministic Workflows
```

MUST remain usable.

Reasoning branches dependent on semantic knowledge MAY become degraded or blocked.

---

# 77. LLM Failure

Likewise, an unavailable LLM MUST NOT disable:

```text
deterministic Procedures
Coverage
World State
Capability execution
exact knowledge lookup
```

This ensures BoberAgent remains a functioning platform rather than merely an LLM frontend.

---

# 78. Knowledge Diagnostics

Knowledge services SHOULD expose Diagnostics for:

```text
no result
stale result
index unavailable
source conflict
invalid Procedure
unsupported source revision
embedding mismatch
```

Reasoner MUST NOT interpret `no retrieval result` as proof that relevant knowledge does not exist.

---

# 79. Evaluation

Knowledge quality SHOULD be tested.

Useful evaluation categories include:

```text
exact Procedure resolution
canonical-document lookup
semantic retrieval relevance
failure-pattern retrieval
source provenance preservation
duplicate suppression
context size
staleness handling
```

A Knowledge System that merely returns semantically similar text is insufficient.

---

# 80. Retrieval Test Corpus

The project SHOULD maintain retrieval regression tests.

Example:

```text
query:
"LDAP works on 389 but authentication is rejected because signing is required"

expected relevant:
knowledge.ldap.signing

must_not_prioritize:
unrelated TLS documentation
```

This prevents silent degradation when changing:

```text
embeddings
chunking
metadata
vector backend
```

---

# 81. Procedure Tests

Procedures SHOULD have structural and behavioral tests.

Tests MAY verify:

```text
valid referenced Capabilities
valid state predicates
valid completion criteria
expected branches
known failure handling
```

Critical Procedures SHOULD be exercised against synthetic World State fixtures.

---

# 82. Knowledge Auditability

For any materially Knowledge-driven Decision, the platform SHOULD be able to answer:

```text
Which sources were retrieved?
Which source versions?
Which Procedure was active?
Was external research used?
Which model produced the Decision?
```

This is sufficient operational explainability.

Hidden model reasoning is not required.

---

# 83. Knowledge Security Boundary

Knowledge ingestion and retrieval MUST respect data classification.

Examples:

```text
global reusable knowledge
private Mission Artifact
secret material
external public source
```

These MUST NOT be indiscriminately merged into one searchable index.

---

# 84. Initial Implementation Recommendation

The v1 Knowledge implementation SHOULD prioritize simplicity.

Required components:

```text
Knowledge Repository
Procedure Registry
metadata parser
structural Markdown parser
Knowledge Router
Semantic Index abstraction
Embedding Provider abstraction
retrieval service
Context Builder
```

No graph database is required.

No autonomous knowledge rewriting is required.

---

# 85. Initial End-to-End Retrieval Flow

Example:

```text
Workflow encounters unknown tool behavior
        ↓
Knowledge Router
        ↓
exact failure pattern lookup
        ↓
no exact match
        ↓
semantic retrieval
        ↓
relevant curated failure documentation
        ↓
Context Builder
        ↓
LLM Reasoner
        ↓
structured diagnostic hypothesis
        ↓
Workflow validates proposed next action
```

---

# 86. Initial Procedure Flow

Example:

```text
World State indicates probable Active Directory
        ↓
Procedure Registry lookup
        ↓
procedure.ad.baseline
        ↓
Workflow instantiation
        ↓
Coverage requirements
        ↓
Capability invocations
```

The LLM is unnecessary for the normal path.

---

# 87. CVE/PoC Knowledge Flow

Example:

```text
World State:
Technology + version

        ↓

Procedure:
vulnerability research

        ↓

External Research Capability

        ↓

candidate Vulnerability(s)

        ↓

PoC research

        ↓

ExploitCandidate + repository Artifact

        ↓

Mission-scoped artifact inspection

        ↓

relevant internal PoC/runtime Knowledge

        ↓

LLM Reasoner

        ↓

ExecutionPlanDraft
```

This flow deliberately separates:

```text
internal reusable knowledge
current external research
mission-specific PoC source
reasoning
execution
```

---

# 88. Knowledge Promotion Example

After a Mission:

```text
PoC failed with uncommon runtime condition.
Human identified repeatable cause and workaround.
```

This SHOULD NOT automatically rewrite the Knowledge base.

Instead:

```text
candidate lesson
      ↓
review
      ↓
new failure Knowledge item
or Procedure update
      ↓
canonical version
      ↓
reindex
```

---

# 89. Knowledge Invariants

The following invariants MUST hold:

```text
Knowledge and World State are separate.

Procedures are structured and versioned.

Known Procedures do not depend solely on semantic search.

Curated documentation is authoritative over model memory.

Semantic indexes are derived, rebuildable data.

Raw Mission data does not automatically become global Knowledge.

External research remains separately sourced and timestamped.

Retrieved text does not directly mutate World State.

LLM prior knowledge does not override canonical maintained sources.

Secrets do not enter general semantic indexes.

GraphRAG is not required for v1.

Knowledge backend implementations remain replaceable.
```

---

# 90. Stress Cases

The Knowledge System MUST naturally support:

```text
deterministic AD baseline Procedure

tool-error diagnosis

JWT/cookie assessment guidance

hash-recovery guidance

unknown technology interpretation

CVE research

unknown GitHub PoC inspection

runtime preparation guidance

privilege-escalation reasoning

human-assisted troubleshooting
```

No case should require mixing permanent Knowledge with Mission state.

---

# 91. Implementation Rule for Coding Agents

A coding agent implementing the Knowledge System MUST NOT introduce shortcuts such as:

```text
feeding the entire vault to the LLM

using semantic RAG as the only Procedure lookup

writing retrieved knowledge into World State as fact

automatically ingesting arbitrary Mission Artifacts globally

embedding plaintext secrets

hard-coding one vector database into Workflow logic

making GraphRAG a hidden mandatory dependency

allowing LLM memory to silently override canonical project knowledge
```

If a use case appears to require one of these shortcuts, the architecture must be reviewed.

---

# 92. Knowledge System v1 Acceptance Goal

The Knowledge architecture is successful when BoberAgent can reliably answer:

```text
Do we already have an authoritative Procedure for this?

What canonical internal knowledge explains this situation?

What contextual documentation is most relevant?

Does this question require current external research?

Which sources support the Reasoner's conclusion?

Is the retrieved material current and applicable?

Can the system continue if semantic retrieval or the LLM is temporarily unavailable?
```

and can do so without confusing:

```text
what the target currently is
```

with:

```text
what BoberAgent generally knows.
```

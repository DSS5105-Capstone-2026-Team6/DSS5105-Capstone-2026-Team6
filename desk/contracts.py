"""
contracts — the structured records the dispatcher desk passes around.

Every record must survive a round trip through JSON: they are the units the
audit log stores (AllocationRecord), the evaluation scores (Decision), and
the data the UI renders (Candidate). Stdlib dataclasses only — no new
dependencies. Dates arrive as ISO strings ("2026-04-01"), as they do in the
CSV files, so serialization stays trivial.

Desk layer layout:
    desk/contracts.py  this file — the records
    desk/state.py      the chat-side queue snapshot (to come)
    desk/audit.py      append-only JSONL audit log (to come)
    desk/desk.py       DispatchDesk: LLM + tools + state + audit (to come)
"""

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from uuid import uuid4
from typing import Optional


class Behaviour(Enum):
    """The six routing behaviours from the roadmap (Table 3). The routing
    code — never the LLM — assigns one; the evaluation scores against it."""
    ALLOCATE = "allocate"
    ASK = "ask"
    REFUSE = "refuse"
    IMPOSSIBLE = "impossible"
    ANSWER = "answer"
    NO_DATA = "no_data"


@dataclass
class ChatRequest:
    """One line of the dispatch group chat, envelope already split."""
    request_id: str
    time: str
    speaker: str
    text: str


@dataclass
class Constraint:
    """A named constraint with its originator (roadmap: always record who
    imposed it). target is the object of the constraint, e.g. the excluded
    workshop for kind='exclude'."""
    kind: str                          # exclude | cheapest | fastest | lowest_defect | split | due_date
    originator: str                    # who imposed it (Boss, Ravi, customer...)
    target: Optional[str] = None
    raw_text: str = ""                 # the words they actually used


@dataclass
class ParsedRequest:
    """The LLM's structured extraction of one chat message."""
    order_id: Optional[str] = None
    pieces: Optional[int] = None
    category: Optional[str] = None       # TOPS | ACCESSORIES
    due_date: Optional[str] = None       # ISO date
    suggested_workshop: Optional[str] = None
    constraints: list = field(default_factory=list)   # list[Constraint]


@dataclass
class Candidate:
    """One workshop the allocator scored for an order."""
    workshop_id: str
    name: str
    estimated_finish: str              # ISO date
    days_late: float
    cost: float
    defect_risk: float
    components: dict = field(default_factory=dict)   # queue/work/transport breakdown


@dataclass
class Decision:
    """The outcome of handling one request: what the desk decided, on what
    evidence. The evaluation scores decisions against the labelled inbox."""
    request_id: str
    behaviour: Behaviour
    parsed: ParsedRequest = field(default_factory=ParsedRequest)
    candidates: list = field(default_factory=list)   # list[Candidate]
    chosen: Optional[Candidate] = None
    explanation: str = ""
    options: list = field(default_factory=list)      # ASK: tappable choices (order ids)
    tool_log: list = field(default_factory=list)
    created_at: str = ""               # ISO timestamp
    decision_id: str = field(default_factory=lambda: uuid4().hex)
    state_version: Optional[str] = None
    objective: str = "lateness"
    excluded: list = field(default_factory=list)


@dataclass
class AllocationRecord:
    """One committed allocation, written append-only to the audit log —
    the structured record the group chat lacks."""
    record_id: str
    decision_id: str
    order_id: str
    workshop_id: str
    pieces: int
    committed_by: str                  # the human who confirmed
    committed_at: str                  # ISO timestamp
    queue_before: float = 0.0          # workshop queue (days) before commit
    queue_after: float = 0.0           # after: before + expected work
    evidence: dict = field(default_factory=dict)


def to_dict(obj):
    """Any contract record -> plain JSON-serialisable dict (Enums become
    their string values, dataclasses recurse)."""
    if is_dataclass(obj):
        return {f.name: to_dict(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (list, tuple)):
        return [to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


def decision_from_dict(d):
    d = dict(d)
    d["behaviour"] = Behaviour(d["behaviour"])
    d.setdefault("options", [])          # records from before the field existed
    parsed = dict(d["parsed"])
    parsed["constraints"] = [Constraint(**c)
                             for c in parsed.pop("constraints", [])]
    d["parsed"] = ParsedRequest(**parsed)
    d["candidates"] = [Candidate(**c) for c in d["candidates"]]
    if d.get("chosen") is not None:
        d["chosen"] = Candidate(**d["chosen"])
    return Decision(**d)


def allocation_from_dict(d):
    return AllocationRecord(**d)


if __name__ == "__main__":
    import json
    decision = Decision(
        request_id="R08", behaviour=Behaviour.REFUSE,
        parsed=ParsedRequest(order_id="ORD-073", pieces=400, category="TOPS",
                             suggested_workshop="FreshStart"),
        candidates=[Candidate("W1", "QuickStitch", "2026-04-08", 0.0, 600.0, 0.12,
                              {"queue": 4.0, "work": 1.3, "transport": 1.0})],
        explanation="FreshStart cannot take 400 pieces (300-piece cap).",
        tool_log=[{"tool": "check_eligibility", "arguments": {"category": "TOPS"},
                   "result": {"eligible_count": 5}}],
        created_at="2026-04-01T08:30:00")
    as_json = json.dumps(to_dict(decision), ensure_ascii=False, indent=2)
    print(as_json)
    assert json.loads(as_json)["behaviour"] == "refuse"
    back = decision_from_dict(json.loads(as_json))
    assert back == decision and back.behaviour is Behaviour.REFUSE
    print("\nround trip OK")

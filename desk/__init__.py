"""The dispatcher desk layer: chat-side state, audit log, and orchestration.

contracts.py — the records (Decision, AllocationRecord, ...)
state.py     — DeskState: the chat-side queue snapshot (1 Apr), moved only by commits
audit.py     — AuditLog: append-only JSONL, one line per committed allocation
desk.py      — DispatchDesk: LLM + tools + state + audit behind handle()/confirm()
"""

"""Read-only interpretation of a follow-up, scoped to one displayed proposal."""
import re
from dataclasses import dataclass

from desk.contracts import canonical_order_id

YES = {'yes', 'y', 'yep', 'yes please', 'ok', 'okay', 'sure', 'commit', 'confirm',
       'confirmed', 'go ahead', 'please do', 'do it', 'sounds good', '确认', '好的',
       '行', '可以', '就这样', '确认吧', '好', '就这么办', '没问题'}
CANCEL = {'no', 'cancel', 'stop', 'wait', 'hold on', 'not yet', '取消', '先等等',
          '等等', '先别下单', '暂停', '算了'}
# These messages must be interpreted as questions/changes, never a confirmation.
BLOCKERS = re.compile(
    r"\?|？|\b(?:no|not|never|don\W?t|cannot|can\W?t|but|unless|if|wait|cancel|"
    r"change|instead|maybe|could|would|can|should|why|what|how)\b|"
    r"不|别|不要|取消|等等|但是|不过|如果|改|能否|是否|可以吗|行吗|为什么|怎么|？", re.I)


@dataclass
class FollowupIntent:
    intent: str
    workshop_id: str | None = None
    changes: tuple = ()
    exclude_add: tuple = ()
    exclude_remove: tuple = ()


def normalise(text):
    return (text or '').strip().lower().rstrip('.!。！').strip()


def looks_like_confirmation(text):
    return normalise(text) in YES


def commit_intent_workshop(text, decision):
    """Fast, complete-utterance matches; unknown phrasing uses the API classifier."""
    t = normalise(text)
    if looks_like_confirmation(t):
        return decision.chosen.workshop_id if decision.chosen else None
    if BLOCKERS.search(t):
        return None
    for c in decision.candidates or []:
        names = '(?:' + '|'.join(re.escape(x.lower()) for x in (c.workshop_id, c.name)) + ')'
        order = re.escape(decision.parsed.order_id or 'this order').lower()
        patterns = [
            rf'(?:please\s+)?(?:commit|confirm|book|send|assign|place)(?:\s+(?:it|this order|{order}))?\s+(?:to\s+)?{names}(?:\s+please)?',
            rf'(?:please\s+)?(?:use|go with)\s+{names}(?:\s+please)?',
            rf'(?:这单|这个订单)?(?:就给|就发给|派给|定给|就用|确认给|确认)\s*{names}(?:\s*(?:吧|好了))?',
        ]
        if any(re.fullmatch(p, t) for p in patterns):
            return c.workshop_id
    return None


def fast_intent(text, decision):
    if normalise(text) in CANCEL:
        return FollowupIntent('cancel')
    wid = commit_intent_workshop(text, decision)
    if wid:
        return FollowupIntent('confirm', wid)
    return None


def validate_intent(payload, text, decision):
    """Treat classifier output as untrusted; bind every confirmation to this order."""
    if not isinstance(payload, dict):
        return FollowupIntent('other')
    if set(payload) - {'intent', 'order_id', 'workshop_id', 'changes', 'exclude_add', 'exclude_remove'}:
        return FollowupIntent('other')
    intent = payload.get('intent')
    if intent not in {'confirm', 'question', 'modify', 'cancel', 'other'}:
        return FollowupIntent('other')
    changes = payload.get('changes', [])
    if not isinstance(changes, list) or any(not isinstance(x, str) or x not in
            {'excluded', 'objective', 'pieces', 'due_date', 'other'} for x in changes):
        return FollowupIntent('other')
    edits = []
    for field in ('exclude_add', 'exclude_remove'):
        values = payload.get(field, [])
        if not isinstance(values, list) or any(not isinstance(x, str) or
                not re.fullmatch(r'W[1-9][0-9]*', x) for x in values):
            return FollowupIntent('other')
        edits.append(tuple(values))
    wid = payload.get('workshop_id')
    if intent == 'confirm':
        ids = {c.workshop_id for c in decision.candidates}
        mentioned_orders = re.findall(r'\bORD[\s_-]*\d+\b', text, flags=re.I)
        if (BLOCKERS.search(text) or changes or any(edits)
                or canonical_order_id(payload.get('order_id')) != decision.parsed.order_id
                or not isinstance(wid, str) or wid not in ids
                or any(canonical_order_id(x) != decision.parsed.order_id for x in mentioned_orders)):
            return FollowupIntent('other')
    return FollowupIntent(intent, wid, tuple(changes), *edits)

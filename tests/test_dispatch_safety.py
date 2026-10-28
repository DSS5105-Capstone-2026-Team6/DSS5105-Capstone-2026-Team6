"""Network-free regressions. Also runnable without third-party dependencies:
python -m unittest discover -s tests -p test_dispatch_safety.py -v
"""
import ast
import json
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from adapter.session import ChatSession
from desk.agent import DispatchAgent, load_api_key
from desk.audit import AuditLog
from desk.budget import BudgetExceeded, CallBudget
from desk.confirmation import FollowupIntent, commit_intent_workshop, validate_intent
from desk.contracts import Behaviour, Decision, ParsedRequest, canonical_order_id, to_dict
from desk.desk import DispatchDesk, ProposalChanged
from desk.tools import dispatch_tool, tool_schemas
from eval.score_run import score_run


class FakeAgent:
    def __init__(self):
        from desk.register import WorkshopStore
        self.workshops = WorkshopStore()
        self.history = []
        self.tool_log = []
        self.intent = FollowupIntent('other')
        self.next_order = 'ORD-041'
        self.excluded = []

    def classify_followup(self, text, decision):
        return self.intent

    def chat(self, text, verbose=False):
        args = {'order_id': self.next_order, 'excluded': self.excluded}
        result = dispatch_tool('rank_candidates', args, desk=self.desk)
        self.tool_log = [{'tool': 'rank_candidates', 'arguments': args, 'result': result}]
        self.history += [{'role': 'user', 'content': text},
                         {'role': 'assistant', 'content': 'Review and confirm.'}]
        return 'Review and confirm.'


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'audit.jsonl'
        self.env = patch.dict(os.environ, {'DISPATCH_DB_PATH': str(Path(self.temp.name)/'runtime.sqlite3')})
        self.env.start()
        self.addCleanup(self.env.stop)

    def desk(self):
        return DispatchDesk(agent=FakeAgent(), audit_path=self.path)

    def proposal(self, desk, order='ORD-041'):
        desk.agent.next_order = order
        return desk.handle_message('allocate ' + order, requester='Ravi')

    def test_model_tools_cannot_commit(self):
        desk = self.desk()
        self.assertNotIn('commit_allocation', [s['function']['name'] for s in tool_schemas()])
        result = dispatch_tool('commit_allocation', {'order_id':'ORD-041','workshop_id':'W6'}, desk=desk)
        self.assertIn('error', result)
        self.assertEqual(desk.audit.load_all(), [])

    def test_negative_conditional_and_questions_never_fast_commit(self):
        d = self.proposal(self.desk())
        for text in ['do not commit to W2', 'can we use W2?', 'yes, but wait',
                     'do not use SteadyHands', 'use W20', '如果可以就给W2',
                     '确认给W2吗？', '确认 W2 然后数量改成200']:
            with self.subTest(text=text):
                self.assertIsNone(commit_intent_workshop(text,d))

    def test_normal_confirmation_remains_one_step(self):
        desk=self.desk(); d=self.proposal(desk)
        for text in ['yes', '好的', '就这样', '确认吧']:
            self.assertEqual(commit_intent_workshop(text,d),d.chosen.workshop_id)
        self.assertEqual(commit_intent_workshop('这单就给 W2 吧',d),'W2')
        _, record, _ = desk.follow_up('好的',d)
        self.assertIsNotNone(record)

    def test_classifier_output_is_bound_to_order_and_candidates(self):
        d=self.proposal(self.desk())
        payload={'intent':'confirm','order_id':d.parsed.order_id,'workshop_id':'W2','changes':[]}
        self.assertEqual(validate_intent(payload,'please proceed with SteadyHands',d).intent,'confirm')
        for bad in [dict(payload,order_id='ORD-063'),dict(payload,workshop_id='W7'),
                    dict(payload,changes=['pieces'])]:
            self.assertNotEqual(validate_intent(bad,'proceed',d).intent,'confirm')
        self.assertNotEqual(validate_intent(payload,'do not commit W2',d).intent,'confirm')
        self.assertNotEqual(validate_intent(payload,'send ORD-063 to W2',d).intent,'confirm')

    def test_cancel_clears_pending(self):
        session=ChatSession(self.desk)
        session.handle('allocate ORD-041')
        session.handle('先等等')
        self.assertIsNone(session.pending)
        session.handle('好的')
        self.assertEqual(session.desk.audit.load_all(),[])

    def test_modify_updates_candidates(self):
        desk=self.desk(); d=self.proposal(desk)
        desk.agent.intent=FollowupIntent('modify',changes=('excluded',))
        desk.agent.excluded=['W2']
        updated, record, _=desk.follow_up('不要给 W2',d)
        self.assertIsNone(record)
        self.assertNotIn('W2',[c.workshop_id for c in updated.candidates])
        self.assertEqual(updated.excluded,['W2'])
        self.assertNotEqual(updated.decision_id,d.decision_id)

    def test_source_order_edits_invalidate_proposal(self):
        desk=self.desk(); d=self.proposal(desk)
        desk.agent.intent=FollowupIntent('modify',changes=('pieces',))
        updated,record,reply=desk.follow_up('change quantity to 200',d)
        self.assertIsNone(updated); self.assertIsNone(record)
        self.assertIn('register',reply)
        self.assertEqual(desk.audit.load_all(),[])

    def test_sessions_and_restart_read_same_queues(self):
        a=self.desk(); b=self.desk()
        d=self.proposal(a)
        a.confirm(replace(d,chosen=next(c for c in d.candidates if c.workshop_id=='W6')))
        self.assertAlmostEqual(a.state.queues['W6'],5.73076923076923)
        self.assertEqual(a.state.queues,b.state.queues)
        self.assertEqual(a.state.queues,self.desk().state.queues)

    def test_stale_proposal_refreshes_instead_of_committing(self):
        a=self.desk(); b=self.desk()
        old=self.proposal(b,'ORD-063')
        a.confirm(self.proposal(a))
        with self.assertRaises(ProposalChanged) as error:
            b.confirm(old)
        fresh=error.exception.decision
        self.assertNotEqual(old.state_version,fresh.state_version)
        self.assertEqual(len(a.audit.load_all()),1)
        b.confirm(fresh)
        self.assertEqual(len(a.audit.load_all()),2)

    def test_duplicate_concurrent_confirm_only_allocates_once(self):
        a=self.desk(); b=self.desk()
        da=self.proposal(a); db=self.proposal(b)
        def commit(pair):
            try: pair[0].confirm(pair[1]); return True
            except ValueError: return False
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(commit,[(a,da),(b,db)]))
        self.assertEqual(sum(results),1)
        self.assertEqual(len(a.audit.load_all()),1)
        record=a.audit.load_all()[0]
        self.assertAlmostEqual(a.state.queues[record.workshop_id],record.queue_after)

    def test_transaction_failure_rolls_back_queue(self):
        desk=self.desk(); d=self.proposal(desk); before=desk.state.queues
        with desk.audit.connection() as db:
            db.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON allocations BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(sqlite3.IntegrityError): desk.confirm(d)
        self.assertEqual(desk.state.queues,before)
        self.assertEqual(desk.audit.load_all(),[])

    def test_audit_contains_reason_and_constraints(self):
        desk=self.desk(); desk.agent.excluded=['W2']
        record=desk.confirm(self.proposal(desk))
        self.assertEqual(record.evidence['excluded'],['W2'])
        self.assertEqual(record.evidence['constraints'][0]['originator'],'Ravi')
        self.assertIn('reason',record.evidence)
        self.assertIn('tool_log',record.evidence)

    def test_legacy_jsonl_is_imported_once(self):
        desk=self.desk(); record=desk.confirm(self.proposal(desk))
        legacy=Path(self.temp.name)/'legacy.jsonl'
        legacy.write_text(json.dumps(to_dict(record))+'\n')
        imported=AuditLog(legacy,initial_queues=desk.state._queues)
        self.assertEqual(len(imported.load_all()),1)
        imported.reset()
        self.assertEqual(AuditLog(legacy).load_all(),[])

    def test_reset_invalidates_versions_but_does_not_reset_budget(self):
        desk=self.desk(); d=self.proposal(desk)
        budget=CallBudget(desk.audit.path)
        budget.reserve(limits=[(3600,1)])
        desk.audit.reset()
        with self.assertRaises(BudgetExceeded): budget.reserve(limits=[(3600,1)])
        with self.assertRaises(ProposalChanged): desk.confirm(d)

    def test_rate_limit_survives_new_budget_instances(self):
        path=Path(self.temp.name)/'budget.sqlite3'
        CallBudget(path).reserve(limits=[(3600,1)],now=10000)
        with self.assertRaises(BudgetExceeded):
            CallBudget(path).reserve(limits=[(3600,1)],now=10001)
        CallBudget(path).reserve(limits=[(3600,1)],now=13601)

    def test_concurrent_budget_reservations_are_atomic(self):
        path=Path(self.temp.name)/'budget.sqlite3'; CallBudget(path)
        def reserve(_):
            try: CallBudget(path).reserve(limits=[(3600,1)]); return True
            except BudgetExceeded: return False
        with ThreadPoolExecutor(4) as pool:
            self.assertEqual(sum(pool.map(reserve,range(4))),1)

    def test_deepseek_never_falls_back_to_openai_key(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'fake-openai'},clear=True):
            with self.assertRaises(RuntimeError):
                load_api_key('deepseek',env_path=Path(self.temp.name)/'missing')

    def test_missing_results_count_as_failures(self):
        labels=json.loads(Path('data/labels_inbox.json').read_text(encoding="utf-8"))
        label=labels[0]; path=Path(self.temp.name)/'run.jsonl'
        path.write_text(json.dumps({'request_id':label['request_id'],'behaviour':label['behaviour'],
                                   'explanation':'','tool_log':[]})+'\n')
        _,summary=score_run(results_path=path)
        self.assertEqual(summary['errors'],29)
        self.assertEqual(summary['completion_rate'],.033)
        self.assertEqual(summary['behaviour_accuracy'],.033)
        self.assertEqual(summary['successful_behaviour_accuracy'],1.)
        self.assertEqual(summary['faithfulness'],.033)

    def test_api_error_message_does_not_expose_provider_error(self):
        def fail(**kwargs): raise RuntimeError('Invalid API key: sk-test-secret-fragment')
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fail)))
        agent=DispatchAgent(client=client)
        with self.assertRaises(RuntimeError) as error: agent._completion(model='fake',messages=[])
        self.assertNotIn('sk-test',str(error.exception))

    def test_oversized_input_does_not_call_api(self):
        client=SimpleNamespace()
        agent=DispatchAgent(client=client)
        with self.assertRaises(ValueError): agent.chat('a'*8001)
        self.assertEqual(agent.history,[])

    def test_foreign_workshop_and_unversioned_proposal_refused(self):
        desk=self.desk(); d=self.proposal(desk)
        with self.assertRaises(ValueError): desk.confirm(replace(d,state_version=None))
        with self.assertRaises(ValueError): desk.confirm(replace(d,candidates=[]))
        self.assertEqual(desk.audit.load_all(),[])

    def test_streamlit_replace_item_invalidates_old_card(self):
        # Exercise the UI state helper without importing/starting Streamlit.
        source=Path('app/streamlit_app.py').read_text(encoding="utf-8")
        node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='_replace_item')
        old=Decision('',Behaviour.ALLOCATE)
        state={'decisions':[{'decision':old}]}
        namespace={'st':SimpleNamespace(session_state=state),'Decision':Decision,'Behaviour':Behaviour}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'ui-helper','exec'),namespace)
        namespace['_replace_item'](old,None,'Updating')
        self.assertEqual(state['decisions'][0]['decision'].candidates,[])
        fresh=Decision('',Behaviour.ALLOCATE)
        namespace['_replace_item'](old,fresh,'Done')
        self.assertIs(state['decisions'][0]['decision'],fresh)

    def test_exclusions_survive_followup_when_model_forgets_them(self):
        desk=self.desk(); desk.agent.excluded=['W2']
        d=self.proposal(desk)
        desk.agent.excluded=[]
        desk.agent.intent=FollowupIntent('question')
        updated,_,_=desk.follow_up('why this workshop?',d)
        self.assertEqual(updated.excluded,['W2'])
        self.assertEqual(updated.parsed.constraints[0].originator,'Ravi')

    def test_followup_does_not_silently_switch_to_another_order(self):
        desk=self.desk(); d=self.proposal(desk)
        desk.agent.next_order='ORD-063'
        desk.agent.intent=FollowupIntent('question')
        updated,record,reply=desk.follow_up('why this workshop?',d)
        self.assertIsNone(updated); self.assertIsNone(record)
        self.assertIn('another order',reply)

    def test_explicit_removal_of_exclusion_updates_proposal(self):
        desk=self.desk(); desk.agent.excluded=['W2']
        d=self.proposal(desk)
        # Even if the rank call repeats the old exclusion, the explicit edit wins.
        desk.agent.intent=FollowupIntent('modify',changes=('excluded',),exclude_remove=('W2',))
        updated,_,_=desk.follow_up('allow W2 again',d)
        self.assertEqual(updated.excluded,[])
        self.assertIn('W2',[c.workshop_id for c in updated.candidates])

    def test_old_telegram_option_cannot_act_on_new_proposal(self):
        session=ChatSession(self.desk)
        session.handle('allocate ORD-041')
        token=session.options_token
        session.handle('cancel')
        reply,_=session.handle_option(token,0)
        self.assertIn('expired',reply)
        self.assertIsNone(session.pending)
        self.assertEqual(session.desk.audit.load_all(),[])

    def test_hybrid_still_matches_simulator_for_all_orders(self):
        from datetime import date
        from desk.allocator import CHAT_TODAY,rank_candidates
        from desk.register import OrderStore,WorkshopStore
        from harness.algorithm2 import make_hybrid_allocator
        store=WorkshopStore(); allocator=make_hybrid_allocator(.5)
        queues={wid:w.queue0 for wid,w in store.workshops.items()}
        for rec in OrderStore().orders:
            batch={'category':rec['category'],'pieces':int(rec['pieces']),
                   'sent_date':CHAT_TODAY,'due_date':date.fromisoformat(rec['due_date'])}
            with self.subTest(order=rec['order_id']):
                self.assertEqual(rank_candidates(rec['order_id'],objective='hybrid')['chosen'],
                                 allocator(batch,store.workshops,queues))

    def test_classifier_uses_api_for_natural_language_without_write_tools(self):
        desk=self.desk(); d=self.proposal(desk)
        calls=[]
        def classify(**kwargs):
            calls.append(kwargs)
            payload={'intent':'confirm','order_id':'ORD-041','workshop_id':'W2','changes':[]}
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=classify)))
        desk.agent=DispatchAgent(client=client)
        _,record,_=desk.follow_up("I'm happy to go with SteadyHands",d)
        self.assertEqual(record.workshop_id,'W2')
        self.assertEqual(len(calls),1)
        self.assertNotIn('tools',calls[0])

    def ui_helpers(self,desk,decision,prompt):
        from contextlib import nullcontext
        class State(dict):
            __getattr__=dict.__getitem__
            __setattr__=dict.__setitem__
        class Rerun(Exception): pass
        state=State(decisions=[{'decision':decision}])
        def rerun(): raise Rerun()
        ui=SimpleNamespace(session_state=state,rerun=rerun,
            container=lambda **kw:nullcontext(),chat_message=lambda *a,**kw:nullcontext(),
            form=lambda **kw:nullcontext(),spinner=lambda *a,**kw:nullcontext(),
            text_input=lambda *a,**kw:prompt,form_submit_button=lambda *a,**kw:True,
            markdown=lambda *a,**kw:None,text=lambda *a,**kw:None,
            warning=lambda *a,**kw:None,error=lambda *a,**kw:None)
        names={'_replace_item','render_item_chat','_budget_ok','_norm_msg','_log_exchange',
               '_auth_token','_valid_auth_token'}
        nodes=[n for n in ast.parse(Path('app/streamlit_app.py').read_text(encoding="utf-8")).body
               if isinstance(n,ast.FunctionDef) and n.name in names]
        import hmac,hashlib
        namespace={'st':ui,'Decision':Decision,'Behaviour':Behaviour,'AUTH_DAYS':30,
                   'hmac':hmac,'hashlib':hashlib,'BudgetExceeded':BudgetExceeded}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'ui-events','exec'),namespace)
        return namespace,state,Rerun

    def test_streamlit_followup_replaces_card_and_buttons(self):
        desk=self.desk(); d=self.proposal(desk)
        desk.agent.intent=FollowupIntent('modify',changes=('excluded',),exclude_add=('W2',))
        namespace,state,Rerun=self.ui_helpers(desk,d,'exclude W2')
        with self.assertRaises(Rerun): namespace['render_item_chat'](d,desk)
        fresh=state['decisions'][0]['decision']
        self.assertNotEqual(fresh.decision_id,d.decision_id)
        self.assertNotIn('W2',[c.workshop_id for c in fresh.candidates])
        self.assertEqual(desk.audit.load_all(),[])

    def test_streamlit_failed_followup_does_not_leave_confirm_buttons(self):
        desk=self.desk(); d=self.proposal(desk)
        namespace,state,_=self.ui_helpers(desk,d,'change it')
        with patch.object(desk,'follow_up',side_effect=RuntimeError('failure')):
            namespace['render_item_chat'](d,desk)
        self.assertEqual(state['decisions'][0]['decision'].candidates,[])

    def test_streamlit_plain_yes_commits_without_classifier(self):
        desk=self.desk(); d=self.proposal(desk)
        namespace,state,Rerun=self.ui_helpers(desk,d,'好的')
        with patch.object(desk.agent,'classify_followup',side_effect=AssertionError('no API needed')):
            with self.assertRaises(Rerun): namespace['render_item_chat'](d,desk)
        self.assertIn(f'committed-{id(d)}',state)
        self.assertEqual(len(desk.audit.load_all()),1)

    def test_cookie_expiry_and_password_change_are_verified_server_side(self):
        desk=self.desk(); d=self.proposal(desk)
        ns,_,_=self.ui_helpers(desk,d,'')
        with patch('time.time',return_value=10000):
            token=ns['_auth_token']('test-password')
            self.assertTrue(ns['_valid_auth_token'](token,'test-password'))
            self.assertFalse(ns['_valid_auth_token'](token,'changed-password'))
            self.assertFalse(ns['_valid_auth_token'](token+'x','test-password'))
        with patch('time.time',return_value=10000+31*86400):
            self.assertFalse(ns['_valid_auth_token'](token,'test-password'))


    # ---------------- follow-up display and order ids ----------------

    def test_followup_history_records_user_words_not_internal_context(self):
        desk=self.desk(); desk.agent.excluded=['W2']
        d=self.proposal(desk)
        desk.agent.intent=FollowupIntent('question')
        desk.follow_up('why this workshop?',d)
        users=[m['content'] for m in desk.agent.history if m['role']=='user']
        self.assertEqual(users[-1],'why this workshop?')
        self.assertFalse(any('Current proposal' in u for u in users))

    def test_order_id_spellings_resolve_without_guessing(self):
        for raw,want in [('ORD-63','ORD-063'),('ord 63','ORD-063'),('ORD-0063','ORD-063'),
                         ('ORD63','ORD-063'),(' ORD-063 ','ORD-063'),('ORD-999','ORD-999'),
                         ('W2','W2'),(None,None)]:
            with self.subTest(raw=raw):
                self.assertEqual(canonical_order_id(raw),want)
        found=dispatch_tool('lookup_order',{'order_id':'ORD-63'})
        self.assertEqual(found['status'],'found')
        self.assertEqual(found['matches'][0]['order_id'],'ORD-063')
        self.assertEqual(dispatch_tool('lookup_order',{'order_id':'ORD-999'})['status'],'not_found')

    def test_agent_logs_canonical_order_id_for_tool_calls(self):
        class Msg(SimpleNamespace):
            def model_dump(self): return {'role':'assistant','content':self.content}
        call=SimpleNamespace(id='c1',function=SimpleNamespace(
            name='lookup_order',arguments=json.dumps({'order_id':'ORD-63'})))
        replies=iter([Msg(content=None,tool_calls=[call]),Msg(content='Found it.',tool_calls=None)])
        create=lambda **kw:SimpleNamespace(choices=[SimpleNamespace(message=next(replies))])
        agent=DispatchAgent(client=SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create))))
        agent.chat('ORD-63, sent')
        self.assertEqual(agent.tool_log[0]['arguments']['order_id'],'ORD-063')
        self.assertEqual(agent.tool_log[0]['result']['status'],'found')

    def test_followup_on_unknown_order_starts_fresh(self):
        desk=self.desk()
        d=Decision('',Behaviour.NO_DATA,parsed=ParsedRequest(order_id='ORD-999'),
                   explanation='No such order.')
        desk.agent.classify_followup=lambda *a: self.fail('no proposal to classify against')
        desk.agent.next_order='ORD-041'
        updated,record,_=desk.follow_up('what orders do you have?',d)
        self.assertIsNone(record)
        self.assertEqual(updated.parsed.order_id,'ORD-041')
        users=[m['content'] for m in desk.agent.history if m['role']=='user']
        self.assertEqual(users,['what orders do you have?'])

if __name__=='__main__':
    unittest.main()

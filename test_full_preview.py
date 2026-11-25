import copy
import unittest
from unittest.mock import patch
import bot as b
from test_bot import A, B, C, movie

class FullPreviewTests(unittest.TestCase):
    def setUp(self):
        self.state=b.new_state();self.state['tests']=['123'];self.state['subscribers']['456']=[]
        self.cinemas={c['id']:c for c in (A,B,C)}
        self.current={c['id']:{'film':movie(fmt=c['name'])} for c in (A,B,C)}

    @patch.object(b,'get_page',return_value='')
    def test_all_three_only_requester_and_no_history_mutation(self,_):
        seen=copy.deepcopy(self.state['cinemas'])
        with patch.object(b,'deliver') as deliver:
            b.deliver_tests('token',self.state,self.cinemas,self.current)
        self.assertEqual(deliver.call_count,3)
        self.assertEqual({call.args[1] for call in deliver.call_args_list},{'123'})
        for call,c in zip(deliver.call_args_list,(A,B,C)):
            card=call.args[2]
            self.assertIn(c['name'],card['caption']);self.assertIn(c['id'],card['url']);self.assertIn('TEST',card['caption'])
        self.assertEqual(self.state['tests'],[])
        self.assertEqual(self.state['cinemas'],seen)
        self.assertEqual(self.state['subscribers']['456'],[])

    @patch.object(b,'get_page',return_value='')
    def test_failed_branch_retries_without_resending_other_two(self,_):
        first={k:v for k,v in self.current.items() if k!=B['id']}
        with patch.object(b,'deliver') as deliver:
            b.deliver_tests('token',self.state,self.cinemas,first)
            self.assertEqual(deliver.call_count,2)
            b.deliver_tests('token',self.state,self.cinemas,self.current)
            self.assertEqual(deliver.call_count,3)
            self.assertIn(B['id'],deliver.call_args.args[2]['url'])
        self.assertEqual(self.state['tests'],[])

    @patch.object(b,'get_page',return_value='')
    def test_delivery_failure_keeps_only_failed_card_pending(self,_):
        with patch.object(b,'deliver',side_effect=[None,RuntimeError(),None]):
            b.deliver_tests('token',self.state,self.cinemas,self.current)
        self.assertEqual(self.state['test_progress']['123']['remaining'],[B['id']])

    def test_discovery_failure_does_not_finish_partial_preview(self):
        self.state['discovery_error']=True
        with patch.object(b,'deliver') as deliver:
            b.deliver_tests('token',self.state,self.cinemas,self.current)
        deliver.assert_not_called();self.assertEqual(self.state['tests'],['123'])

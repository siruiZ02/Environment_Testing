import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiment import ROOT, command, stability, verify

class ExperimentTests(unittest.TestCase):
    def test_negative_positive_and_wrong_state(self):
        for site in ['github','amazon']:
            spec=json.loads((ROOT/'inputs'/f'{site}.json').read_text())
            state=json.loads(json.dumps(spec['seed']))
            self.assertFalse(verify(spec,state))
            key='issues' if site=='github' else 'cart'
            state[key]=[spec['expected']]
            self.assertTrue(verify(spec,state))
            state[key].append(spec['expected'])
            self.assertFalse(verify(spec,state))
    def test_stability_is_not_success(self):
        self.assertTrue(stability([False]*5)['stable'])
        self.assertFalse(stability([False]*5)['all_passed'])
        self.assertFalse(stability([True,False])['stable'])
        self.assertFalse(stability([])['stable'])
    def test_subprocess_failure_log_and_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); log=p/'failure.log'
            r=command([sys.executable,'-c','import sys; print("failure-marker"); sys.exit(7)'],p,log)
            self.assertEqual(r['returncode'],7)
            self.assertIn('failure-marker',log.read_text())
            r=command([sys.executable,'-c','import time; time.sleep(10)'],p,log,timeout=.05)
            self.assertEqual(r['error'],'timeout')
            r=command(['nonexistent-verienv-test-executable'],p,log)
            self.assertEqual(r['status'],'blocked')

if __name__=='__main__': unittest.main()

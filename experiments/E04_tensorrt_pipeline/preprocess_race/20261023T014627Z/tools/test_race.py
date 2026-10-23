import unittest
from race import choose_candidate


class DecisionTests(unittest.TestCase):
    def rows(self,candidate=8.5,baseline_end=10.0,one_bad=False):
        rows=[]
        for block in range(4):
            for position,name,value in [(0,'R0',10.0),(1,'canvas',candidate),
                                        (2,'reuse',9.8),(3,'R0',baseline_end)]:
                if one_bad and block==3 and name=='canvas':value=12.0
                for i in range(3):rows.append(dict(block=block,position=position,variant=name,input_ready_ms=value))
        return rows
    def test_winner_requires_at_least_one_ms_for_stereo_pair(self):
        summaries,paired,winner=choose_candidate(self.rows(),['canvas','reuse'])
        self.assertEqual(winner,'canvas')
        self.assertEqual(paired['canvas']['mean_saved_ms'],1.5)
        self.assertFalse(paired['reuse']['eligible'])
        self.assertEqual(summaries['canvas']['n'],12)
    def test_below_one_ms_stops_even_if_fastest(self):
        _,_,winner=choose_candidate(self.rows(candidate=9.2),['canvas','reuse'])
        self.assertIsNone(winner)
    def test_one_block_regression_rejects_aggregate_speedup(self):
        _,paired,winner=choose_candidate(self.rows(candidate=7.0,one_bad=True),['canvas','reuse'])
        self.assertGreater(paired['canvas']['mean_saved_ms'],1)
        self.assertIsNone(winner)
    def test_baseline_drift_larger_than_saved_cost_stops(self):
        _,paired,winner=choose_candidate(self.rows(candidate=9.0,baseline_end=12.0),['canvas'])
        self.assertEqual(paired['canvas']['mean_saved_ms'],2)
        self.assertFalse(paired['canvas']['eligible'])
        self.assertIsNone(winner)
    def test_mean_improves_but_tail_regresses_is_not_selected(self):
        rows=self.rows(candidate=6.0)
        for block in range(4):
            candidate=[r for r in rows if r['block']==block and r['variant']=='canvas']
            candidate[-1]['input_ready_ms']=14.0
        _,paired,winner=choose_candidate(rows,['canvas'])
        self.assertGreater(paired['canvas']['mean_saved_ms'],1)
        self.assertFalse(paired['canvas']['tail_nonregression'])
        self.assertIsNone(winner)


if __name__=='__main__':unittest.main()

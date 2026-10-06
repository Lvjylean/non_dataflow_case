import unittest
from plan_sll import parse


def table(demands):
    text='Number SLLs per Column: 1440\nEstimated SLL Demand Per Column: \n'
    for lo,hi in [(2,3),(1,2),(0,1)]:
        data=demands if lo==0 else [0]*16
        pairs=' '.join(f'{d} ({round(d/1440*100)}%)' for d in data)
        text+=f'  SLR [{lo}-{hi}] {pairs} Demand: {sum(data)} Available: 23040 Utilization(%): 1.00\n'
    return text


class TestSll(unittest.TestCase):
    def test_integer_threshold(self):
        rows=parse(table([1151,1152,1153,2994]+[0]*12))
        hot=[r['column'] for r in rows if r['demand']*5>=r['capacity']*4]
        self.assertEqual(hot,[1,2,3])
        self.assertGreater(rows[-13]['utilization'],1)

    def test_reject_incomplete_or_multiple(self):
        t=table([0]*16)
        for bad in [t+t,t.replace('1440','1000',1),t.replace('Available: 23040','Available: 23041',1),t[:t.rfind('  SLR')]]:
            with self.assertRaises(ValueError): parse(bad)


if __name__=='__main__': unittest.main()

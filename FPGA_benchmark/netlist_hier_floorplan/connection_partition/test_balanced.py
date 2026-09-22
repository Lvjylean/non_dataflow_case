"""Independent checks for grain-invariant span costs and admission constraints."""
import itertools
import unittest

import numpy as np

from balanced_physical import NetModel, expected_ranges, admissible
from balanced_regions import options_for, local_fractions
from static_regions import RESOURCES


def fixture():
    device={f'X{x}Y0':dict(x=x,y=0,slr=x,resources={r:(10 if r in ('LUT','FF') else 0) for r in RESOURCES})
            for x in (0,1)}
    region=dict(crs=list(device),bounds=[0,0,1,0],area=2,slrs=[0,1],
                capacity={r:sum(d['resources'][r] for d in device.values()) for r in RESOURCES})
    data=dict(atom_resources=[dict(LUT=1),dict(LUT=1)],edges=[((0,1),4)])
    return data,device,region


class BalancedTests(unittest.TestCase):
    def test_expected_span_matches_enumeration(self):
        for n in range(2,6):
            locations=list(itertools.product((0,1),repeat=n))
            exact=sum(max(p)-min(p) for p in locations)/len(locations)
            calculated=expected_ranges(np.array([[n]]),np.array([[.5]]))[0,0]
            self.assertAlmostEqual(exact,calculated)

    def test_internal_net_has_physical_cost(self):
        d,device,r=fixture();m=NetModel(d,[0,0],1,device)
        c=m.components({'P00':r})
        self.assertAlmostEqual(c['x_span'],.5)
        self.assertAlmostEqual(c['slr_span'],.5)
        self.assertAlmostEqual(c['internal_span_cost'],2.5)

    def test_relabeling_does_not_change_physical_cost(self):
        d,device,r=fixture()
        a=NetModel(d,[0,0],1,device).components({'P00':r})
        b=NetModel(d,[0,1],2,device).components({'P00':r,'P01':r})
        self.assertAlmostEqual(a['physical_cost'],b['physical_cost'])

    def test_one_point_has_zero_span(self):
        self.assertEqual(expected_ranges(np.array([[2,1]]),np.array([[0,1],[0,1]])).sum(),0)

    def test_hypernet_counts_each_distinct_atom(self):
        d,device,r=fixture();d['atom_resources'].append(dict(LUT=1));d['edges']=[((0,1,2),4)]
        m=NetModel(d,[0,0,0],1,device)
        self.assertAlmostEqual(m.components({'P00':r})['x_span'],.75)

    def test_mixed_resource_distributions(self):
        d,device,r=fixture();d['atom_resources'][1]={'FF':1}
        device['X0Y0']['resources']['LUT']=20;device['X1Y0']['resources']['LUT']=0
        device['X0Y0']['resources']['FF']=0;device['X1Y0']['resources']['FF']=20
        m=NetModel(d,[0,0],1,device)
        self.assertAlmostEqual(m.components({'P00':r})['x_span'],1)

    def test_local_constraint_not_hidden_by_global_total(self):
        cfg=dict(global_added_km1_fraction_of_all_net_weight=.025,local_split_fraction_of_incident_net_weight=.1)
        self.assertFalse(admissible(dict(global_added_fraction=.001,maximum_local_split_fraction=.2),cfg))

    def test_multi_slr_options_not_removed(self):
        d,device,r=fixture();a=dict(r,area=1,slrs=[0]);b=dict(r,area=2,slrs=[0,1])
        options,_=options_for(dict(LUT=1),[a,b],dict(region_max_area_factor=1.5,region_max_area_extra_crs=4))
        self.assertEqual(len(options),2)

    def test_local_net_cuts_count_multiple_child_boundaries(self):
        data=dict(edges=[((0,1,2),4),((0,3),4)])
        x=local_fractions(data,[0,0,0,1],[0,1,2,3])
        self.assertEqual(x['P00']['local_km1'],2)
        self.assertEqual(x['P00']['incident_weight'],2)


if __name__=='__main__':unittest.main()

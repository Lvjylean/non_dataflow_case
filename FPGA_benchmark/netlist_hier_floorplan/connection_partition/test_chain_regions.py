"""Independent feasibility, cost-equivalence and immutable-owner checks."""
from collections import Counter
import copy
import itertools
import unittest

import numpy as np

from chain_regions import (BranchCost, chain_nodes, directed_edges, layouts, legal,
                           plan, physical_groups, assignment)
from chain_guidance import soft_regions
from directed_model import DirectedModel
from edge_padding import region_from_crs
from static_regions import RESOURCES


def fixture():
    device = {f'X{x}Y0':dict(x=x,y=0,slr=0,resources={r:10 for r in RESOURCES}) for x in range(4)}
    parent = region_from_crs(device,device)
    nodes = dict(S00=dict(parent='S00',resources=Counter(LUT=12),cells=12,chain=None),
                 J0000=dict(parent='S00',resources=Counter(LUT=8),cells=8,chain='first'),
                 J0001=dict(parent='S00',resources=Counter(LUT=8),cells=8,chain='second'))
    edges = {}
    for n in ['J0000','J0001']:
        w=np.zeros((9,9));w[0,0]=100;edges[n,n]=w
    directed=dict(resource_limits={r:.7 for r in RESOURCES},directed_weight=1.,
                  slr_distance_weight=8.,branch_square_weight=32.)
    cfg=dict(min_parent_crs=4,min_parent_chains=2,target_child_crs=2,min_child_crs=2,
             max_children=2,max_layouts=4,mip_seconds_per_layout=5,threads=1,seed=0)
    return device,parent,nodes,edges,directed,cfg


def exhaustive(nodes,chains,options,chosen,device,limits,costs,cfg):
    feasible=[]
    for ks in itertools.product(range(len(options)),repeat=len(chains)):
        trial=dict(chosen);trial.update({n:options[k] for n,k in zip(chains,ks)})
        if legal(nodes,trial,device,limits):
            feasible.append((sum(costs[n,k] for n,k in zip(chains,ks)),ks))
    if not feasible:return None,dict(status='infeasible')
    _,ks=min(feasible)
    return dict(zip(chains,ks)),dict(status='exhaustive')


class ChainRegionsTests(unittest.TestCase):
    def test_simultaneous_moves_fit_while_individual_moves_do_not(self):
        d,p,n,e,c,cfg=fixture();chosen={a:p for a in n}
        half=layouts(p,d,cfg)[0]['regions']
        one=dict(chosen,J0000=half[0])
        self.assertFalse(legal(n,one,d,c['resource_limits']))
        both=dict(one,J0001=half[1])
        self.assertTrue(legal(n,both,d,c['resource_limits']))
        selected,info=plan(n,e,{'S00':p},d,c,cfg,solver=exhaustive)
        self.assertEqual(info['decisions'][0]['guided_chains'],2)
        self.assertLess(info['guided_directed_cost'],info['baseline_directed_cost'])
        self.assertEqual(n['S00']['resources']['LUT'],12)

    def test_invalid_solver_proposal_cannot_bypass_capacity(self):
        d,p,n,e,c,cfg=fixture()
        def invalid(*args):return {'J0000':1,'J0001':1},dict(status='mock')
        chosen,info=plan(n,e,{'S00':p},d,c,cfg,solver=invalid)
        self.assertEqual(info['decisions'][0]['status'],'parent_fallback')
        self.assertTrue(all(r==p for r in chosen.values()))

    def test_directed_cost_matches_existing_formula_and_is_label_invariant(self):
        d,p,n,e,c,cfg=fixture()
        d['X3Y0']['slr']=2
        a=region_from_crs(['X0Y0','X1Y0'],d);b=region_from_crs(['X3Y0'],d)
        w=np.zeros((9,9));w[0,1]=7.25;w[3,2]=4
        edges={('a','b'):w,('a','a'):w*.5}
        data=dict(module_count=2,pairs=[dict(source=0,sink=10,weight=7.25,pins=8),
            dict(source=3,sink=11,weight=4,pins=4),dict(source=0,sink=1,weight=3.625,pins=4),
            dict(source=3,sink=2,weight=2,pins=2)],coverage={'same_atom_pins':0},families={})
        expected=DirectedModel(data,d,c).components({'S00':a,'S01':b})
        scorer=BranchCost(d,c)
        self.assertAlmostEqual(scorer.total(edges,{'a':a,'b':b}),
                               expected['directed_term']+expected['branch_square_term'])
        self.assertGreater(expected['branch_square_term'],0)
        self.assertAlmostEqual(scorer.total({('a','b'):w}, {'a':p,'b':p}),
                               scorer.total({('a','a'):w}, {'a':p}))

    def test_zero_capacity_tiles_cannot_host_memory(self):
        d,p,n,e,c,cfg=fixture()
        d['X0Y0']['resources']['URAM']=0;d['X1Y0']['resources']['URAM']=0
        n['J0000']['resources']['URAM']=1
        zero=region_from_crs(['X0Y0','X1Y0'],d)
        chosen={a:region_from_crs(d,d) for a in n};chosen['J0000']=zero
        self.assertFalse(legal(n,chosen,d,c['resource_limits']))

    def test_child_candidates_stay_in_parent_and_one_die(self):
        d,p,n,e,c,cfg=fixture();d['X2Y0']['slr']=1;d['X3Y0']['slr']=1
        for item in layouts(p,d,dict(cfg,min_child_crs=1,max_children=4)):
            seen=[]
            for r in item['regions']:
                self.assertEqual(len(r['slrs']),1);self.assertLess(r['area'],p['area']);seen+=r['crs']
            self.assertEqual(sorted(seen),sorted(p['crs']))

    def test_tight_parent_retains_coarse_candidates_before_area_budget(self):
        d={f'X{x}Y{y}':dict(x=x,y=y,slr=0,resources={r:10 for r in RESOURCES})
           for x in range(8) for y in range(4)}
        cfg=dict(max_children=8,min_child_crs=2,target_child_crs=8,max_layouts=2)
        result=layouts(region_from_crs(d,d),d,cfg)
        self.assertEqual({p['name'] for p in result},{'grid1x2','grid2x1'})

    def test_physical_groups_preserve_logical_owners_and_complete_operators(self):
        d,p,n,e,c,cfg=fixture()
        data=dict(atoms=[[a] for a in range(28)],atom_resources=[dict(LUT=1) for _ in range(28)])
        joint=[dict(hierarchy='first',atoms=list(range(12,20)),resources={'LUT':8}),
               dict(hierarchy='second',atoms=list(range(20,28)),resources={'LUT':8})]
        labels=[0]*28
        nodes,owner=chain_nodes(data,labels,['S00'],joint,joint)
        chosen,info=plan(nodes,e,{'S00':p},d,c,cfg,solver=exhaustive)
        result=physical_groups(nodes,owner,chosen,{'S00':p},data,labels,['S00'],joint)
        self.assertEqual(len(result['modules']),3)
        self.assertEqual(sum(m['LUT'] for m in result['modules']),28)
        self.assertEqual(sum(m['cells'] for m in result['modules']),28)
        self.assertEqual(set(result['parent_of'].values()),{'S00'})
        self.assertEqual(result['integrity']['split_units'],0)
        self.assertEqual(labels,[0]*28)
        bad=copy.deepcopy(joint);bad[1]['atoms'][0]=12
        with self.assertRaises(ValueError):chain_nodes(data,labels,['S00'],bad,joint)

    def test_sink_multiplicity_unknown_sources_and_internal_nets_retained(self):
        data=dict(atoms=[[0],[1]],atom_of=[0,1],atom_resources=[dict(LUT=1),dict(FF=1)],
            nets=[('n',0,[1,1,0,'PORT'],4),('p','PORT',[1],4)])
        edges,coverage=directed_edges(data,['J0','J0'])
        self.assertEqual(edges['J0','J0'][0,1],2)
        self.assertEqual(coverage['same_atom_pins'],1)
        self.assertEqual(coverage['unlocated_source_pins'],1)
        self.assertEqual(coverage['unlocated_sink_pins'],1)

    def test_soft_geometry_does_not_credit_capacity_or_expand_into_other_child(self):
        d,p,n,e,c,cfg=fixture();halves=layouts(p,d,cfg)[0]['regions']
        physical=dict(modules=[dict(module_id='S00',LUT=12),dict(module_id='S00G00',LUT=8)],
                      regions={'S00':p,'S00G00':halves[0]},parent_of={'S00':'S00','S00G00':'S00'})
        soft,_=soft_regions(physical,{'S00':p},d)
        self.assertEqual(set(soft['S00G00']['crs']),set(halves[0]['crs']))
        self.assertNotIn('capacity',soft['S00G00'])

    def test_native_assignment_when_solver_is_available(self):
        try:import gurobipy
        except ImportError:self.skipTest('Gurobi is tested on the experiment server')
        d,p,n,e,c,cfg=fixture();options=[p,*layouts(p,d,cfg)[0]['regions']]
        cost=BranchCost(d,c);chosen={a:p for a in n};chains=['J0000','J0001']
        unary=cost.unaries(chains,options,e,chosen)
        selected,_=assignment(n,chains,options,chosen,d,c['resource_limits'],unary,cfg)
        self.assertNotEqual(selected[chains[0]],selected[chains[1]])
        self.assertTrue(all(selected[n]>0 for n in chains))


if __name__=='__main__':unittest.main()

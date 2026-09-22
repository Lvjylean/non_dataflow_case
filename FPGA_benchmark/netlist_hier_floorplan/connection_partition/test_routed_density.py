"""Checks that fitted distributions remain valid inputs to resource and J models."""
import unittest

import numpy as np

from balanced_physical import cdf_table
from directed_model import DirectedModel
from routed_density import fit_profile, resource_probabilities, region_cache_key
from static_regions import RESOURCES, overlap_audit


class RoutedDensityTests(unittest.TestCase):
    def setUp(self):
        self.device = {f'X{x}Y0': dict(x=x,y=0,slr=0,
            resources={r:(0 if r=='URAM' and x==1 else 100) for r in RESOURCES}) for x in range(3)}
        self.region = dict(bounds=[0,0,2,0],crs=list(self.device),
                           capacity={r:sum(d['resources'][r] for d in self.device.values()) for r in RESOURCES})

    def test_fallback_is_capacity_prior(self):
        self.assertEqual(resource_probabilities(self.region,self.device,'URAM'),
                         {'X0Y0':.5,'X1Y0':0.,'X2Y0':.5})

    def test_mass_zero_sites_and_overlap_consistency(self):
        profile=fit_profile({'URAM':{'X0Y0':10,'X2Y0':90}},self.region,self.device)
        region=dict(self.region,density_profile=profile)
        p=resource_probabilities(region,self.device,'URAM')
        self.assertAlmostEqual(sum(p.values()),1)
        self.assertEqual(p['X1Y0'],0)
        self.assertGreater(p['X2Y0'],p['X0Y0'])
        module=dict.fromkeys(RESOURCES,0);module.update(module_id='S00',URAM=100)
        audit=overlap_audit([module],{'S00':region},self.device)
        self.assertAlmostEqual(sum(v['utilization'].get('URAM',0)*self.device[v['cr']]['resources']['URAM'] for v in audit['contributions']),100)

    def test_constant_macro_density_does_not_invent_peak(self):
        profile=fit_profile({'URAM':{'X0Y0':100,'X2Y0':100}},self.region,self.device)
        region=dict(self.region,density_profile=profile)
        self.assertEqual(resource_probabilities(region,self.device,'URAM'),
                         resource_probabilities(self.region,self.device,'URAM'))

    def test_cdf_and_cache_distinguish_modules_at_same_geometry(self):
        left=fit_profile({'LUT':{'X0Y0':90,'X1Y0':50,'X2Y0':10}},self.region,self.device)
        right=fit_profile({'LUT':{'X0Y0':10,'X1Y0':50,'X2Y0':90}},self.region,self.device)
        a=dict(self.region,density_profile=left);b=dict(self.region,density_profile=right)
        self.assertNotEqual(region_cache_key(a),region_cache_key(b))
        model=DirectedModel(dict(module_count=1,pairs=[]),self.device,{})
        ca=model.profile(a)[0];cb=model.profile(b)[0]
        self.assertGreater(ca[0,0],cb[0,0])
        for region in [a,b]:
            p=resource_probabilities(region,self.device,'LUT')
            self.assertAlmostEqual(cdf_table(region,self.device)[0,1],p['X0Y0']+p['X1Y0'])

    def test_translation_preserves_relative_shape(self):
        profile=fit_profile({'LUT':{'X0Y0':90,'X1Y0':50,'X2Y0':10}},self.region,self.device)
        shifted={f'X{x+4}Y4':dict(x=x+4,y=4,slr=1,resources=self.device[f'X{x}Y0']['resources']) for x in range(3)}
        region=dict(bounds=[4,4,6,4],crs=list(shifted),density_profile=profile)
        a=resource_probabilities(dict(self.region,density_profile=profile),self.device,'LUT')
        b=resource_probabilities(region,shifted,'LUT')
        np.testing.assert_allclose(list(a.values()),list(b.values()))


if __name__=='__main__':unittest.main()

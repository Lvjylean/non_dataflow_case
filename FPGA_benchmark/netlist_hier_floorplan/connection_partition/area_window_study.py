"""Local fixed-membership area-window comparison using exact cached costs.

No remote jobs, MIP solver, netlist extraction, or physical implementation.
"""
import copy
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from directed_search import Search,emit
from static_regions import LIMITS,overlap_audit


def load(p):return json.loads(p.read_text())
def dump(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


class SingleDieSearch(Search):
    def __init__(self,run):
        super().__init__(run)
        self.netmodel._cache={}
        for mid,rs in self.options.items():
            self.options[mid]=[r for r in rs if len(r['slrs'])==1]
            self.stats[mid].update(retained_rectangles=len(self.options[mid]),maximum_slrs=1,
                search_window='single SLR only; area <= factor*minimum area + extra CRs')

    def legal(self,chosen):
        return all(len(r['slrs'])==1 for r in chosen.values()) and super().legal(chosen)


def setup(root,reference,cache,source):
    root.mkdir(exist_ok=False);(root/'input').mkdir()
    shutil.copytree(source,root/'source',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(reference/'selected_core/export',root/'input/export')
    shutil.copy2(reference/'input/cr.tsv',root/'input/cr.tsv')
    shutil.copy2(reference/'input/original_regions.json',root/'input/original_regions.json')
    for name in ['directed.json','binding.json']:shutil.copy2(reference/name,root/name)
    previous=load(reference/'binding.json')
    assert sha(cache) in [v for k,v in previous['immutable_files'].items() if k.endswith('netmodel.pkl')]
    shutil.copy2(cache,root/'netmodel.pkl')
    snapshot=[p for p in (root/'input').rglob('*') if p.is_file()]+[root/'directed.json',root/'netmodel.pkl']
    dump(root/'local_binding.json',dict(reference=str(reference),cache_source=str(cache),
        source_sha256={str(p.relative_to(root)):sha(p) for p in snapshot},
        original_dcp=previous['input_dcp'],original_dcp_sha256=previous['input_sha256'],
        dcp_accessed=False,remote_accessed=False,scope='Local static area sensitivity only.'))


def run_variant(root,name,factor,extra,starts):
    variant=root/name;variant.mkdir();shutil.copytree(root/'source',variant/'source')
    shutil.copytree(root/'input',variant/'input')
    for n in ['netmodel.pkl','directed.json','binding.json']:shutil.copy2(root/n,variant/n)
    cfg=load(root/'input/export/static_regions.json')['configuration']
    cfg.update(region_max_area_factor=factor,region_max_area_extra_crs=extra,
        region_max_slrs=1,local_rounds=5,local_seeds=[0,17,31],
        notes='Local exact-cost coordinate search and joint swaps; single-SLR rectangles. No new MIP, per-module die preference, or physical implementation.')
    dump(variant/'source/directed_config.json',cfg)
    dump(variant/'source/manifest.json',{p.name:sha(p) for p in (variant/'source').iterdir() if p.is_file() and p.name!='manifest.json'})
    search=SingleDieSearch(variant);started=time.perf_counter()
    reference=search.old['regions']
    current=search.record('baseline_current',reference)
    original=search.record('baseline_original',search.original['regions'])
    # Same J and weights, down to floating-point tolerance, before any search.
    assert abs(current['components']['J']-search.old['objective'])<1e-6
    seeds=[];seen=set()
    def seed(tag,chosen):
        key=tuple(tuple(chosen[m]['bounds']) for m in sorted(chosen))
        if key in seen or not search.legal(chosen):return
        seen.add(key);seeds.append((tag,copy.deepcopy(chosen)))
    for tag,chosen in starts:seed(tag,chosen)
    for i,(tag,chosen) in enumerate(seeds):
        seedno=[0,17,31][i%3]
        emit(dict(stage='start_local',variant=name,tag=tag,seed=seedno,options={m:len(o) for m,o in search.options.items()}))
        chosen,history=search.refine(chosen,seedno)
        search.record('local_'+str(i),chosen,dict(start=tag,seed=seedno,history=history))
    diagnostics={}
    if extra==32:
        whole={mid:search.lookup[(0,4*r['slrs'][0],7,4*r['slrs'][0]+3)] for mid,r in reference.items()}
        assert search.legal(whole)
        trial=search.record('all_whole_die_reference_assignments',whole)
        diagnostics['all_whole_die_J']=trial['components']['J']
        chosen,history=search.refine(whole,31)
        search.record('refined_whole_die',chosen,dict(start='all_whole_die_reference_assignments',seed=31,history=history))
        s01=dict(reference,S01=whole['S01'])
        diagnostics['S01_whole_die_others_fixed_legal']=search.legal(s01)
        if not diagnostics['S01_whole_die_others_fixed_legal']:
            diagnostics['S01_whole_die_others_fixed_violations']=overlap_audit(search.modules,s01,search.device)['violations']
    # Generic tie rule preserves absolute die labels where objective translations tie.
    def movement(p):return sum(abs(p['regions'][m]['center'][a]-reference[m]['center'][a]) for m in reference for a in range(2))
    minimum=min(p['components']['J'] for p in search.trials)
    best=min([p for p in search.trials if p['components']['J']<=minimum+1e-6],key=lambda p:(movement(p),p['tag']))
    result=dict(best,configuration=cfg,limits=LIMITS,candidate_stats=search.stats,
        total_module_crs=sum(r['area'] for r in best['regions'].values()),maximum_slrs_per_unit=1,
        objective=best['components']['J'],normalized=False,runtime_seconds=time.perf_counter()-started,
        search_certificate='Best recorded exact-J feasible candidate from bounded local searches and pair swaps; no MIP or global optimality proof.',
        timing_validation='Not run.',physical_model='Unchanged capacity-weighted static expectation on core rectangles.',diagnostics=diagnostics)
    dump(variant/'solution.json',result);dump(variant/'comparison.json',search.trials)
    shutil.copytree(variant/'input/export',variant/'export');dump(variant/'export/static_regions.json',result)
    emit(dict(stage='variant_complete',variant=name,J=result['objective'],areas={m:r['area'] for m,r in result['regions'].items()},seconds=result['runtime_seconds']))
    return result


def main(root,reference,cache,source):
    setup(root,reference,cache,source)
    starts=[('current',load(reference/'selected_core/solution.json')['regions'])]
    for n in ['mip_0','mip_17']:
        starts.append((n,load(reference/f'weight_8/candidates/{n}.json')['regions']))
    # Matching starts and refinement settings isolate the changed area cap.
    a=run_variant(root,'control',1.5,4,starts)
    b=run_variant(root,'area32',0,32,starts+[('control_best',a['regions'])])
    old=load(reference/'selected_core/solution.json')
    assert b['objective']<=old['objective']+1e-6
    dump(root/'comparison.json',dict(reference_J=old['objective'],control_J=a['objective'],area32_J=b['objective'],
        area32_change_vs_reference=b['objective']/old['objective']-1,area32_change_vs_control=b['objective']/a['objective']-1,
        module_comparison={m:dict(old=old['regions'][m],control=a['regions'][m],area32=b['regions'][m]) for m in old['regions']},
        solver='Existing exact-cost local refinement; no local MIP package available; no remote access.',
        search_limits='5 sweeps/start, full single-module rectangle scans + pair swaps; 32CR variant additionally starts from whole-die regions.'))
    emit(dict(stage='complete',reference_J=old['objective'],control_J=a['objective'],area32_J=b['objective']))


if __name__=='__main__':main(*(Path(p).resolve() for p in sys.argv[1:]))

"""Plot static candidate regions and resource overlap, never actual placement."""
import argparse
import json
from pathlib import Path

from static_regions import load_device


def main(run,candidate):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.patches import Rectangle
    device=load_device(run/'cr.tsv')
    baseline=json.loads((run/'candidates/baseline/static_coupled_regions.json').read_text())
    selected=json.loads((run/'candidates'/candidate/'static_coupled_regions.json').read_text())
    selected_summary=json.loads((run/'candidates'/candidate/'summary.json').read_text())
    mapping={m['module_id']:f'N{i:02d}' for i,m in enumerate(selected_summary['modules'])}
    xs=[d['x'] for d in device.values()];ys=[d['y'] for d in device.values()]
    width=max(xs)+1;height=max(ys)+1
    fig,axes=plt.subplots(2,2,figsize=(13,13),constrained_layout=True)
    slrs=sorted({d['slr'] for d in device.values()})
    def grid(ax):
        ax.set_xlim(-.5,width-.5);ax.set_ylim(-.5,height-.5);ax.set_aspect('equal')
        ax.set_xticks(range(width));ax.set_yticks(range(0,height,2))
        ax.set_xticks(np.arange(-.5,width,1),minor=True)
        ax.set_yticks(np.arange(-.5,height,1),minor=True)
        ax.grid(which='minor',color='#d1d5db',linewidth=.4)
        ax.tick_params(which='minor',length=0);ax.set_xlabel('Clock-region X');ax.set_ylabel('Clock-region Y')
        for slr in slrs:
            rows=[d['y'] for d in device.values() if d['slr']==slr]
            ax.axhline(min(rows)-.5,color='#475569',linewidth=1)
            ax.text(width-.4,(min(rows)+max(rows))/2,f'SLR{slr}',fontsize=9,va='center',clip_on=False)
    colors=plt.get_cmap('tab10')
    for ax,solution,title,rename in [(axes[0,0],baseline,'Baseline: five planning units',{}),
                                     (axes[0,1],selected,'Candidate: shared allowed regions',mapping)]:
        grid(ax);ax.set_title(title,pad=12)
        for i,(mid,region) in enumerate(solution['regions'].items()):
            x0,y0,x1,y1=region['bounds'];color=colors(i)
            ax.add_patch(Rectangle((x0-.5,y0-.5),x1-x0+1,y1-y0+1,
                facecolor=(*color[:3],.055),edgecolor=color,linewidth=2))
            ax.text(x0-.35,y0-.2+.35*(i%3),rename.get(mid,mid),color=color,
                    fontsize=9,fontweight='bold',bbox=dict(facecolor='white',alpha=.85,edgecolor='none',pad=.5))
        audit=solution['overlap']
        ax.text(.5,-.13,f"Used CRs: {audit['occupied_crs']} | Shared CRs: {audit['overlapping_crs']}",
                ha='center',transform=ax.transAxes,fontsize=10)
    for ax,resource in [(axes[1,0],'LUT'),(axes[1,1],'URAM')]:
        array=np.full((height,width),np.nan)
        for c,d in device.items():
            if d['resources'][resource]:array[d['y'],d['x']]=0
        for entry in selected['overlap']['contributions']:
            d=device[entry['cr']]
            if d['resources'][resource]:array[d['y'],d['x']]=entry['utilization'].get(resource,0)
        heat=ax.imshow(array,origin='lower',vmin=0,vmax=1,cmap='YlGnBu')
        grid(ax);ax.set_title(f'Candidate: estimated {resource} utilization',pad=12)
        fig.colorbar(heat,ax=ax,fraction=.045,pad=.12,format=matplotlib.ticker.PercentFormatter(xmax=1))
    fig.suptitle('Static resource-region comparison\nCapacity estimates; no placement or routing was run',fontsize=15)
    out=run/'figures';out.mkdir(exist_ok=True)
    fig.savefig(out/'static_comparison.png',dpi=160)
    plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('candidate')
    a=p.parse_args();main(a.run,a.candidate)

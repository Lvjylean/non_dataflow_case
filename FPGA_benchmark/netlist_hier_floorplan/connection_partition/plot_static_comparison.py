"""Plot static candidate regions and resource overlap, never actual placement."""
import argparse
import json
from pathlib import Path

from static_regions import load_device


def main(run,candidate,output_dir=None,baseline_name='baseline',result_file='static_coupled_regions.json',id_prefix='N'):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.patches import Patch, Rectangle
    device=load_device(run/'cr.tsv')
    baseline=json.loads((run/'candidates'/baseline_name/result_file).read_text())
    selected=json.loads((run/'candidates'/candidate/result_file).read_text())
    selected_summary=json.loads((run/'candidates'/candidate/'summary.json').read_text())
    mapping={m['module_id']:f'{id_prefix}{i:02d}' for i,m in enumerate(selected_summary['modules'])}
    xs=[d['x'] for d in device.values()];ys=[d['y'] for d in device.values()]
    width=max(xs)+1;height=max(ys)+1
    # Zero usage is a separate state, not the pale end of a continuous ramp.
    upper_bounds=np.array([.01,.05,.10,.20,.40,.60,.80,1.0,np.inf])
    band_labels=['>0–1%','>1–5%','>5–10%','>10–20%','>20–40%',
                 '>40–60%','>60–80%','>80–100%','>100%']
    band_colors=['#b1dff0','#79c9e4','#42b0d2','#188daf','#116b99',
                 '#21518a','#30366f','#171c49','#b91c1c']
    resource_cmap=ListedColormap(band_colors)
    resource_cmap.set_bad((1,1,1,0))
    resource_norm=BoundaryNorm(np.arange(-.5,len(band_colors)+.5),len(band_colors))
    def usage_legend(figure):
        figure.legend(handles=[
            Patch(facecolor='white',edgecolor='#94a3b8',label='0%: capacity available, unused'),
            Patch(facecolor='#e5e7eb',edgecolor='#9ca3af',hatch='///',
                  label='No capacity for this resource')],
            loc='outside lower center',ncol=2,fontsize=10,frameon=False)
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
    colors=plt.get_cmap('tab20' if len(selected['regions'])>10 else 'tab10')
    for ax,solution,title,rename in [(axes[0,0],baseline,'Baseline: five planning units',{}),
                                     (axes[0,1],selected,'Candidate: shared allowed regions',mapping)]:
        grid(ax);ax.set_title(title,pad=12)
        for i,(mid,region) in enumerate(solution['regions'].items()):
            x0,y0,x1,y1=region['bounds'];color=colors(i)
            ax.add_patch(Rectangle((x0-.5,y0-.5),x1-x0+1,y1-y0+1,
                facecolor=(*color[:3],.055),edgecolor=color,linewidth=2))
            ax.text(x0-.35,y0-.2+.35*(i%3),rename.get(mid,mid),color='#1f2937',
                    fontsize=9,fontweight='bold',bbox=dict(facecolor='white',alpha=.85,edgecolor='none',pad=.5))
        audit=solution['overlap']
        ax.text(.5,-.13,f"Used CRs: {audit['occupied_crs']} | Shared CRs: {audit['overlapping_crs']}",
                ha='center',transform=ax.transAxes,fontsize=10)
    def resource_map(ax,resource,figure):
        array=np.full((height,width),np.nan)
        for c,d in device.items():
            if d['resources'][resource]:array[d['y'],d['x']]=0
        for entry in selected['overlap']['contributions']:
            d=device[entry['cr']]
            if d['resources'][resource]:array[d['y'],d['x']]=entry['utilization'].get(resource,0)
        assert np.all(array[np.isfinite(array)]>=0),'Negative resource utilization'
        occupied=np.isfinite(array)&(array>0)
        bands=np.searchsorted(upper_bounds,array,side='left')
        display=np.ma.array(bands,mask=~occupied)
        heat=ax.imshow(display,origin='lower',cmap=resource_cmap,norm=resource_norm,
                       interpolation='nearest')
        for y in range(height):
            for x in range(width):
                value=array[y,x]
                if not np.isfinite(value):
                    ax.add_patch(Rectangle((x-.5,y-.5),1,1,facecolor='#e5e7eb',
                        edgecolor='#9ca3af',hatch='///',linewidth=0,zorder=2))
                    continue
                if value==0:
                    label='0%';color='#64748b'
                else:
                    percentage=value*100
                    label=('<0.1%' if percentage<.1 else f'{percentage:.1f}%' if percentage<1
                           else f'{percentage:.0f}%')
                    color='white' if bands[y,x]>=3 else '#102d46'
                ax.text(x,y,label,ha='center',va='center',fontsize=7.2,color=color,zorder=4)
        grid(ax);ax.set_title(f'Candidate: estimated {resource} utilization',pad=12)
        bar=figure.colorbar(heat,ax=ax,fraction=.045,pad=.12,ticks=range(len(band_labels)))
        bar.ax.set_yticklabels(band_labels,fontsize=8)
        bar.set_label('Utilization bands (not a linear scale)',fontsize=9)
    for ax,resource in [(axes[1,0],'LUT'),(axes[1,1],'URAM')]:
        resource_map(ax,resource,fig)
    fig.suptitle('Static resource-region comparison\nCapacity estimates; no placement or routing was run',fontsize=15)
    usage_legend(fig)
    out=output_dir or run/'figures';out.mkdir(parents=True,exist_ok=True)
    fig.savefig(out/'static_comparison.png',dpi=160)
    plt.close(fig)
    fig,axes=plt.subplots(1,3,figsize=(17,9),constrained_layout=True)
    for ax,resource in zip(axes,('LUT','URAM','DSP')):
        resource_map(ax,resource,fig)
    fig.suptitle('Candidate resource utilization: LUT / URAM / DSP\n'
                 'Static estimates; every positive value is colored and labeled',fontsize=15)
    usage_legend(fig)
    fig.savefig(out/'static_resource_utilization.png',dpi=160)
    plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('candidate')
    p.add_argument('--output-dir',type=Path)
    p.add_argument('--baseline-name',default='baseline')
    p.add_argument('--result-file',default='static_coupled_regions.json')
    p.add_argument('--id-prefix',default='N')
    a=p.parse_args();main(a.run,a.candidate,a.output_dir,a.baseline_name,a.result_file,a.id_prefix)

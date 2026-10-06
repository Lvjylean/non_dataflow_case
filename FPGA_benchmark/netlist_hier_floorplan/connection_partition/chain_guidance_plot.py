"""Compact figures distinguish logical parents, physical groups and estimates."""
import json
from pathlib import Path


def plots(out, parent, device):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from matplotlib.cm import ScalarMappable
    summary = json.loads((out/'summary.json').read_text())
    figdir = out/'figures'; figdir.mkdir(exist_ok=True)
    core = summary['core_plan']; module = {m['module_id']: m for m in summary['modules']}
    xmax = max(d['x'] for d in device.values()); ymax = max(d['y'] for d in device.values())
    colors = plt.get_cmap('tab20')
    occupied = set().union(*(set(r['crs']) for r in core['regions'].values()))
    padding = set().union(*(set(r['padding_crs']) for r in summary['soft_regions'].values())) - occupied

    def grid(ax):
        ax.set_xlim(-.5, xmax+.5); ax.set_ylim(-.5, ymax+.5)
        ax.set_xticks(range(xmax+1)); ax.set_yticks(range(ymax+1)); ax.set_aspect('equal')
        for d in device.values():
            ax.add_patch(Rectangle((d['x']-.5, d['y']-.5), 1, 1, fill=False,
                                   edgecolor='#d1d5db', linewidth=.45, zorder=4))
        for slr in sorted({d['slr'] for d in device.values()}):
            ys = [d['y'] for d in device.values() if d['slr'] == slr]
            ax.axhline(min(ys)-.5, color='#475569', linewidth=1.3)
            ax.text(xmax+.65, (min(ys)+max(ys))/2, f'SLR{slr}', fontsize=9)
        ax.set_xlabel('Clock-region X'); ax.set_ylabel('Clock-region Y')

    fig, axes = plt.subplots(1, 2, figsize=(12, 11))
    for panel, (ax, regions) in enumerate(zip(axes, [parent['regions'], core['regions']])):
        labels_by_bounds = {}
        # Draw full-parent remainder first, then child cores on top.
        ordered = sorted(regions, key=lambda m: (m != summary['parent_of'].get(m, m), m))
        for i, mid in enumerate(ordered):
            region = regions[mid]; color = colors(i % 20)
            child = mid != summary['parent_of'].get(mid, mid)
            for c in region['crs']:
                d = device[c]
                ax.add_patch(Rectangle((d['x']-.5, d['y']-.5), 1, 1, facecolor=color,
                                      alpha=.48 if child else .16, edgecolor='none'))
            x0, y0, x1, y1 = region['bounds']
            remainder = panel and any(p == mid and n != mid for n, p in summary['parent_of'].items())
            ax.add_patch(Rectangle((x0-.46, y0-.46), x1-x0+.92, y1-y0+.92,
                                  fill=False, edgecolor=color, linewidth=1.8,
                                  linestyle='--' if remainder else '-', zorder=5))
            label = mid
            if panel and child:
                label += f"\n{module[mid]['chain_count']} chains"
            if remainder:
                ax.text(x0-.4, y1+.23, mid+' remainder: parent envelope', fontsize=8,
                        color='#334155', bbox=dict(facecolor='white', alpha=.85, edgecolor='none'), zorder=8)
            else:
                labels_by_bounds.setdefault(tuple(region['bounds']), []).append(label)
        for (x0,y0,x1,y1), labels in labels_by_bounds.items():
            ax.text((x0+x1)/2, (y0+y1)/2, '\n'.join(labels), fontsize=8 if len(labels)>1 else 9,
                    ha='center', va='center', bbox=dict(facecolor='white', alpha=.9, edgecolor='none', pad=1), zorder=8)
        if panel:
            for c in padding:
                d = device[c]
                ax.add_patch(Rectangle((d['x']-.5,d['y']-.5),1,1,facecolor='#fff7ed',
                                      edgecolor='#d97706',hatch='xx',linewidth=.5,zorder=3))
                ax.text(d['x'],d['y'],'EXT',ha='center',va='center',fontsize=7,
                        color='#92400e',bbox=dict(facecolor='#fff7ed',edgecolor='none',pad=0),zorder=8)
        grid(ax)
    titles=summary.get('comparison_titles', [f"A: {summary['logical_module_count']} logical modules / parent cores",
                                            f"B: {summary['physical_group_count']} physical groups + soft extensions"])
    axes[0].set_title(titles[0]);axes[1].set_title(titles[1])
    fig.suptitle(summary.get('figure_title','Intact joint chains receive distinct subregions; logical module owners stay unchanged'), fontsize=13)
    fig.text(.5, .02, 'EXT = soft allowance only, no resource credit. Actual distribution and congestion remain unmeasured.', ha='center', fontsize=10)
    fig.tight_layout(rect=(0,.035,1,.96)); fig.savefig(figdir/'chain_regions.png', dpi=170); plt.close(fig)

    fig, axes = plt.subplots(1,3,figsize=(16,11))
    usage = {c['cr']: c['utilization'] for c in core['overlap']['contributions']}
    bounds = [0,.01,.05,.1,.2,.4,.6,.8,1,1.00001]
    cmap = ListedColormap(['#b1dff0','#79c9e4','#42b0d2','#188daf','#116b99',
                           '#21518a','#30366f','#171c49','#b91c1c'])
    norm = BoundaryNorm(bounds, cmap.N)
    for ax, resource in zip(axes,['LUT','URAM','DSP']):
        for c,d in device.items():
            value = usage.get(c,{}).get(resource,0); available = d['resources'][resource] > 0
            color = '#e5e7eb' if not available else 'white' if value == 0 else cmap(norm(value))
            ax.add_patch(Rectangle((d['x']-.5,d['y']-.5),1,1,facecolor=color,
                                  hatch='///' if not available else None, edgecolor='#cbd5e1', linewidth=.3))
            if available:
                label = '0%' if value == 0 else '<1%' if value < .01 else f'{value:.0%}'
                ax.text(d['x'],d['y'],label,ha='center',va='center',fontsize=7,
                        color='white' if value>.1 else '#334155')
            if c in padding:
                ax.add_patch(Rectangle((d['x']-.5,d['y']-.5),1,1,facecolor='none',
                                      edgecolor='#d97706',hatch='xx',linewidth=.3,zorder=5))
                ax.text(d['x'],d['y'],'EXT',ha='center',va='center',fontsize=7,color='#92400e',
                        bbox=dict(facecolor='#fff7ed',edgecolor='none',pad=0),zorder=6)
        grid(ax); ax.set_title(resource+' | combined core estimate')
    fig.suptitle('Resource accounting: chain groups + remainder, without counting parents twice',fontsize=14)
    fig.text(.5,.025,'White = 0% allocation; hatch = no resource. Static estimate, not routed occupancy. Soft extensions add no capacity.',ha='center',fontsize=10)
    fig.tight_layout(rect=(0,.045,1,.96)); fig.savefig(figdir/'core_resources.png',dpi=170); plt.close(fig)

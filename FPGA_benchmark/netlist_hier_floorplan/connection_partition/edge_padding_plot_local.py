"""Portable PNG rendering for core estimates and selected soft-only CRs.

Used when matplotlib is unavailable; reads the same explicit core-only schema.
"""
import csv
import colorsys
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

COLORS=['#1f77b4','#aec7e8','#ff7f0e','#ffbb78','#2ca02c','#98df8a',
        '#d62728','#ff9896','#9467bd','#c5b0d5','#8c564b',
        '#e377c2','#7f7f7f','#bcbd22','#17becf','#393b79','#637939','#8c6d31',
        '#843c39','#7b4173','#3182bd','#31a354','#756bb1','#636363']
BANDS=[.01,.05,.1,.2,.4,.6,.8,1,float('inf')]
HEAT=['#b1dff0','#79c9e4','#42b0d2','#188daf','#116b99','#21518a','#30366f','#171c49','#b91c1c']
LABELS=['>0-1%','>1-5%','>5-10%','>10-20%','>20-40%','>40-60%','>60-80%','>80-100%','>100%']


def font(size,bold=False):
    for path in ['/System/Library/Fonts/Supplemental/Arial'+(' Bold' if bold else '')+'.ttf',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans'+('-Bold' if bold else '')+'.ttf']:
        if Path(path).exists():return ImageFont.truetype(path,size)
    return ImageFont.load_default(size=size)


def text(draw,xy,s,size=16,color='#334155',anchor='la',bold=False):
    draw.text(xy,str(s),font=font(size,bold),fill=color,anchor=anchor)


def hatch(draw,box,color,cross=False):
    x0,y0,x1,y1=map(int,box)
    for t in range(0,(x1-x0)+(y1-y0)+1,10):
        a=max(0,t-(y1-y0));b=min(x1-x0,t)
        draw.line((x0+a,y0+t-a,x0+b,y0+t-b),fill=color,width=1)
        if cross:draw.line((x0+a,y1-t+a,x0+b,y1-t+b),fill=color,width=1)


def grid(draw,ox,oy,tile):
    for x in range(9):draw.line((ox+x*tile,oy,ox+x*tile,oy+16*tile),fill='#cbd5e1')
    for y in range(17):draw.line((ox,oy+y*tile,ox+8*tile,oy+y*tile),fill='#cbd5e1')
    for y in [0,4,8,12,16]:draw.line((ox,oy+y*tile,ox+8*tile,oy+y*tile),fill='#334155',width=2)
    for x in range(8):text(draw,(ox+(x+.5)*tile,oy+16*tile+18),x,14,anchor='mm')
    for y in range(16):text(draw,(ox-17,oy+(15.5-y)*tile),y,14,anchor='mm')
    for s in range(4):text(draw,(ox+8*tile+9,oy+(14-4*s)*tile),'SLR'+str(s),14,anchor='lm')
    text(draw,(ox+4*tile,oy+16*tile+45),'Clock-region X',17,anchor='mm')
    text(draw,(ox-25,oy-21),'Y',15,anchor='mm')


def plots(folder):
    load=lambda p:json.loads((folder/p).read_text())
    new=load('solution.json');core=load('input/export/static_regions.json')
    assert new['resource_accounting']['schema']=='core-only-v1'
    assert new['overlap']==core['overlap']
    padding={c for r in new['regions'].values() for c in r['padding_crs']}
    device={}
    with (folder/'input/cr.tsv').open() as f:
        for r in csv.DictReader(f,delimiter='\t'):
            n=int(r['SLICEL'])+int(r['SLICEM'])
            device[r['cr']]=dict(x=int(r['x']),y=int(r['y']),LUT=8*n,URAM=int(r['URAM']),DSP=int(r['DSP']))
    figdir=folder/'figures';figdir.mkdir(exist_ok=True)
    def box(c,ox,oy,t):
        d=device[c];x=ox+d['x']*t;y=oy+(15-d['y'])*t
        return (x,y,x+t,y+t)
    count=len(core['regions'])
    palette=list(COLORS)
    for i in range(len(palette),count):
        rgb=colorsys.hsv_to_rgb((i*.61803398875)%1,.7,.7)
        palette.append('#'+''.join(f'{round(v*255):02x}' for v in rgb))
    legend_rows=(count+5)//6
    image=Image.new('RGB',(1160,max(900,850+29*legend_rows)),'white');draw=ImageDraw.Draw(image)
    for panel,plan in enumerate([core,new]):
        ox=75+panel*570;oy=70;t=42
        title='J-selected core floorplan' if panel==0 else 'Soft Pblock: core + extensions'
        text(draw,(ox-20,25),title,23,bold=True)
        for i,(mid,r) in enumerate(sorted(plan['regions'].items())):
            for c in r['crs']:
                color=tuple(int(palette[i][j:j+2],16) for j in (1,3,5))
                light=tuple(round(.8*255+.2*v) for v in color)
                draw.rectangle(box(c,ox,oy,t),fill=light)
        if panel==1:
            for c in padding:
                b=box(c,ox,oy,t);draw.rectangle(b,fill='#fef3c7');hatch(draw,b,'#b45309',True)
        grid(draw,ox,oy,t);slots={}
        for i,(mid,r) in enumerate(sorted(plan['regions'].items())):
            cells={(device[c]['x'],device[c]['y']) for c in r['crs']}
            for c in r['crs']:
                x,y=device[c]['x'],device[c]['y'];a,b,d,e=box(c,ox,oy,t)
                for dx,dy,coords in [(-1,0,(a,b,a,e)),(1,0,(d,b,d,e)),(0,1,(a,b,d,b)),(0,-1,(a,e,d,e))]:
                    if (x+dx,y+dy) not in cells:draw.line(coords,fill=palette[i],width=3)
            x,y=min(cells,key=lambda xy:(xy[1],xy[0]));slot=slots.get((x,y),0);slots[x,y]=slot+1
            px=ox+x*t+4;py=oy+(16-y)*t-4-slot*19
            draw.rectangle((px-1,py-18,px+39,py+1),fill='white')
            text(draw,(px,py),mid,16,anchor='ld',bold=True)
    for i,mid in enumerate(sorted(core['regions'])):
        x=35+(i%6)*182;y=813+(i//6)*29
        draw.rectangle((x,y,x+17,y+17),fill=palette[i]);text(draw,(x+24,y),mid,16)
    x,y=35,813+29*legend_rows
    draw.rectangle((x,y,x+17,y+17),fill='#fef3c7');hatch(draw,(x,y,x+17,y+17),'#b45309',True)
    text(draw,(x+23,y),'Soft extension',16)
    image.save(figdir/'regions.png')

    image=Image.new('RGB',(1920,1690),'white');draw=ImageDraw.Draw(image)
    text(draw,(960,26),'Resources and J use the core only; EXT marks selected soft geometry',27,anchor='mm',bold=True)
    usage={r['cr']:r['utilization'] for r in core['overlap']['contributions']}
    for row in range(2):
        for col,res in enumerate(['LUT','URAM','DSP']):
            ox=65+col*640;oy=115+row*765;t=39
            title=('Core estimate' if row==0 else 'Same estimate + soft extensions')+' | '+res
            text(draw,(ox-18,oy-47),title,21,bold=True)
            for c,d in device.items():
                b=box(c,ox,oy,t);v=usage.get(c,{}).get(res,0)
                index=next(i for i,threshold in enumerate(BANDS) if v<=threshold)
                draw.rectangle(b,fill='#e5e7eb' if not d[res] else 'white' if v==0 else HEAT[index])
                if not d[res]:hatch(draw,b,'#9ca3af')
                cx=(b[0]+b[2])/2;cy=(b[1]+b[3])/2
                if row==1 and c in padding:
                    if d[res]:draw.rectangle(b,fill='#fef3c7')
                    hatch(draw,b,'#b45309',True)
                    draw.rectangle((cx-15,cy-9,cx+15,cy+9),fill='#fffbeb')
                    text(draw,(cx,cy),'EXT',12,'#92400e',anchor='mm',bold=True)
                elif d[res]:
                    label='0%' if not v else '<0.1%' if v<.001 else f'{v:.1%}' if v<.01 else f'{v:.0%}'
                    text(draw,(cx,cy),label,12,'white' if v and index>=3 else '#334155',anchor='mm')
            grid(draw,ox,oy,t)
            for i,label in enumerate(LABELS):
                x=ox+410;y=oy+80+i*30
                draw.rectangle((x,y,x+18,y+18),fill=HEAT[i]);text(draw,(x+25,y),label,15)
    legend=[('white','0%: available, no core allocation',None),('#e5e7eb','No resource capacity','#9ca3af'),('#fef3c7','EXT: soft range, no resource allocation','#b45309')]
    for i,(fill,label,line) in enumerate(legend):
        x=35+i*635;y=1622;draw.rectangle((x,y,x+21,y+21),fill=fill,outline='#94a3b8')
        if line:hatch(draw,(x,y,x+21,y+21),line,i==2)
        text(draw,(x+30,y+1),label,17)
    text(draw,(960,1663),'Static planning estimates only. No new placement, route, or measured occupancy.',18,anchor='mm')
    image.save(figdir/'estimated_utilization.png')

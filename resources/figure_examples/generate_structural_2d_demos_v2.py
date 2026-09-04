# -*- coding: utf-8 -*-
"""Structural 2-D scientific visualization demos V2.

DEMO ONLY. The fields are deterministic synthetic capability data. Replace
with traceable result-manifest arrays before using any image as evidence.
These demos emphasize topology, fields, geometry and optimization structure,
not ordinary point/line/bar chart variants.
"""
from pathlib import Path
import sys
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.patches import Polygon
from scipy import ndimage
from scipy.spatial import Delaunay, Voronoi

ROOT = Path.cwd()
if not (ROOT / "_utils" / "plot_utils.py").exists():
    raise SystemExit("Run from a Modex workspace containing _utils/plot_utils.py")
sys.path.insert(0, str(ROOT))
from _utils.plot_utils import setup_style, save_fig, PALETTE, COLORS, _lighten
setup_style("auto")

OUT = Path(r"D:\C盘迁移\桌面项目\OH-WorkSpace\modex-figure-system\demos\structural-2d-v2")
OUT.mkdir(parents=True, exist_ok=True)
P = list(PALETTE)
INK = COLORS.get("text", "#333333")
GRID = COLORS.get("grid", "#E0E0E0")
HI = COLORS.get("highlight", P[1])


def cmap(name, colors):
    return LinearSegmentedColormap.from_list(name, colors, N=256)


def finish(fig, name):
    # Use the declared canvas for structural demos. The workspace plot_utils
    # safety hook already handles ordinary margins; tight bounding boxes can
    # explode when a contour-tree panel has long categorical tick labels.
    fig.savefig(OUT / f"{name}.pdf", format="pdf", bbox_inches=None, pad_inches=.08)
    fig.savefig(OUT / f"{name}.png", format="png", dpi=600, bbox_inches=None, pad_inches=.08)
    plt.close(fig)


def clean(ax, grid=False):
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    if grid:
        ax.grid(alpha=.12, color=GRID); ax.set_axisbelow(True)


def demo(ax, text):
    ax.text(.02, .98, "DEMO ONLY · " + text, transform=ax.transAxes, ha="left", va="top", fontsize=7.5, color=INK,
            bbox=dict(facecolor="white", edgecolor="none", alpha=.82, pad=2))


def scalar_field(ny=150, nx=170):
    x=np.linspace(-2.5,2.5,nx); y=np.linspace(-2.1,2.1,ny); X,Y=np.meshgrid(x,y)
    Z=(1.4*np.exp(-((X+1.15)**2+(Y+.42)**2)/.48)
       +1.05*np.exp(-((X-.72)**2+(Y-.58)**2)/.62)
       -.72*np.exp(-((X+.05)**2+(Y-.05)**2)/.75)
       +.12*np.sin(2.5*X)*np.cos(2.0*Y))
    return x,y,X,Y,Z


def gradient_basins():
    x,y,X,Y,Z=scalar_field(160,180); gy,gx=np.gradient(Z,y,x)
    # Discrete gradient-ascent basins: every grid cell repeatedly moves to
    # the highest-valued 8-neighbour until a local maximum is reached.
    basin=np.full(Z.shape,-1,int); peaks=[]
    for iy in range(1,Z.shape[0]-1):
        for ix in range(1,Z.shape[1]-1):
            p=(iy,ix); seen=set()
            while p not in seen:
                seen.add(p); iy0,ix0=p
                if iy0 <= 0 or iy0 >= Z.shape[0]-1 or ix0 <= 0 or ix0 >= Z.shape[1]-1:
                    break
                nb=Z[iy0-1:iy0+2,ix0-1:ix0+2].copy(); nb[1,1]=-np.inf
                q=np.unravel_index(np.argmax(nb),nb.shape); q=(iy0+q[0]-1,ix0+q[1]-1)
                if Z[q] <= Z[p]: break
                p=q
            if p not in peaks: peaks.append(p)
            basin[iy,ix]=peaks.index(p)
    # keep strongest basins and merge tiny labels into nearest strong basin
    counts=np.bincount(basin[basin>=0]); keep=np.argsort(counts)[-4:]
    remap={old:i for i,old in enumerate(keep)}
    for old in range(len(counts)):
        if old not in remap: basin[basin==old]=keep[0]
    for old,new in remap.items(): basin[basin==old]=new
    B=cmap("basins",[_lighten(P[i%len(P)],.58) for i in range(len(keep))])
    fig,ax=plt.subplots(figsize=(7.5,5.1)); ax.contourf(X,Y,basin,levels=np.arange(len(keep)+1)-.5,cmap=B,alpha=.72)
    ax.contour(X,Y,Z,levels=14,colors=INK,linewidths=.35,alpha=.36)
    # Separatrices from label discontinuities
    boundary=np.zeros_like(basin,dtype=bool); boundary[1:,:]|=basin[1:,:]!=basin[:-1,:]; boundary[:,1:]|=basin[:,1:]!=basin[:,:-1]
    ax.contour(X,Y,boundary.astype(float),levels=[.5],colors=[HI],linewidths=1.25)
    peak_xy=[]
    for i in range(len(keep)):
        q=np.argwhere(basin==i); k=q[np.argmax(Z[basin==i])]; peak_xy.append((x[k[1]],y[k[0]],Z[k[0],k[1]]))
    ax.scatter([q[0] for q in peak_xy],[q[1] for q in peak_xy],s=120,c=[HI]*len(peak_xy),marker="*",edgecolor="white",lw=1.0,zorder=5)
    ax.set(xlabel="场域 x",ylabel="场域 y",title="Gradient-ascent basin map：极值分区与分离边界"); clean(ax,False); demo(ax,"分区由离散梯度上升计算；高亮线为 basin separatrix"); finish(fig,"gradient_basin_separatrix_demo")


def persistence_landscape():
    x,y,X,Y,Z=scalar_field(130,150); mx=ndimage.maximum_filter(Z,size=13)==Z; pos=np.argwhere(mx & (Z>.25)); vals=Z[mx & (Z>.25)]
    order=np.argsort(vals)[-9:]; births=np.array([max(0.,vals[i]-.18-.035*i) for i in order]); deaths=np.array([vals[i] for i in order]); t=np.linspace(0,1.5,400)
    tents=[]
    for b,d in zip(births,deaths):
        c=(b+d)/2; h=(d-b)/2; tents.append(np.maximum(0,h-np.abs(t-c)))
    tents=np.array(tents); landscape=np.sort(tents,axis=0)[::-1]
    fig,aa=plt.subplots(1,3,figsize=(10.2,3.8),gridspec_kw={"width_ratios":[1.05,1.05,1.2]})
    for i,(b,d) in enumerate(zip(births,deaths)): aa[0].plot([b,d],[i,i],color=P[i%len(P)],lw=3,solid_capstyle="round")
    aa[0].set(xlabel="标量值",ylabel="特征排序",title="Barcode"); aa[0].set_yticks([]); clean(aa[0],True)
    aa[1].scatter(births,deaths,s=45,c=[P[i%len(P)] for i in range(len(births))],edgecolor="white",lw=.6); aa[1].plot([0,1.5],[0,1.5],ls="--",color=INK,lw=.8); aa[1].set(xlim=(0,1.5),ylim=(0,1.5),xlabel="birth",ylabel="death",title="Persistence diagram"); clean(aa[1],True)
    for k in range(min(4,len(landscape))): aa[2].plot(t,landscape[k],color=P[k],lw=1.8,label=f"λ{k+1}")
    aa[2].set(xlabel="标量值 t",ylabel="landscape λk(t)",title="Persistence landscape"); aa[2].legend(frameon=False,fontsize=8); clean(aa[2],True)
    fig.suptitle("Topological persistence：特征生命周期到函数化摘要",fontsize=11); demo(aa[0],"长度 ∝ persistence；演示特征对"); finish(fig,"persistence_landscape_demo")


def merge_tree():
    x,y,X,Y,Z=scalar_field(120,150); levels=np.linspace(Z.min()+.08,Z.max()-.08,18); comps=[]; centers=[]
    for lv in levels:
        lab,n=ndimage.label(Z>=lv)
        cur=[]
        for k in range(1,n+1):
            q=np.argwhere(lab==k)
            if len(q)>=18: cur.append((q[:,1].mean(),q[:,0].mean(),len(q)))
        comps.append(cur)
    fig,(ax,tr)=plt.subplots(1,2,figsize=(8.8,4.5),gridspec_kw={"width_ratios":[1.3,.9]})
    cf=ax.contourf(X,Y,Z,levels=18,cmap=cmap("field",[_lighten(P[0],.75),P[0],P[1],HI]),alpha=.82); ax.contour(X,Y,Z,levels=levels,colors="white",linewidths=.45,alpha=.7); ax.set(xlabel="x",ylabel="y",title="Scalar field / level sets"); clean(ax,False); fig.colorbar(cf,ax=ax,label="f(x,y)")
    prev=[]; nodes=[]
    for li,cur in enumerate(comps):
        for ci,c in enumerate(cur): nodes.append((li,ci,levels[li],c[2],c[0],c[1]))
        if prev and cur:
            for pi,p in enumerate(prev):
                q=min(cur,key=lambda z:abs(z[0]-p[0]))
                edges=(li-1,pi,levels[li-1],p[2],p[0],p[1],li,cur.index(q),levels[li],q[2],q[0],q[1])
                tr.plot([edges[0],edges[6]],[edges[2],edges[8]],color=P[0],alpha=.35,lw=1)
        prev=cur
    for li,ci,lv,area,cx,cy in nodes: tr.scatter(li,lv,s=15+area/20,color=HI if area<80 else P[1],edgecolor="white",lw=.35)
    tr.set(xlabel="level index",ylabel="f value",title="Merge-tree abstraction"); clean(tr,True); demo(tr,"节点大小 ∝ 连通分支面积；树由等值层连通摘要得到"); finish(fig,"merge_tree_linked_field_demo")


def lic_critical():
    n=190; q=np.linspace(-2.2,2.2,n); X,Y=np.meshgrid(q,q); U=-(Y-.25)+.18*np.sin(2*X); V=(X+.1)+.18*np.cos(2*Y); S=np.hypot(U,V); U/=S; V/=S; rng=np.random.default_rng(2026); noise=rng.random((n,n)); tex=np.zeros_like(noise)
    for i in range(n):
        for j in range(n):
            vals=[]
            for k in range(-12,13):
                ii=int(np.clip(i+k*V[i,j],0,n-1)); jj=int(np.clip(j+k*U[i,j],0,n-1)); vals.append(noise[ii,jj])
            tex[i,j]=np.mean(vals)
    fig,ax=plt.subplots(figsize=(6.4,5.5)); ax.imshow(tex,extent=[q.min(),q.max(),q.min(),q.max()],origin="lower",cmap=cmap("lic",[_lighten(P[0],.88),_lighten(P[0],.35),P[0]]),alpha=.94); ax.streamplot(q,q,U,V,color=HI,density=1.0,linewidth=.32,arrowsize=.35)
    ax.scatter([.1],[.25],s=120,color=HI,marker="o",edgecolor="white",label="中心/旋涡"); ax.scatter([-1.4,1.3],[.2,-.5],s=72,color=P[1],marker="^",edgecolor="white",label="代表源汇"); ax.set(xlabel="状态 x",ylabel="状态 y",title="LIC texture + critical-point topology"); clean(ax,False); ax.legend(frameon=False,loc="upper left"); demo(ax,"纹理沿矢量场积分；临界点由局部场结构标记"); finish(fig,"lic_critical_topology_demo")


def voronoi_dual():
    rng=np.random.default_rng(12); pts=rng.uniform(-1,1,(42,2)); tri=Delaunay(pts); val=.5+.3*np.sin(2*pts[:,0])+.25*np.cos(3*pts[:,1]); vor=Voronoi(pts); fig,ax=plt.subplots(figsize=(7,5.4)); cm=cmap("dual",[_lighten(P[0],.72),P[0],P[1],HI]); norm=Normalize(val.min(),val.max())
    for s in tri.simplices:
        poly=pts[s]; ax.add_patch(Polygon(poly,facecolor=cm(norm(val[s].mean())),edgecolor="white",lw=.7,alpha=.82))
    edges = set()
    for simplex in tri.simplices:
        for ia, ib in ((simplex[0], simplex[1]), (simplex[1], simplex[2]), (simplex[2], simplex[0])):
            edges.add(tuple(sorted((int(ia), int(ib)))))
    for ia, ib in edges:
        ax.plot([pts[ia,0], pts[ib,0]], [pts[ia,1], pts[ib,1]], color=INK, lw=.35, alpha=.42)
    for rv in vor.ridge_vertices:
        if -1 not in rv: ax.plot(vor.vertices[rv,0],vor.vertices[rv,1],color=HI,lw=.55,alpha=.7)
    ax.scatter(pts[:,0],pts[:,1],c=val,cmap=cm,norm=norm,s=25,edgecolor="white",lw=.45,zorder=3); ax.set(xlim=(-1.05,1.05),ylim=(-1.05,1.05),xlabel="空间 x",ylabel="空间 y",title="Voronoi–Delaunay dual scalar field"); ax.set_aspect("equal"); clean(ax,False); fig.colorbar(plt.cm.ScalarMappable(norm=norm,cmap=cm),ax=ax,label="节点/单元标量"); demo(ax,"白线：Delaunay primal；橙线：Voronoi dual"); finish(fig,"voronoi_delaunay_dual_demo")


def ensemble_contours():
    x,y,X,Y,Z=scalar_field(130,150); rng=np.random.default_rng(7); members=[]
    for k in range(24): members.append(Z+.06*rng.normal(size=Z.shape)+.08*np.sin((k+1)*X/5)*np.cos((k+2)*Y/5))
    M=np.array(members); mean=M.mean(0); lo=np.quantile(M,.1,axis=0); hi=np.quantile(M,.9,axis=0); levels=[.25,.55,.85]
    fig,ax=plt.subplots(figsize=(7.4,5.1)); ax.contourf(X,Y,mean,levels=18,cmap=cmap("ens",[_lighten(P[0],.8),P[0],P[1],HI]),alpha=.78); ax.contour(X,Y,lo,levels=levels,colors=[_lighten(P[0],.25)],linewidths=1.0,linestyles="--"); ax.contour(X,Y,mean,levels=levels,colors=[P[0]],linewidths=1.5); ax.contour(X,Y,hi,levels=levels,colors=[HI],linewidths=1.0,linestyles=":"); ax.set(xlabel="状态 x",ylabel="状态 y",title="Ensemble contour envelope：均值等值线与不确定性外壳"); clean(ax,False); demo(ax,"实线：均值；虚线/点线：10%/90% ensemble 等值层"); finish(fig,"ensemble_contour_envelope_demo")


def phase_nullcline():
    # Van der Pol field, with nullclines and trajectories integrated from seeds.
    mu=1.2; x=np.linspace(-2.5,2.5,130); y=np.linspace(-3,3,130); X,Y=np.meshgrid(x,y); U=Y; V=mu*(1-X**2)*Y-X; fig,ax=plt.subplots(figsize=(7.1,5.0)); speed=np.hypot(U,V); ax.streamplot(x,y,U,V,color=speed,density=1.2,cmap=cmap("phase",[_lighten(P[0],.72),P[0],HI]),linewidth=.7,arrowsize=.45)
    ax.plot(x,np.zeros_like(x),color=P[1],lw=1.5,label="dx/dt=0"); ax.plot(x, x/(mu*(1-x**2)+1e-6),color=HI,lw=1.3,alpha=.0) # avoid singular plotting; vertical nullcline shown below
    ax.axvline(0,color=HI,lw=1.2,ls="--",label="dy/dt=0: x=0"); ax.scatter([0],[0],s=105,color=HI,marker="*",edgecolor="white",label="平衡点")
    for x0,y0 in [(-2.0,1.8),(-1.7,-1.2),(1.9,.8),(1.3,-2.0)]:
        xx,yy=x0,y0; path=[]
        for _ in range(850): path.append((xx,yy)); dx=0.012*yy; dy=0.012*(mu*(1-xx*xx)*yy-xx); xx+=dx; yy+=dy
        path=np.array(path); ax.plot(path[:,0],path[:,1],color=INK,lw=.65,alpha=.55)
    ax.set(xlim=(-2.5,2.5),ylim=(-3,3),xlabel="状态 x",ylabel="状态 y",title="Phase portrait + nullclines：动力系统几何结构"); clean(ax,False); ax.legend(frameon=False,loc="upper left"); demo(ax,"背景为速度场；流线与轨迹来自同一动力系统"); finish(fig,"phase_portrait_nullcline_demo")


def dominance_hypervolume():
    rng=np.random.default_rng(3); pts=np.array([[.12,.20],[.18,.34],[.26,.30],[.33,.48],[.42,.43],[.50,.62],[.62,.58],[.73,.76],[.84,.71],[.38,.67],[.58,.78]])
    xx=np.linspace(0,1,140); yy=np.linspace(0,1,120); X,Y=np.meshgrid(xx,yy); dom=np.zeros_like(X)
    for px,py in pts: dom+=(X>=px)&(Y>=py)
    nd=[]
    for i,(px,py) in enumerate(pts):
        if not any(j!=i and q[0]>=px and q[1]>=py and (q[0]>px or q[1]>py) for j,q in enumerate(pts)): nd.append(i)
    fig,ax=plt.subplots(figsize=(7.0,5.0)); ax.contourf(X,Y,dom,levels=np.arange(dom.max()+2)-.5,cmap=cmap("dom",[_lighten(P[0],.85),_lighten(P[0],.45),P[0],HI]),alpha=.72); ax.scatter(pts[:,0],pts[:,1],s=35,color=P[2],edgecolor="white",lw=.5,label="候选解"); ax.plot(pts[nd,0],pts[nd,1],color=HI,lw=2.0,label="Pareto skyline"); ax.scatter(pts[nd,0],pts[nd,1],s=105,color=HI,edgecolor="white",lw=.9); ax.set(xlabel="目标 1（越大越优）",ylabel="目标 2（越大越优）",title="Dominance-count map：支配层级与 Pareto skyline"); clean(ax,False); fig.colorbar(plt.cm.ScalarMappable(norm=Normalize(0,dom.max()),cmap=cmap("dom2",[_lighten(P[0],.85),P[0],HI])),ax=ax,label="被支配候选数量"); ax.legend(frameon=False,loc="upper left"); demo(ax,"背景：每个位置支配的候选数；高亮线：非支配 skyline"); finish(fig,"dominance_hypervolume_map_demo")


def main():
    funcs=[gradient_basins,persistence_landscape,merge_tree,lic_critical,voronoi_dual,ensemble_contours,phase_nullcline,dominance_hypervolume]
    for fn in funcs: fn()
    print(f"generated {len(funcs)} structural 2-D demos in {OUT}")

if __name__ == "__main__": main()

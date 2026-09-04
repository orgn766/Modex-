# -*- coding: utf-8 -*-
"""Advanced 2-D scientific visualization demos for Modex.

DEMO ONLY: deterministic synthetic fields are used to demonstrate visual
structures. Replace them with traceable result-manifest data before paper use.
The script deliberately favors field/topology/geometry views over ordinary
bar, line and scatter charts.
"""
from pathlib import Path
import sys
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection, LineCollection
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Polygon, FancyArrowPatch
from scipy import ndimage
from scipy.spatial import Delaunay

ROOT = Path.cwd()
if not (ROOT / "_utils" / "plot_utils.py").exists():
    raise SystemExit("Run from a Modex workspace containing _utils/plot_utils.py")
sys.path.insert(0, str(ROOT))
from _utils.plot_utils import setup_style, save_fig, PALETTE, COLORS, _lighten

# auto reads the frozen user palette/layout markers from CLAUDE.md.
setup_style("auto")
OUT = ROOT / "figures" / "_advanced_2d_demos"
OUT.mkdir(parents=True, exist_ok=True)
P = list(PALETTE)
INK = COLORS.get("text", "#333333")
GRID = COLORS.get("grid", "#E0E0E0")
HI = COLORS.get("highlight", P[1])


def cmap_user(name, colors):
    return LinearSegmentedColormap.from_list(name, colors, N=256)


def clean(ax, grid=True):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if grid:
        ax.grid(axis="y", alpha=.12, color=GRID)
        ax.set_axisbelow(True)


def label(ax, text):
    ax.text(.02, .98, f"DEMO · {text}", transform=ax.transAxes, ha="left", va="top",
            fontsize=8, color=INK, bbox=dict(facecolor="white", edgecolor="none", alpha=.84, pad=2))


def save(fig, name):
    fig.savefig(OUT / f"{name}.pdf", format="pdf", bbox_inches="tight", pad_inches=.08)
    fig.savefig(OUT / f"{name}.png", format="png", dpi=600, bbox_inches="tight", pad_inches=.08)
    plt.close(fig)


def field():
    x = np.linspace(-2.4, 2.4, 100); y = np.linspace(-2.0, 2.0, 88)
    X, Y = np.meshgrid(x, y)
    Z = (1.2*np.exp(-((X+1.1)**2+(Y+.45)**2)/.45)
         + .92*np.exp(-((X-.7)**2+(Y-.55)**2)/.58)
         - .62*np.exp(-((X+.05)**2+(Y-.05)**2)/.75)
         + .08*np.sin(3*X)*np.cos(2*Y))
    return x, y, X, Y, Z


def carpet_plot():
    x, y, X, Y, Z = field()
    # Warp a structured grid in the normal direction by scalar response Z.
    xs = np.linspace(-2.25, 2.25, 34); ys = np.linspace(-1.85, 1.85, 28)
    XX, YY = np.meshgrid(xs, ys); ZZ = 0.45*np.exp(-((XX+1.0)**2+(YY+.4)**2)/.6) - .28*np.exp(-((XX-.1)**2+(YY-.1)**2)/.8)
    polys=[]; vals=[]
    for i in range(len(ys)-1):
        for j in range(len(xs)-1):
            polys.append([(XX[i,j],YY[i,j]+ZZ[i,j]),(XX[i,j+1],YY[i,j+1]+ZZ[i,j+1]),(XX[i+1,j+1],YY[i+1,j+1]+ZZ[i+1,j+1]),(XX[i+1,j],YY[i+1,j]+ZZ[i+1,j])])
            vals.append(.5*(ZZ[i,j]+ZZ[i+1,j+1]))
    fig, ax = plt.subplots(figsize=(7.2,4.8)); pc=PolyCollection(polys,array=np.asarray(vals),cmap=cmap_user("carpet",[_lighten(P[0],.82),P[0],HI]),edgecolors=_lighten(P[0],.45),linewidths=.28,alpha=.88); ax.add_collection(pc)
    ax.contour(X,Y,Z,levels=8,colors=INK,linewidths=.35,alpha=.35); ax.set(xlim=(-2.4,2.4),ylim=(-2.15,2.25),xlabel="参数 x",ylabel="参数 y + 响应变形",title="Carpet plot：二维网格变形与第二标量编码"); clean(ax,False); fig.colorbar(pc,ax=ax,label="网格变形量"); label(ax,"高度/变形：响应值；颜色：同一响应的局部幅度"); save(fig,"carpet_plot_demo")


def lic_like():
    # Deterministic line-integral-convolution-like texture for a 2-D vector field.
    n=180; q=np.linspace(-2.2,2.2,n); X,Y=np.meshgrid(q,q); U=-(Y-.3)+.24*np.sin(2*X); V=(X+.2)+.18*np.cos(2*Y); speed=np.hypot(U,V); U/=speed; V/=speed
    noise=np.random.default_rng(2026).random((n,n)); tex=np.zeros_like(noise); steps=10
    for i in range(n):
        for j in range(n):
            vals=[]
            for s in range(-steps,steps+1):
                ii=int(np.clip(i+s*V[i,j]*1.1,0,n-1)); jj=int(np.clip(j+s*U[i,j]*1.1,0,n-1)); vals.append(noise[ii,jj])
            tex[i,j]=np.mean(vals)
    fig,ax=plt.subplots(figsize=(6.2,5.5)); ax.imshow(tex,extent=[q.min(),q.max(),q.min(),q.max()],origin="lower",cmap=cmap_user("lic",[_lighten(P[0],.88),_lighten(P[0],.35),P[0]]),alpha=.92); ax.streamplot(q,q,U,V,color=HI,density=1.0,linewidth=.35,arrowsize=.35); ax.scatter([0],[.3],s=95,color=HI,marker="o",edgecolor="white",lw=1,label="旋涡核心"); ax.set(xlabel="场域 x",ylabel="场域 y",title="LIC-style 纹理场：局部流向而非点线采样"); clean(ax,False); ax.legend(frameon=False,loc="upper left"); label(ax,"纹理沿矢量场积分；流线仅作方向校验"); save(fig,"lic_texture_field_demo")


def morse_style_basins():
    x,y,X,Y,Z=field(); gx,gy=np.gradient(Z,x[1]-x[0],y[1]-y[0]);
    # Local extrema as critical candidates; basin labels are a deterministic
    # nearest-peak assignment for this demo, not a certified Morse-Smale run.
    peaks=ndimage.maximum_filter(Z,size=13)==Z; py,px=np.where(peaks & (Z>.38)); pts=np.c_[x[px],y[py],Z[py]]
    if len(pts)>5: order=np.argsort(pts[:,2])[-5:]; pts=pts[order]
    d=((X[...,None]-pts[:,0])**2+(Y[...,None]-pts[:,1])**2); basin=np.argmin(d,axis=2)
    fig,ax=plt.subplots(figsize=(7.3,5.0)); ax.contourf(X,Y,basin,levels=np.arange(len(pts)+1)-.5,cmap=LinearSegmentedColormap.from_list("basins",[_lighten(P[i%len(P)],.64) for i in range(len(pts))]),alpha=.62); ax.contour(X,Y,Z,levels=10,colors=INK,linewidths=.35,alpha=.4); ax.quiver(X[::7,::7],Y[::7,::7],gx[::7,::7],gy[::7,::7],color=P[0],alpha=.25,scale=35,width=.002); ax.scatter(pts[:,0],pts[:,1],s=110,color=HI,marker="*",edgecolor="white",lw=1.0,label="局部极大点"); ax.set(xlabel="场域 x",ylabel="场域 y",title="Morse-style basin map：标量场分区与临界点"); clean(ax,False); ax.legend(frameon=False,loc="upper left"); label(ax,"分区为 DEMO 的峰值归属；正式使用需由梯度流/拓扑算法计算"); save(fig,"morse_style_basins_demo")


def persistence_pair():
    births=np.array([.05,.13,.22,.31,.42,.57,.66]); deaths=np.array([.88,.74,.61,.55,.50,.69,.70]); pers=deaths-births; order=np.argsort(pers)[::-1]
    fig,(ax1,ax2)=plt.subplots(1,2,figsize=(8.1,4.2),gridspec_kw={"width_ratios":[1.1,1]});
    for i in order: ax1.plot([births[i],deaths[i]],[i,i],color=P[i%len(P)],lw=3.0,solid_capstyle="round"); ax1.scatter([births[i],deaths[i]],[i,i],color=P[i%len(P)],s=23,edgecolor="white",lw=.5)
    ax1.set(xlabel="函数值",ylabel="特征排序",title="Persistence barcode"); ax1.set_yticks([]); clean(ax1)
    ax2.scatter(births,deaths,s=55,c=[P[i%len(P)] for i in range(len(births))],edgecolor="white",lw=.7); lo=0; hi=1; ax2.plot([lo,hi],[lo,hi],ls="--",color=INK,lw=.8); ax2.set(xlim=(0,1),ylim=(0,1),xlabel="birth",ylabel="death",title="Persistence diagram"); clean(ax2)
    fig.suptitle("Persistence：特征的出现—消失生命周期",fontsize=11); label(ax1,"点/条的长度 ∝ persistence；仅为拓扑演示"); save(fig,"persistence_barcode_diagram_demo")


def contour_tree():
    x,y,X,Y,Z=field(); levels=np.linspace(Z.min()+.05,Z.max()-.05,12); comps=[]; sizes=[]
    for lv in levels:
        mask=Z>=lv; lab,n=ndimage.label(mask); cs=[]
        for k in range(1,n+1):
            area=np.sum(lab==k)
            if area>30: cs.append((k,area))
        comps.append(cs); sizes.append(sum(a for _,a in cs))
    fig,(ax,tree)=plt.subplots(1,2,figsize=(8.3,4.5),gridspec_kw={"width_ratios":[1.25,.85]}); cf=ax.contourf(X,Y,Z,levels=18,cmap=cmap_user("ct",[_lighten(P[0],.75),P[0],P[1],HI]),alpha=.85); ax.contour(X,Y,Z,levels=levels,colors="white",linewidths=.5,alpha=.68); ax.set(xlabel="x",ylabel="y",title="标量场等值层"); clean(ax,False); fig.colorbar(cf,ax=ax,label="f(x,y)")
    # Contour-tree-style level/component abstraction, derived from connected components.
    nodes=[]; edges=[]; prev=[]
    for li,(lv,cs) in enumerate(zip(levels,comps)):
        cur=[]
        for ci,(labid,area) in enumerate(cs): cur.append((li,ci,lv,area)); nodes.append(cur[-1])
        for a in prev:
            for b in cur:
                if b[3] <= a[3]*1.8: edges.append((a,b))
        prev=cur
    for a,b in edges: tree.plot([a[0],b[0]],[a[2],b[2]],color=P[0],alpha=.38,lw=1.0)
    for li,ci,lv,area in nodes: tree.scatter(li,lv,s=18+area/18,color=P[1] if area<180 else HI,edgecolor="white",lw=.4)
    tree.set(xlabel="等值层级",ylabel="函数值",title="Contour-tree-style abstraction"); clean(tree); label(tree,"节点大小 ∝ 连通区域面积；演示采用连通分支摘要"); save(fig,"contour_tree_demo")


def voronoi_delaunay():
    rng=np.random.default_rng(11); pts=rng.uniform(-1,1,(32,2)); tri=Delaunay(pts); val=.55+.35*np.sin(2*pts[:,0])+ .22*np.cos(3*pts[:,1]);
    fig,ax=plt.subplots(figsize=(6.8,5.4)); cmap=cmap_user("vor",[_lighten(P[0],.72),P[0],P[1],HI]); norm=Normalize(val.min(),val.max())
    for simplex in tri.simplices:
        poly=pts[simplex]; ax.add_patch(Polygon(poly,facecolor=cmap(norm(val[simplex].mean())),edgecolor="white",lw=.7,alpha=.88))
    ax.triplot(pts[:,0],pts[:,1],tri.simplices,color=INK,lw=.35,alpha=.45); ax.scatter(pts[:,0],pts[:,1],s=32,c=val,cmap=cmap,norm=norm,edgecolor="white",lw=.6,zorder=3); ax.set(xlim=(-1.05,1.05),ylim=(-1.05,1.05),xlabel="空间 x",ylabel="空间 y",title="Voronoi–Delaunay scalar tessellation"); ax.set_aspect("equal"); clean(ax,False); fig.colorbar(plt.cm.ScalarMappable(norm=norm,cmap=cmap),ax=ax,label="节点标量值"); label(ax,"三角剖分单元颜色由节点标量平均值决定"); save(fig,"voronoi_delaunay_scalar_demo")


def radvis_2d():
    angles=np.linspace(0,2*np.pi,7,endpoint=False); axes=np.c_[np.cos(angles),np.sin(angles)]; vals=np.array([[.92,.28,.76,.82,.45,.66,.58],[.55,.86,.42,.61,.88,.40,.72],[.75,.58,.90,.35,.62,.77,.46]])
    fig,ax=plt.subplots(figsize=(6.4,5.8)); ax.set_aspect("equal")
    for i,a in enumerate(axes): ax.plot([0,a[0]],[0,a[1]],color=GRID,lw=.8); ax.text(a[0]*1.14,a[1]*1.14,["胜率","稳定","资源","公平","恢复","速度","解释"][i],ha="center",va="center",fontsize=8)
    for i,row in enumerate(vals):
        q=row@axes; ax.plot(np.r_[q[0],q[0]],np.r_[q[1],q[1]],alpha=0) # keep deterministic path anchor
        poly=axes*row[:,None]; poly=np.vstack([poly,poly[0]]); ax.plot(poly[:,0],poly[:,1],color=P[i],lw=1.9,label=f"候选{i+1}"); ax.fill(poly[:,0],poly[:,1],color=P[i],alpha=.10); ax.scatter(q[0],q[1],color=P[i],s=42,edgecolor="white",lw=.7)
    ax.scatter([0],[0],s=100,color=HI,marker="*",edgecolor="white",label="参考原点"); ax.set(xlim=(-1.35,1.35),ylim=(-1.35,1.35),xlabel="径向投影 x",ylabel="径向投影 y",title="2D-RadVis：多目标空间的径向投影"); clean(ax,False); ax.legend(frameon=False,loc="best"); label(ax,"目标轴角度固定；候选多边形保留多目标结构，不等同普通雷达图"); save(fig,"radvis_2d_demo")


def constraint_tension():
    x=np.linspace(0,1,100); y=np.linspace(0,1,90); X,Y=np.meshgrid(x,y); obj=.2+.7*X+.35*Y+.15*np.sin(3*X)*np.cos(2*Y); slack=np.minimum(1-X,.9-Y); feasible=(X+Y<1.35)&(X>.08)&(Y>.06); rng=np.random.default_rng(8); pts=rng.uniform(.1,.9,(45,2)); vals=.2+.7*pts[:,0]+.35*pts[:,1]; ok=(pts[:,0]+pts[:,1]<1.35); fig,ax=plt.subplots(figsize=(7.1,5.0)); cf=ax.contourf(X,Y,slack,levels=14,cmap=cmap_user("slack",[_lighten(P[1],.78),P[1],HI]),alpha=.82); ax.contour(X,Y,obj,levels=8,colors=INK,linewidths=.45,alpha=.55); ax.contourf(X,Y,~feasible,levels=[.5,1],colors=[_lighten(P[2],.82)],alpha=.45); ax.scatter(pts[ok,0],pts[ok,1],s=22+65*(1-np.clip(vals[ok],.2,1)),color=P[0],alpha=.65,edgecolor="white",lw=.45,label="可行候选"); ax.scatter(pts[~ok,0],pts[~ok,1],s=40,color=COLORS.get("neutral","#999999"),marker="x",label="不可行"); k=np.where(ok)[0][np.argmax(vals[ok])]; ax.scatter([pts[k,0]],[pts[k,1]],s=160,color=HI,marker="*",edgecolor="white",label="高目标/高张力点"); ax.set(xlabel="决策变量 x",ylabel="决策变量 y",title="Constraint tension map：目标等值线与约束余量"); clean(ax,False); fig.colorbar(cf,ax=ax,label="约束余量 slack"); ax.legend(frameon=False,loc="best"); label(ax,"背景：约束余量；等值线：目标；点大小：目标张力"); save(fig,"constraint_tension_map_demo")


def separator_field():
    x=np.linspace(-2.2,2.2,120); y=np.linspace(-1.8,1.8,100); X,Y=np.meshgrid(x,y); psi=(X**3-3*X)+(Y**2-.7)+.35*np.sin(2*Y); U=np.gradient(psi,axis=1); V=np.gradient(psi,axis=0); speed=np.hypot(U,V); fig,ax=plt.subplots(figsize=(7.1,4.8)); cf=ax.contourf(X,Y,psi,levels=18,cmap=cmap_user("psi",[_lighten(P[0],.8),P[0],P[1],HI]),alpha=.74); ax.streamplot(x,y,U,V,color=speed,density=1.5,cmap=cmap_user("flow",[_lighten(P[1],.55),P[1],HI]),linewidth=.75,arrowsize=.55); ax.contour(X,Y,psi,levels=[0],colors=[HI],linewidths=2.0); ax.scatter([-1,1],[0,0],s=90,color=P[0],edgecolor="white",label="临界候选"); ax.set(xlabel="状态 x",ylabel="状态 y",title="Separator-field map：势场、流向与分离边界"); clean(ax,False); fig.colorbar(cf,ax=ax,label="势函数 ψ(x,y)"); ax.legend(frameon=False,loc="upper left"); label(ax,"流线：梯度场方向；高亮等值线：分离/决策边界"); save(fig,"separator_field_demo")


def main():
    funcs=[carpet_plot,lic_like,morse_style_basins,persistence_pair,contour_tree,voronoi_delaunay,radvis_2d,constraint_tension,separator_field]
    for fn in funcs: fn()
    print(f"generated {len(funcs)} advanced 2-D demos in {OUT}")

if __name__ == "__main__":
    main()

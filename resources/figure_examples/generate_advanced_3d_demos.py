# -*- coding: utf-8 -*-
"""Advanced 3-D scientific visualization demos for Modex.

All data in this file are deterministic DEMO ONLY data. They are visual
capability samples, not scientific results. Replace every array with a
traceable result manifest before using any figure in a paper.
"""
from pathlib import Path
import sys
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import cm
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.collections import PolyCollection
from mpl_toolkits.mplot3d.art3d import Poly3DCollection, Line3DCollection

ROOT = Path.cwd()
if not (ROOT / "_utils" / "plot_utils.py").exists():
    raise SystemExit("Run from a Modex workspace containing _utils/plot_utils.py")
sys.path.insert(0, str(ROOT))
from _utils.plot_utils import setup_style, save_fig, PALETTE, COLORS, _lighten

setup_style("auto")
OUT = ROOT / "figures" / "_advanced_3d_demos"
OUT.mkdir(parents=True, exist_ok=True)
P = list(PALETTE)
INK = COLORS.get("text", "#333333")
GRID = COLORS.get("grid", "#E0E0E0")
HI = COLORS.get("highlight", P[1])


def cmap_user(name, colors):
    return LinearSegmentedColormap.from_list(name, colors, N=256)


def base3d(ax, title, xlabel, ylabel, zlabel):
    ax.set_title("DEMO · " + title, fontsize=10, pad=12)
    ax.set_xlabel(xlabel, labelpad=5)
    ax.set_ylabel(ylabel, labelpad=5)
    ax.set_zlabel(zlabel, labelpad=5)
    ax.grid(True, alpha=.14, color=GRID, linewidth=.6)
    ax.xaxis.pane.set_alpha(0.03); ax.yaxis.pane.set_alpha(0.03); ax.zaxis.pane.set_alpha(0.03)
    ax.view_init(elev=25, azim=-55)


def save3d(fig, name):
    fig.savefig(OUT / f"{name}.pdf", format="pdf", bbox_inches="tight", pad_inches=.08)
    fig.savefig(OUT / f"{name}.png", format="png", dpi=600, bbox_inches="tight", pad_inches=.08)
    plt.close(fig)


def risk_landscape_isosurface():
    # A scalar risk field in a genuine 3-D parameter space.
    x = np.linspace(-2.4, 2.4, 42); y = np.linspace(-2.2, 2.2, 42); z = np.linspace(-1.5, 1.5, 30)
    X, Y, Z = np.meshgrid(x, y, z, indexing="ij")
    F = (X**2 + .7*Y**2 + 1.4*Z**2 + .22*np.sin(3*X)*np.cos(2*Y)
         - .75*np.exp(-((X-.8)**2+(Y+.2)**2+(Z-.2)**2)/.55))
    # Marching-cubes-free implicit isosurfaces: nested ellipsoidal shells.
    fig = plt.figure(figsize=(7.8, 6.0)); ax = fig.add_subplot(111, projection="3d")
    for level, alpha, color in [(0.35, .12, P[0]), (.85, .08, P[1]), (1.35, .045, P[2])]:
        u = np.linspace(0, 2*np.pi, 80); v = np.linspace(0, np.pi, 42)
        sx = 1.55*np.sqrt(level)*np.outer(np.cos(u), np.sin(v))
        sy = 1.25*np.sqrt(level)*np.outer(np.sin(u), np.sin(v))
        sz = .85*np.sqrt(level)*np.outer(np.ones_like(u), np.cos(v))
        ax.plot_surface(sx, sy, sz, color=color, alpha=alpha, linewidth=0, antialiased=True, shade=True)
    # Actual scalar-field slices show the underlying response, not only the shell.
    mid = np.argmin(abs(z-.1)); ax.contourf(X[:, :, mid], Y[:, :, mid], F[:, :, mid], zdir="z", offset=-1.35, levels=12, cmap=cmap_user("risk", [_lighten(P[0], .75), P[0], HI]), alpha=.72)
    pts = np.array([[-1.35,-.8,.2],[-.6,.8,-.4],[.25,-.1,.25],[.9,.2,-.1],[1.4,.75,.4]])
    ax.scatter(pts[:,0],pts[:,1],pts[:,2],s=45,c=P[3:3+len(pts)],edgecolor="white",lw=.8,depthshade=False)
    ax.scatter([.25],[ -.1],[.25],s=150,c=[HI],marker="*",edgecolor="white",lw=1.1,label="稳健候选")
    base3d(ax,"3-D 风险地形 + 等值壳层 + 参数切片","参数 x","参数 y","参数 z")
    ax.text2D(.02,.03,"透明壳层：风险等值面；底部：z≈0.1 的真实场切片；点：候选方案",transform=ax.transAxes,fontsize=8,color=INK)
    ax.legend(frameon=False,loc="upper left"); save3d(fig,"risk_landscape_isosurface_demo")


def cutaway_volume():
    # A cutaway view of a scalar volume: outer translucent shell + internal slices.
    x=np.linspace(-2,2,36); y=np.linspace(-2,2,36); z=np.linspace(-1.5,1.5,30); X,Y,Z=np.meshgrid(x,y,z,indexing="ij")
    V=np.exp(-((X+.6)**2+(Y-.3)**2+(Z)**2)/.7)+.72*np.exp(-((X-.8)**2+(Y+.5)**2+(Z-.25)**2)/.45)
    fig=plt.figure(figsize=(7.7,5.9)); ax=fig.add_subplot(111,projection="3d")
    # volume-like point cloud sampled by scalar opacity
    flat=V.ravel(); idx=np.argsort(flat)[-900:]; xp,yp,zp=X.ravel()[idx],Y.ravel()[idx],Z.ravel()[idx]; vp=flat[idx]
    ax.scatter(xp,yp,zp,c=vp,cmap=cmap_user("volume",[_lighten(P[0],.85),P[0],P[1],HI]),s=7+34*vp,alpha=.46,edgecolor="none",depthshade=False)
    # orthogonal cutaway slices
    norm=Normalize(vmin=0,vmax=V.max())
    ax.plot_surface(X[:,:,15],Y[:,:,15],Z[:,:,15],facecolors=cmap_user("slice",[_lighten(P[0],.8),P[0],HI])(norm(V[:,:,15])),alpha=.78,shade=False,linewidth=0)
    ax.plot_surface(X[:,18,:],Y[:,18,:],Z[:,18,:],facecolors=cmap_user("slice2",[_lighten(P[1],.82),P[1],HI])(norm(V[:,18,:])),alpha=.45,shade=False,linewidth=0)
    ax.scatter([-.6,.8],[.3,-.5],[0,.25],s=100,c=[HI,P[1]],marker="*",edgecolor="white",lw=1.0)
    base3d(ax,"体数据切面 + 半透明高值体","空间 x","空间 y","空间 z")
    ax.text2D(.02,.03,"点云透明度/大小 ∝ 标量场强度；两张切面显示内部结构",transform=ax.transAxes,fontsize=8,color=INK)
    save3d(fig,"cutaway_volume_demo")


def streamtube_field():
    # 3-D vector field with tube-like trajectories and a scalar context plane.
    t=np.linspace(0,1,180); fig=plt.figure(figsize=(7.8,5.8)); ax=fig.add_subplot(111,projection="3d")
    for k in range(13):
        a=-1.35+k*.225
        xx=a+.32*np.sin(2*np.pi*t+.5*k)*np.exp(-1.1*t)
        yy=-1.45+2.9*t+.22*np.cos(3*np.pi*t+.3*k)
        zz=.38*np.sin(2*np.pi*t+.25*k)+.18*np.cos(5*np.pi*t)
        speed=np.sqrt(np.gradient(xx)**2+np.gradient(yy)**2+np.gradient(zz)**2)
        ax.plot(xx,yy,zz,color=P[k%len(P)],lw=1.0+2.0*(k in [3,8,10]),alpha=.28 if k not in [3,8,10] else .9)
        # sparse cross-section markers give a tube impression without fake surface geometry
        ax.scatter(xx[::24],yy[::24],zz[::24],s=8+18*speed[::24]/speed.max(),color=P[k%len(P)],alpha=.6,depthshade=False)
    gx=np.linspace(-1.5,1.5,26); gy=np.linspace(-1.5,1.5,26); GX,GY=np.meshgrid(gx,gy); GZ=-.65+.12*np.sin(GX)*np.cos(GY)
    ax.plot_surface(GX,GY,GZ,color=_lighten(P[2],.72),alpha=.35,linewidth=0)
    ax.scatter([0],[ -1.45],[0],s=110,color=HI,marker="^",edgecolor="white",label="源区")
    base3d(ax,"3-D 流管式策略场 + 标量背景切片","状态 x","时间/阶段 y","状态 z")
    ax.text2D(.02,.03,"轨迹：矢量场积分路径；重点轨迹用更高视觉权重；平面：标量场背景",transform=ax.transAxes,fontsize=8,color=INK)
    ax.legend(frameon=False,loc="upper left"); save3d(fig,"streamtube_field_demo")


def uncertainty_shell():
    # Ensemble surfaces: mean surface plus translucent uncertainty envelope.
    u=np.linspace(0,2*np.pi,80); v=np.linspace(0,np.pi,42); U,V=np.meshgrid(u,v)
    R=1.0+.12*np.sin(3*U)*np.sin(2*V); mean=np.array([R*np.sin(V)*np.cos(U),R*np.sin(V)*np.sin(U),.72*R*np.cos(V)])
    fig=plt.figure(figsize=(7.2,5.8)); ax=fig.add_subplot(111,projection="3d")
    for q,(dr,c) in enumerate([(-.14,P[1]),(-.07,P[0]),(.07,P[0]),(.14,P[1])]):
        rr=R+dr*(.35+.65*np.sin(V)**2); ax.plot_surface(rr*np.sin(V)*np.cos(U),rr*np.sin(V)*np.sin(U),.72*rr*np.cos(V),color=c,alpha=.075,linewidth=0,shade=True)
    ax.plot_surface(mean[0],mean[1],mean[2],color=P[0],alpha=.42,linewidth=.15,edgecolor=_lighten(P[0],.2),shade=True)
    ax.plot_wireframe(mean[0],mean[1],mean[2],rstride=5,cstride=8,color=INK,alpha=.10,linewidth=.35)
    base3d(ax,"Ensemble 不确定性外壳 + 中心曲面","状态 x","状态 y","响应 z")
    ax.text2D(.02,.03,"中心曲面：均值；透明外壳：ensemble spread（演示）",transform=ax.transAxes,fontsize=8,color=INK)
    save3d(fig,"uncertainty_shell_demo")


def radvis_3d():
    # 3D radial coordinates for six objectives, with candidate trajectories.
    axes=np.array([[1,0,0],[-.5,.86,0],[-.5,-.86,0],[0,0,1],[0,0,-1],[.65,.2,.73]],float)
    axes/=np.linalg.norm(axes,axis=1,keepdims=True); vals=np.array([[.9,.3,.7,.8,.5,.65],[.5,.85,.45,.58,.9,.42],[.72,.58,.82,.36,.62,.78],[.38,.72,.55,.88,.47,.56]])
    fig=plt.figure(figsize=(7.7,6.0)); ax=fig.add_subplot(111,projection="3d")
    labels=["胜率","稳定性","资源效率","公平性","恢复力","可解释性"]
    for i,a in enumerate(axes): ax.plot([0,a[0]],[0,a[1]],[0,a[2]],color=GRID,lw=1.0); ax.text(*(a*1.12),labels[i],fontsize=8,color=INK)
    for i,row in enumerate(vals):
        p=row@axes; ax.plot(np.r_[p[0],0],np.r_[p[1],0],np.r_[p[2],0],color=P[i],alpha=.25,lw=.6)
        pts=axes*row[:,None]; pts=np.vstack([pts,pts[0]])
        ax.plot(pts[:,0],pts[:,1],pts[:,2],color=P[i],lw=2,label=f"候选{i+1}"); ax.scatter([p[0]],[p[1]],[p[2]],s=55,color=P[i],edgecolor="white",lw=.7)
    ax.scatter([0],[0],[0],s=80,color=HI,marker="*",label="原点")
    base3d(ax,"3D-RadVis：多目标候选的径向投影","Radial x","Radial y","Radial z")
    ax.text2D(.02,.03,"六条目标轴保留原始目标语义；候选多边形显示多目标结构",transform=ax.transAxes,fontsize=8,color=INK)
    ax.legend(frameon=False,loc="upper left"); save3d(fig,"radvis_3d_demo")


def pareto_surface():
    # A genuine three-objective Pareto surface with feasible boundary and selected point.
    a=np.linspace(.05,.95,35); b=np.linspace(.05,.95,35); A,B=np.meshgrid(a,b)
    C=1-(.72*A+.55*B-.16*np.sin(3*A)*np.cos(2*B)); C=np.clip(C,.05,.98)
    feasible=(A+B<1.35)&(C>.18)
    fig=plt.figure(figsize=(7.8,5.9)); ax=fig.add_subplot(111,projection="3d")
    ax.plot_surface(A,B,C,facecolors=cmap_user("pareto",[_lighten(P[0],.65),P[0],HI])(Normalize(C.min(),C.max())(C)),alpha=.54,linewidth=.12,edgecolor="white",shade=True)
    ax.plot_wireframe(A,B,C,rstride=5,cstride=5,color=INK,alpha=.10,linewidth=.35)
    ax.scatter(A[feasible][::8],B[feasible][::8],C[feasible][::8],s=11,color=P[2],alpha=.62,depthshade=False)
    k=np.unravel_index(np.argmin((A-.66)**2+(B-.47)**2+(C-.42)**2),A.shape)
    ax.scatter([A[k]],[B[k]],[C[k]],s=170,color=HI,marker="*",edgecolor="white",lw=1.1)
    base3d(ax,"三目标 Pareto 响应面 + 可行候选","目标/资源 A","目标/资源 B","目标 C")
    ax.text2D(.02,.03,"曲面：三目标响应；散点：可行候选；星标：示例选择点",transform=ax.transAxes,fontsize=8,color=INK)
    save3d(fig,"pareto_surface_demo")


def tensor_glyph_field():
    # Ellipsoidal tensor glyphs on a 3-D lattice; axes encode anisotropic uncertainty.
    fig=plt.figure(figsize=(7.8,5.9)); ax=fig.add_subplot(111,projection="3d")
    centers=[]
    for x in [-1.0,0,1.0]:
        for y in [-.8,.2,1.0]:
            z=.25*np.sin(x*2)+.18*np.cos(y*2); centers.append((x,y,z))
    u=np.linspace(0,2*np.pi,24); v=np.linspace(0,np.pi,12); U,V=np.meshgrid(u,v)
    for i,(cx,cy,cz) in enumerate(centers):
        ang=.35*cx+.22*cy; ca,sa=np.cos(ang),np.sin(ang); q=.16+.035*(i%3); r=.26+.04*((i+1)%3); h=.18+.05*(i%2)
        X=q*np.sin(V)*np.cos(U); Y=r*np.sin(V)*np.sin(U); Z=h*np.cos(V)
        XX=ca*X-sa*Y+cx; YY=sa*X+ca*Y+cy; ZZ=Z+cz
        ax.plot_surface(XX,YY,ZZ,color=P[i%len(P)],alpha=.48,linewidth=.1,edgecolor="white",shade=True)
        ax.plot([cx-q*ca,cx+q*ca],[cy-q*sa,cy+q*sa],[cz,cz],color=INK,lw=.7,alpha=.6)
    base3d(ax,"3-D Tensor Glyph Field：各向异性不确定性","空间 x","空间 y","场响应 z")
    ax.text2D(.02,.03,"超椭球长短轴：协方差结构；旋转：主方向；颜色：场分区（演示）",transform=ax.transAxes,fontsize=8,color=INK)
    save3d(fig,"tensor_glyph_field_demo")


def topological_skeleton():
    # Terrain plus a hand-constructed contour-tree/Morse-style skeleton for a demo.
    x=np.linspace(-2.4,2.4,70); y=np.linspace(-2.0,2.0,62); X,Y=np.meshgrid(x,y)
    Z=1.25*np.exp(-((X+1.15)**2+(Y+.45)**2)/.42)+.95*np.exp(-((X-.75)**2+(Y-.55)**2)/.6)-.55*np.exp(-((X+.1)**2+(Y-.1)**2)/.9)
    fig=plt.figure(figsize=(8.0,5.9)); ax=fig.add_subplot(111,projection="3d")
    ax.plot_surface(X,Y,Z,cmap=cmap_user("terrain",[_lighten(P[0],.75),P[0],P[1],HI]),alpha=.78,linewidth=0,shade=True)
    nodes=np.array([[-1.15,-.45,1.25],[.75,.55,.95],[-.1,-.1,-.55],[-1.65,1.1,.08],[1.45,-1.0,.05]])
    edges=[(0,2),(1,2),(0,3),(1,4)]
    for i,j in edges: ax.plot(nodes[[i,j],0],nodes[[i,j],1],nodes[[i,j],2]+.05,color=INK,lw=2.3,alpha=.9)
    ax.scatter(nodes[:,0],nodes[:,1],nodes[:,2]+.07,s=[115,115,95,55,55],c=[HI,P[1],P[2],P[0],P[0]],edgecolor="white",lw=1.0)
    ax.text(-1.15,-.45,1.45,"极大点",fontsize=8); ax.text(.75,.55,1.15,"极大点",fontsize=8); ax.text(-.1,-.1,-.72,"鞍/谷",fontsize=8)
    base3d(ax,"Topological Skeleton：地形与极值—鞍点骨架","场域 x","场域 y","标量值")
    ax.text2D(.02,.03,"曲面：标量场；骨架：临界点及其连接关系（Morse/contour-tree 风格演示）",transform=ax.transAxes,fontsize=8,color=INK)
    save3d(fig,"topological_skeleton_demo")


def bo3_state_space():
    # Strategy trajectory through time-energy-win probability state space.
    t=np.linspace(0,1,180); energy=1.05-.62*t+.12*np.sin(4*np.pi*t); win=.35+.48/(1+np.exp(-8*(t-.48)))+.035*np.sin(8*np.pi*t); risk=.18+.14*np.cos(5*np.pi*t)
    fig=plt.figure(figsize=(7.9,5.8)); ax=fig.add_subplot(111,projection="3d")
    pts=np.column_stack([t,energy,win]); seg=np.stack([pts[:-1],pts[1:]],axis=1); lc=Line3DCollection(seg,colors=cmap_user("path",[P[1],P[0],P[2]])(np.linspace(0,1,len(seg))),linewidths=2.2,alpha=.9); ax.add_collection3d(lc)
    ax.scatter(t[::12],energy[::12],win[::12],c=risk[::12],cmap=cmap_user("riskpath",[_lighten(P[1],.45),HI]),s=20+70*risk[::12],edgecolor="white",lw=.45,depthshade=False)
    events=[(.18,"暂停"),(.45,"换电"),(.68,"维修")]
    for q,name in events:
        i=np.argmin(abs(t-q)); ax.scatter([t[i]],[energy[i]],[win[i]],s=120,color=HI,marker="D",edgecolor="white",lw=1); ax.text(t[i],energy[i],win[i]+.04,name,fontsize=8)
    ax.plot(t,energy,np.zeros_like(t),color=P[3%len(P)],alpha=.24,lw=.9)
    base3d(ax,"BO3 状态空间轨迹：资源—胜率—时间","比赛进程 t","剩余资源/能量","胜率")
    ax.text2D(.02,.03,"主轨迹：策略状态演化；点大小/颜色：风险；菱形：暂停、换电、维修事件",transform=ax.transAxes,fontsize=8,color=INK)
    save3d(fig,"bo3_state_space_demo")


def main():
    funcs=[risk_landscape_isosurface,cutaway_volume,streamtube_field,uncertainty_shell,radvis_3d,pareto_surface,tensor_glyph_field,topological_skeleton,bo3_state_space]
    for fn in funcs: fn()
    print(f"generated {len(funcs)} advanced 3-D demos in {OUT}")

if __name__ == "__main__":
    main()

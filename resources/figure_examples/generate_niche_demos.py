# -*- coding: utf-8 -*-
"""Generate deterministic DEMO images for the long-tail figure catalog.

These are visual examples only. Replace all demo arrays with source-manifest
arrays before using any figure as scientific evidence.
"""
from pathlib import Path
import sys
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, PathPatch, Polygon, Ellipse
from matplotlib.path import Path as MPath
from matplotlib.colors import Normalize, LinearSegmentedColormap
from matplotlib import cm

# Run from a workspace so its frozen palette/layout settings are respected.
ROOT = Path.cwd()
if not (ROOT / "_utils" / "plot_utils.py").exists():
    raise SystemExit("Run from a Modex workspace containing _utils/plot_utils.py")
sys.path.insert(0, str(ROOT))
from _utils.plot_utils import setup_style, PALETTE, COLORS, _lighten

setup_style("auto")
OUT = ROOT / "figures" / "_niche_demos"
OUT.mkdir(parents=True, exist_ok=True)
P = list(PALETTE)
INK = COLORS.get("text", "#333333")
GRID = COLORS.get("grid", "#E0E0E0")
HI = COLORS.get("highlight", P[1])
BG = "white"


def save(fig, name):
    fig.patch.set_facecolor(BG)
    fig.savefig(OUT / f"{name}.pdf", format="pdf", bbox_inches="tight", pad_inches=.08)
    fig.savefig(OUT / f"{name}.png", format="png", dpi=600, bbox_inches="tight", pad_inches=.08)
    plt.close(fig)


def label(ax, text):
    ax.text(.02, .98, f"DEMO · {text}", transform=ax.transAxes, ha="left", va="top",
            fontsize=8, color=INK, bbox=dict(facecolor="white", edgecolor="none", alpha=.82, pad=2))


def clean(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=.12, color=GRID)
    ax.set_axisbelow(True)


def bezier(p1, p2, bend=.35):
    x1, y1 = p1; x2, y2 = p2
    cx = (x1 + x2) / 2
    cy = max(y1, y2) + abs(x2 - x1) * bend + .05
    verts = [p1, (cx, cy), (cx, cy), p2]
    return MPath(verts, [MPath.MOVETO, MPath.CURVE4, MPath.CURVE4, MPath.CURVE4])


def ecdf_threshold():
    groups = {"稳健策略": np.array([.19,.22,.24,.27,.29,.31,.34,.36,.37,.39,.41,.43,.45,.47,.50,.52,.55]),
              "激进策略": np.array([.25,.29,.32,.35,.39,.41,.44,.47,.50,.53,.57,.60,.63,.66,.70,.74,.78])}
    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    for i, (name, vals) in enumerate(groups.items()):
        x = np.sort(vals); y = np.arange(1, len(x)+1) / len(x)
        ax.step(x, y, where="post", color=P[i], lw=2.2, label=f"{name}（n={len(x)}）")
        ax.scatter(x, y, color=P[i], s=15, edgecolor="white", linewidth=.4, zorder=3)
    ax.axvline(.55, color=HI, ls="--", lw=1.4, label="风险阈值")
    ax.axhline(.75, color=INK, ls=":", lw=1.0)
    ax.text(.56, .77, "超过阈值的比例", fontsize=8, color=INK)
    ax.set(xlabel="失稳风险指标", ylabel="经验累积分布 F(x)", title="ECDF + 阈值：比较尾部风险")
    clean(ax); ax.legend(frameon=False, loc="lower right"); save(fig, "ecdf_threshold_demo")


def quantile_dot():
    probs = [("方案 A", .32), ("方案 B", .58), ("方案 C", .76)]
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    xs = np.arange(20)
    for i, (name, p) in enumerate(probs):
        filled = int(round(p * 20))
        ax.scatter(xs, np.full(20, i), s=34, color=_lighten(P[i], .68), edgecolor="white", lw=.4)
        ax.scatter(xs[:filled], np.full(filled, i), s=34, color=P[i], edgecolor="white", lw=.4)
        ax.text(20.5, i, f"{p:.0%}", va="center", fontsize=9, color=INK)
    ax.set(xticks=[0,4,9,14,19], xticklabels=["0%","20%","50%","75%","100%"],
           yticks=range(3), yticklabels=[x[0] for x in probs], xlabel="可能结果的分位位置", title="Quantile dot plot：概率的频率表达")
    ax.set_xlim(-.8, 22.2); ax.set_ylim(-.7, 2.7); ax.grid(False); ax.spines[["top","right","left"]].set_visible(False)
    label(ax, "每个实心点代表约 5% 概率"); save(fig, "quantile_dot_demo")


def beeswarm():
    vals = [np.array([.23,.26,.27,.30,.31,.33,.34,.35,.36,.40,.42,.45]),
            np.array([.29,.30,.34,.36,.38,.41,.44,.46,.50,.53,.56,.62]),
            np.array([.18,.22,.25,.28,.31,.35,.39,.43,.46,.48,.51,.55])]
    fig, ax = plt.subplots(figsize=(7.1, 4.2))
    for i, ys in enumerate(vals):
        order = np.argsort(ys); offsets = .09 * np.sin(np.arange(len(ys)) * 2.4)
        ax.scatter(ys, np.full(len(ys), i) + offsets, color=P[i], s=37, alpha=.78, edgecolor="white", lw=.55, label=f"动作组 {i+1}")
        ax.plot([np.median(ys)]*2, [i-.25, i+.25], color=INK, lw=2.2, solid_capstyle="round")
    ax.set(yticks=range(3), yticklabels=["拳法","腿法","组合技"], xlabel="重复仿真的风险值", title="Beeswarm：保留原始点并显示组内分布")
    clean(ax); ax.legend(frameon=False, loc="best"); save(fig, "beeswarm_demo")


def ridgeline():
    x = np.linspace(-3, 4, 320)
    params = [("低故障", .0, .58), ("中故障", .65, .72), ("高故障", 1.35, .82), ("极端故障", 2.05, .95)]
    fig, ax = plt.subplots(figsize=(7.3, 4.8))
    for i, (name, mu, sd) in enumerate(params):
        y = np.exp(-.5*((x-mu)/sd)**2) + .22*np.exp(-.5*((x-(mu+1.1))/(sd*.55))**2)
        y /= y.max()
        base = i * .72
        ax.fill_between(x, base, base + y*.68, color=_lighten(P[i], .38), alpha=.86)
        ax.plot(x, base + y*.68, color=P[i], lw=1.7)
        ax.text(-3.25, base+.12, name, ha="right", va="center", fontsize=8.5, color=INK)
        ax.axhline(base, color=GRID, lw=.55)
    ax.set(xlabel="资源消耗标准化值", yticks=[], title="Ridgeline：多种故障压力下的分布形状")
    ax.set_xlim(-3.65, 4.1); ax.set_ylim(-.15, 3.15); ax.spines[:].set_visible(False); ax.grid(False); save(fig, "ridgeline_demo")


def horizon():
    t = np.arange(72); y = .55*np.sin(t/6) + .22*np.sin(t/2.8) + .08*(t-35)/35
    fig, ax = plt.subplots(figsize=(8.0, 3.1))
    ax.axhline(0, color=INK, lw=.7)
    # Horizon bands: the same series split into magnitude layers, not invented data.
    ax.fill_between(t, 0, np.maximum(y, 0), color=_lighten(P[0], .35), alpha=.9)
    ax.fill_between(t, 0, np.minimum(y, 0), color=_lighten(P[1], .35), alpha=.9)
    ax.fill_between(t, 0, np.maximum(y-.42, 0), color=P[0], alpha=.72)
    ax.fill_between(t, 0, np.minimum(y+.42, 0), color=P[1], alpha=.72)
    ax.plot(t, y, color=INK, lw=1.0, alpha=.75)
    ax.set(xlabel="比赛时间（离散时刻）", ylabel="资源偏差", title="Horizon chart：长时序中压缩显示正负偏差")
    clean(ax); save(fig, "horizon_demo")


def parallel_sets():
    left = ["攻击类型", "防守响应", "结果状态"]; cats = [["拳法","腿法","组合技"], ["闪避","格挡","恢复"], ["得分","失稳","反击"]]
    links = [((0,0),(1,0),.32),((0,0),(1,1),.38),((0,1),(1,0),.28),((0,1),(1,2),.42),((0,2),(1,1),.31),((0,2),(1,2),.24),((1,0),(2,0),.42),((1,0),(2,1),.18),((1,1),(2,0),.36),((1,1),(2,2),.31),((1,2),(2,0),.22),((1,2),(2,2),.36)]
    fig, ax = plt.subplots(figsize=(8.2, 4.5)); ax.set_xlim(-.1, 2.1); ax.set_ylim(-.1, 3.1); ax.axis("off")
    pos = {}
    for k, group in enumerate(cats):
        for j, name in enumerate(group):
            yy = 2.55 - j*.88 + (k*.03); pos[(k,j)] = (k, yy)
            ax.add_patch(Rectangle((k-.09, yy-.16), .18, .32, facecolor=_lighten(P[j%len(P)], .42), edgecolor=P[j%len(P)], lw=1.1))
            ax.text(k, yy, name, ha="center", va="center", fontsize=8)
        ax.text(k, 3.0, left[k], ha="center", fontsize=9, fontweight="bold")
    for q, ((a,ai),(b,bi),w) in enumerate(links):
        p1=(pos[(a,ai)][0]+.09,pos[(a,ai)][1]); p2=(pos[(b,bi)][0]-.09,pos[(b,bi)][1])
        ax.add_patch(PathPatch(bezier(p1,p2,.28), fill=False, edgecolor=P[ai%len(P)], lw=1+7*w, alpha=.20+.35*w))
    ax.text(1, .15, "边宽 ∝ 真实转移概率（演示数据）", ha="center", fontsize=8, color=INK)
    save(fig, "parallel_sets_demo")


def mosaic_association():
    table = np.array([[32, 18, 10], [14, 36, 20], [8, 18, 42]], dtype=float)
    rowp = table.sum(1)/table.sum(); colp = table.sum(0)/table.sum(); expected = table.sum(1,keepdims=True)*table.sum(0,keepdims=True)/table.sum(); resid=(table-expected)/np.sqrt(expected)
    fig, ax = plt.subplots(figsize=(6.8, 4.8)); x0=0
    for i in range(3):
        y0=0
        for j in range(3):
            h=table[i,j]/table[i].sum(); color=P[0] if resid[i,j]>=0 else P[1]
            alpha=.25 + .65*min(abs(resid[i,j])/3,1)
            ax.add_patch(Rectangle((x0,y0), rowp[i], h, facecolor=color, alpha=alpha, edgecolor="white", lw=1.5))
            ax.text(x0+rowp[i]/2,y0+h/2,f"{int(table[i,j])}\nΔ={resid[i,j]:+.1f}",ha="center",va="center",fontsize=8)
            y0 += h
        ax.text(x0+rowp[i]/2,-.07,["落后","平局","领先"][i],ha="center",va="top",fontsize=8)
        x0 += rowp[i]
    ax.set_xlim(0,1); ax.set_ylim(0,1); ax.set_xticks([]); ax.set_yticks([0,.5,1], ["得分","失稳","反击"]); ax.set_title("Mosaic / association：列联结构与标准化残差")
    ax.set_xlabel("比分状态（横向面积 ∝ 边际频数）"); ax.grid(False); ax.spines[["top","right","bottom"]].set_visible(False); save(fig, "mosaic_association_demo")


def arc_diagram():
    names=["拳","腿","组合","闪避","格挡","恢复","反击"]; x=np.arange(len(names)); edges=[(0,3,.8),(0,4,.55),(1,3,.5),(1,5,.72),(2,4,.66),(2,6,.82),(4,5,.42),(5,6,.52)]
    fig, ax=plt.subplots(figsize=(8,3.8)); ax.scatter(x,np.zeros(len(x)),s=130,color=P[:len(x)],edgecolor="white",lw=1.2,zorder=4)
    for i,n in enumerate(names): ax.text(x[i],-.14,n,ha="center",va="top",fontsize=8)
    for i,j,w in edges:
        p=bezier((x[i],0),(x[j],0),.22); ax.add_patch(PathPatch(p,fill=False,color=P[i%len(P)],lw=1+3*w,alpha=.62))
    ax.set_xlim(-.6,6.6); ax.set_ylim(-.7,2.0); ax.axis("off"); ax.set_title("Arc diagram：有序动作节点之间的稀疏关系"); save(fig, "arc_diagram_demo")


def hive_plot():
    roles=[("攻击",0), ("防守",1), ("恢复",2)]; pos={}; fig, ax=plt.subplots(figsize=(6.6,5.6)); ax.set_aspect("equal");
    for r,(name,k) in enumerate(roles):
        theta=np.deg2rad(90-r*120); ux,uy=np.cos(theta),np.sin(theta); vx,vy=-uy,ux
        for j in range(4 if k<2 else 3):
            q=(j+1)/5; px=ux*q; py=uy*q; pos[(k,j)]=(px,py); ax.scatter(px,py,s=85,color=P[(k+j)%len(P)],edgecolor="white",lw=1,zorder=3)
        ax.text(ux*1.12,uy*1.12,name,ha="center",va="center",fontsize=9,fontweight="bold")
        ax.plot([0,ux],[0,uy],color=GRID,lw=.8)
    for (a,i),(b,j) in [((0,0),(1,1)),((0,1),(1,2)),((0,2),(2,1)),((0,3),(1,0)),((1,0),(2,0)),((1,2),(2,2)),((1,3),(2,1))]:
        ax.add_patch(PathPatch(bezier(pos[(a,i)],pos[(b,j)],.08),fill=False,color=P[a],lw=1.5,alpha=.55))
    ax.set_xlim(-1.3,1.3); ax.set_ylim(-1.3,1.3); ax.axis("off"); ax.set_title("Hive plot：按角色轴表达攻防恢复关系"); save(fig, "hive_plot_demo")


def recurrence_plot():
    t=np.linspace(0,12*np.pi,150); x=np.sin(t)+.25*np.sin(3*t); D=np.abs(x[:,None]-x[None,:]); R=(D<.22).astype(float)
    fig, (ax1,ax2)=plt.subplots(1,2,figsize=(8.0,3.8),gridspec_kw={"width_ratios":[1,1.15]}); ax1.plot(t,x,color=P[0],lw=1.3); ax1.set(xlabel="时间",ylabel="状态",title="原始状态序列"); clean(ax1)
    ax2.imshow(R,cmap=LinearSegmentedColormap.from_list("user_seq",[_lighten(P[0],.88),P[0]]),origin="lower",aspect="auto",interpolation="nearest"); ax2.set(xlabel="时刻 j",ylabel="时刻 i",title="Recurrence plot"); ax2.grid(False)
    save(fig,"recurrence_plot_demo")


def phase_portrait():
    dt=.025; n=900; x=np.zeros(n); y=np.zeros(n); x[0]=1.5; y[0]=0
    for i in range(n-1):
        mu=1.2; x[i+1]=x[i]+dt*y[i]; y[i+1]=y[i]+dt*((1-x[i]**2)*mu*y[i]-x[i])
    fig, ax=plt.subplots(figsize=(5.8,5.0)); sc=ax.scatter(x,y,c=np.arange(n),cmap=LinearSegmentedColormap.from_list("user_path",[P[1],P[0]]),s=8,alpha=.72); ax.plot(x,y,color=INK,lw=.45,alpha=.5); ax.scatter(x[0],y[0],s=80,color=HI,marker="s",label="初始状态"); ax.scatter(x[-1],y[-1],s=90,color=P[2],marker="*",label="末状态"); ax.set(xlabel="状态变量 x",ylabel="状态变量 y",title="Phase portrait：动态轨迹与吸引环"); clean(ax); ax.legend(frameon=False); save(fig,"phase_portrait_demo")


def calibration_belt():
    p=np.linspace(.05,.95,10); obs=np.array([.08,.12,.20,.25,.31,.43,.50,.67,.78,.90]); n=np.array([80,90,110,120,130,140,120,100,80,60]); se=np.sqrt(np.maximum(obs*(1-obs),.002)/n); fig,ax=plt.subplots(figsize=(6.8,4.3)); ax.fill_between(p,obs-1.96*se,obs+1.96*se,color=_lighten(P[0],.55),alpha=.9,label="95%校准带"); ax.plot(p,obs,"o-",color=P[0],lw=2,label="观测频率"); ax.plot([0,1],[0,1],ls="--",color=INK,lw=1,label="理想校准"); ax.scatter(p,n/np.max(n)*.16,s=20+n/3,color=P[1],alpha=.65,label="分箱样本量"); ax.set(xlabel="预测概率",ylabel="实际发生率",title="Calibration belt：预测概率的校准关系"); clean(ax); ax.legend(frameon=False,loc="best"); save(fig,"calibration_belt_demo")


def lorenz_curve():
    vals=np.array([2,3,3,4,5,6,8,10,16,24,35],float); vals.sort(); cum=np.r_[0,np.cumsum(vals)/vals.sum()]; pop=np.linspace(0,1,len(cum)); g=1-2*np.trapezoid(cum,pop); fig,ax=plt.subplots(figsize=(5.8,4.8)); ax.fill_between(pop,cum,pop,color=_lighten(P[0],.65),alpha=.9); ax.plot(pop,cum,color=P[0],lw=2.2,label="资源累计曲线"); ax.plot([0,1],[0,1],ls="--",color=INK,lw=1,label="完全均衡"); ax.text(.60,.20,f"Gini={g:.2f}",fontsize=10,color=HI,fontweight="bold"); ax.set(xlabel="策略/阶段累计占比",ylabel="资源累计占比",title="Lorenz curve：资源集中度"); clean(ax); ax.legend(frameon=False); save(fig,"lorenz_concentration_demo")


def dominance_map():
    pts=np.array([[.20,.82],[.28,.72],[.34,.66],[.44,.55],[.53,.48],[.61,.40],[.72,.29],[.80,.22],[.42,.79],[.68,.57]])
    feasible=np.array([1,1,1,1,1,1,1,1,0,0],bool); nd=[]
    for i,p in enumerate(pts):
        if not feasible[i]: continue
        dominated=False
        for j,q in enumerate(pts):
            if i!=j and feasible[j] and q[0]<=p[0] and q[1]>=p[1] and (q[0]<p[0] or q[1]>p[1]): dominated=True; break
        if not dominated: nd.append(i)
    fig,ax=plt.subplots(figsize=(6.8,4.7)); ax.scatter(pts[~feasible,0],pts[~feasible,1],s=45,color=COLORS.get("neutral", "#999999"),marker="x",label="不可行"); ax.scatter(pts[feasible,0],pts[feasible,1],s=48,color=P[2],alpha=.55,label="可行候选"); ax.plot(pts[nd,0],pts[nd,1],color=P[0],lw=2.1,label="非支配前沿"); ax.scatter(pts[nd,0],pts[nd,1],s=110,color=HI,edgecolor="white",lw=1.0,zorder=4,label="Pareto候选"); ax.scatter([pts[nd[len(nd)//2],0]],[pts[nd[len(nd)//2],1]],s=160,marker="*",color=P[1],edgecolor="white",label="膝点"); ax.set(xlabel="资源消耗（越低越好）",ylabel="获胜概率（越高越好）",title="Dominance map：可行性、支配关系与膝点"); clean(ax); ax.legend(frameon=False,loc="best"); save(fig,"dominance_map_demo")


def event_strip():
    events=[(8,"第1局开始","局"),(94,"战术暂停","暂停"),(128,"局间换电","资源"),(260,"第2局开始","局"),(352,"紧急维修","故障"),(438,"第3局开始","局")]
    fig,ax=plt.subplots(figsize=(8.2,3.2)); ax.axhline(0,color=GRID,lw=1)
    for i,(t,name,typ) in enumerate(events):
        c=P[i%len(P)]; ax.scatter(t,0,s=100,color=c,edgecolor="white",lw=1.2,zorder=3); ax.vlines(t,0,.45 if i%2==0 else -.45,color=c,lw=1.2); ax.text(t,.52 if i%2==0 else -.55,name,ha="center",va="bottom" if i%2==0 else "top",fontsize=8,rotation=0)
    ax.set(xlim=(0,480),ylim=(-.85,.85),xlabel="比赛时间（s）",yticks=[],title="Strategy event strip：策略与资源事件时间轴"); ax.grid(False); ax.spines[:].set_visible(False); save(fig,"strategy_event_strip_demo")


def bivariate_legend_map():
    fig,ax=plt.subplots(figsize=(5.6,5.0)); base=np.array([[0,1,2],[1,2,2],[0,1,2]])
    cmap=LinearSegmentedColormap.from_list("bivar",[_lighten(P[0],.72),_lighten(P[1],.55),P[0],P[1],HI],N=9)
    for i in range(3):
        for j in range(3):
            idx=int(base[i,j]*3+i); ax.add_patch(Rectangle((j,i),1,1,facecolor=cmap(idx/8),edgecolor="white",lw=2)); ax.text(j+.5,i+.5,f"{i+1},{j+1}",ha="center",va="center",fontsize=8)
    ax.set(xticks=[.5,1.5,2.5],xticklabels=["低成本","中成本","高成本"],yticks=[.5,1.5,2.5],yticklabels=["低风险","中风险","高风险"],xlabel="变量 B：资源压力",ylabel="变量 A：故障风险",title="Bivariate legend map：两个变量的联合等级"); ax.set_xlim(0,3); ax.set_ylim(0,3); ax.invert_yaxis(); ax.grid(False); ax.spines[:].set_visible(False); save(fig,"bivariate_legend_map_demo")


def sankey_uncertainty():
    left=[("输入",.65), ("约束",.35)]; right=[("可行",.58),("边界",.25),("失败",.17)]; fig,ax=plt.subplots(figsize=(7.8,4.0)); ax.set_xlim(0,1); ax.set_ylim(0,1); ax.axis("off")
    ysL=[.68,.32]; ysR=[.70,.48,.22]
    for i,(n,w) in enumerate(left): ax.add_patch(Rectangle((.05,ysL[i]-.08),.12,.16,facecolor=_lighten(P[i],.35),edgecolor=P[i],lw=1.2)); ax.text(.11,ysL[i],n,ha="center",va="center",fontsize=9)
    for i,(n,w) in enumerate(right): ax.add_patch(Rectangle((.83,ysR[i]-.07),.12,.14,facecolor=_lighten(P[i+2],.35),edgecolor=P[i+2],lw=1.2)); ax.text(.89,ysR[i],n,ha="center",va="center",fontsize=9)
    flows=[(0,0,.42,.04),(0,1,.16,.025),(0,2,.07,.018),(1,0,.16,.025),(1,1,.09,.02),(1,2,.10,.022)]
    for k,(i,j,w,u) in enumerate(flows):
        p=bezier((.17,ysL[i]),(.83,ysR[j]),.18); ax.add_patch(PathPatch(p,fill=False,color=P[i],lw=2+16*w,alpha=.34)); ax.add_patch(PathPatch(p,fill=False,color=HI,lw=1.1+7*u,alpha=.55,linestyle="--"))
    ax.text(.5,.06,"实线：中心流量　虚线：不确定性带（演示）",ha="center",fontsize=8,color=INK); save(fig,"sankey_uncertainty_demo")


def pareto_glyph():
    names=["候选A","候选B","候选C","候选D"]; cats=["胜率","稳定性","资源效率","公平性","恢复力"]; vals=np.array([[.86,.62,.72,.50,.78],[.74,.86,.55,.80,.65],[.81,.70,.90,.58,.72],[.67,.92,.62,.74,.88]])
    th=np.linspace(0,2*np.pi,len(cats),endpoint=False); th=np.r_[th,th[0]]; fig,ax=plt.subplots(figsize=(7.0,5.4),subplot_kw={"polar":True})
    for i,row in enumerate(vals): ax.plot(th,np.r_[row,row[0]],color=P[i],lw=1.8,label=names[i]); ax.fill(th,np.r_[row,row[0]],color=P[i],alpha=.10)
    ax.set_xticks(th[:-1],cats); ax.set_ylim(0,1); ax.set_title("Pareto glyph / star glyph：少量候选的多指标结构",pad=18); ax.legend(frameon=False,bbox_to_anchor=(1.22,1.08),loc="upper left"); save(fig,"pareto_glyph_demo")


if __name__ == "__main__":
    funcs=[ecdf_threshold,quantile_dot,beeswarm,ridgeline,horizon,parallel_sets,mosaic_association,arc_diagram,hive_plot,recurrence_plot,phase_portrait,calibration_belt,lorenz_curve,dominance_map,event_strip,bivariate_legend_map,sankey_uncertainty,pareto_glyph]
    for fn in funcs:
        fn()
    print(f"generated {len(funcs)} niche demo figures in {OUT}")

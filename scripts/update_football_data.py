import json, os, math, requests
from pathlib import Path
from datetime import datetime, timedelta, timezone
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data"/"drawhunter-data.json"
CFG=json.loads((ROOT/"config"/"competitions.json").read_text(encoding="utf-8"))
API_KEY=os.getenv("API_FOOTBALL_KEY") or os.getenv("API_SPORTS_KEY") or ""
API_HOST=os.getenv("API_FOOTBALL_HOST") or "v3.football.api-sports.io"
BASE=f"https://{API_HOST}"

def headers():
    if not API_KEY: raise RuntimeError("API_FOOTBALL_KEY manquante")
    return {"x-apisports-key":API_KEY,"x-rapidapi-host":API_HOST}
def get(path, params):
    r=requests.get(BASE+path,headers=headers(),params=params,timeout=30); r.raise_for_status()
    payload=r.json()
    if payload.get("errors"): print("API errors:",payload["errors"])
    return payload.get("response",[])
def season_year(now): return now.year if now.month>=7 else now.year-1
def avg(x,d=0): return sum(x)/len(x) if x else d
def fact(n):
    r=1
    for i in range(2,n+1): r*=i
    return r
def pois(l,k): return math.exp(-l)*l**k/fact(k)
def poisson_probs(lh,la):
    ph=pd=pa=0
    for h in range(11):
        for a in range(11):
            p=pois(lh,h)*pois(la,a)
            if h>a: ph+=p
            elif h==a: pd+=p
            else: pa+=p
    return {"home":ph,"draw":pd,"away":pa,"oneX":ph+pd,"xTwo":pd+pa,"twelve":ph+pa}
def parse_finished(fixtures):
    rows=[]
    for f in fixtures:
        g=f.get("goals",{})
        hg,ag=g.get("home"),g.get("away")
        if isinstance(hg,int) and isinstance(ag,int):
            rows.append({"home":f["teams"]["home"]["name"],"away":f["teams"]["away"]["name"],"hg":hg,"ag":ag,"date":f["fixture"]["date"][:10]})
    return rows
def team_stats(games):
    st={}
    for g in games:
        for t in [g["home"],g["away"]]:
            st.setdefault(t,{"gf_h":[],"ga_h":[],"gf_a":[],"ga_a":[],"draws":[],"recent_gf":[],"recent_ga":[],"matches":0})
        st[g["home"]]["gf_h"].append(g["hg"]); st[g["home"]]["ga_h"].append(g["ag"]); st[g["home"]]["draws"].append(1 if g["hg"]==g["ag"] else 0); st[g["home"]]["recent_gf"].append(g["hg"]); st[g["home"]]["recent_ga"].append(g["ag"]); st[g["home"]]["matches"]+=1
        st[g["away"]]["gf_a"].append(g["ag"]); st[g["away"]]["ga_a"].append(g["hg"]); st[g["away"]]["draws"].append(1 if g["hg"]==g["ag"] else 0); st[g["away"]]["recent_gf"].append(g["ag"]); st[g["away"]]["recent_ga"].append(g["hg"]); st[g["away"]]["matches"]+=1
    out={}
    for t,v in st.items():
        out[t]={"gf_h":avg(v["gf_h"],1.25),"ga_h":avg(v["ga_h"],1.2),"gf_a":avg(v["gf_a"],1.1),"ga_a":avg(v["ga_a"],1.35),"draw_rate":avg(v["draws"],.26),"recent_gf":avg(v["recent_gf"][-5:],avg(v["recent_gf"],1.2)),"recent_ga":avg(v["recent_ga"][-5:],avg(v["recent_ga"],1.2)),"matches":v["matches"]}
    return out
def compute(home,away,stats,league_avg):
    h=stats.get(home,{}); a=stats.get(away,{})
    lh=((h.get("gf_h",league_avg)*.35)+(a.get("ga_a",league_avg)*.30)+(h.get("recent_gf",league_avg)*.15)+(a.get("recent_ga",league_avg)*.10)+(league_avg*.10))
    la=((a.get("gf_a",league_avg)*.35)+(h.get("ga_h",league_avg)*.30)+(a.get("recent_gf",league_avg)*.15)+(h.get("recent_ga",league_avg)*.10)+(league_avg*.10))
    lh=max(.15, min(3.5, lh)); la=max(.15, min(3.5, la))
    p=poisson_probs(lh,la)
    balance=max(0,1-min(abs(lh-la)/1.25,1))*30
    low=max(0,1-min(((lh+la)-1.8)/2.2,1))*15
    drawp=max(0,min((p["draw"]-.21)/.13,1))*35
    hist=max(0,min(((h.get("draw_rate",.25)+a.get("draw_rate",.25))/2-.18)/.20,1))*20
    idx=round(drawp+balance+low+hist)
    dc_opts=[("1X",p["oneX"]),("X2",p["xTwo"]),("12",p["twelve"])]
    dc_orientation=max(dc_opts,key=lambda x:x[1])[0]
    dc_index=round(max(x[1] for x in dc_opts)*70 + min(abs(lh-la)/1.4,1)*30)
    explain=[]
    if abs(lh-la)<.35: explain.append("Forces offensives attendues proches")
    if lh+la<2.45: explain.append("Total de buts attendu plutôt faible")
    if ((h.get("draw_rate",.25)+a.get("draw_rate",.25))/2)>.27: explain.append("Historique récent favorable aux nuls")
    if p["draw"]>.28: explain.append("Probabilité de nul modèle supérieure à la moyenne")
    return lh,la,p,idx,dc_index,dc_orientation,explain
def main():
    now=datetime.now(timezone.utc); sy=season_year(now); upcoming_days=int(CFG.get("upcoming_days",7))
    start=(now.date()).isoformat(); end=(now.date()+timedelta(days=upcoming_days)).isoformat()
    matches=[]
    for lname,lid in CFG["leagues"].items():
        all_finished=[]
        for s in range(sy-int(CFG.get("history_seasons_back",2))+1, sy+1):
            try: all_finished += parse_finished(get("/fixtures",{"league":lid,"season":s}))
            except Exception as e: print("history warning",lname,s,e)
        stats=team_stats(all_finished)
        league_avg=avg([g["hg"] for g in all_finished]+[g["ag"] for g in all_finished],1.25)
        fixtures=get("/fixtures",{"league":lid,"season":sy,"from":start,"to":end})
        for f in fixtures:
            home=f["teams"]["home"]["name"]; away=f["teams"]["away"]["name"]
            lh,la,p,idx,dc_idx,dc_or,explain=compute(home,away,stats,league_avg)
            matches.append({"date":f["fixture"]["date"][:10],"kickoff":f["fixture"]["date"],"league":lname,"home":home,"away":away,"lambda_home":round(lh,4),"lambda_away":round(la,4),"model":p,"indexes":{"draw_index":idx,"dc_index":dc_idx,"dc_orientation":dc_or},"explain":explain,"source_fixture_id":f["fixture"]["id"]})
    OUT.write_text(json.dumps({"generated_at":now.isoformat(),"from":start,"to":end,"source":"api-football","matches":matches},ensure_ascii=False,indent=2),encoding="utf-8")
    print("wrote",len(matches),"matches")
if __name__=="__main__": main()

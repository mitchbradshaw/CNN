import json,sys
from pen_kit import CHAR_W, SANS, MONO
f=sys.argv[1]
d=json.load(open(f))
ids=set(); dup=[]; types=set(); overflow=[]; wide=[]
def walk(n,px,py,pw,ph,path):
    i=n.get("id")
    if i in ids: dup.append(i)
    ids.add(i)
    t=n.get("type"); types.add(t)
    x=n.get("x",0); y=n.get("y",0)
    w=n.get("width",0); h=n.get("height",0)
    nm=n.get("name") or t
    if pw is not None:
        if x< -0.5 or y< -0.5 or (w and x+w>pw+0.5) or (h and y+h>ph+0.5):
            overflow.append((path+"/"+str(nm), round(x,1),round(y,1),round(w,1),round(h,1),pw,ph))
    if t=="text":
        fam=n.get("fontFamily",SANS); fs=n.get("fontSize",12)
        est=len(n.get("content",""))*fs*CHAR_W.get(fam,0.52)
        if pw and est> pw-x+0.5:
            wide.append((path+"/"+str(nm), round(est), round(pw-x)))
    for c in n.get("children",[]) or []:
        walk(c,x,y,w,h,path+"/"+str(nm))
for s in d["children"]:
    walk(s,0,0,None,None,"")
import os
print("file    :",f, round(os.path.getsize(f)/1e6,3),"MB")
print("nodes   :",len(ids))
print("dup ids :",dup[:5], len(dup))
print("types   :",sorted(types))
print("overflow:",len(overflow))
for o in overflow[:15]: print("   ",o)
print("wide txt:",len(wide))
for o in wide[:15]: print("   ",o)

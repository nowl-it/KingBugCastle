#!/usr/bin/env python3
"""Doi method RestAPI UniTask<Resp> X(params){return default;} -> void X(params, Action<Resp> onDone){Web...}"""
import re
CS='/home/nowl/Code/kgc/unity/kgc-rebuild/ExportedProject/Assets/Scripts/Assembly-CSharp/Awesomepiece/RestAPI.cs'
src=open(CS,errors='replace').read()
end={}
for line in open('/home/nowl/Code/kgc/docs/restapi-endpoints.txt'):
    if line.startswith('#'): continue
    p,v,mo,u=line.rstrip('\n').split('\t')
    if u=='?' or v=='?': continue
    end.setdefault(p,(v,u))

pat=re.compile(r'public static UniTask<(\w+)>\s+(\w+)\s*\(([^)]*)\)\s*\{\s*return default;\s*\}')
done=0
def repl(m):
    global done
    resp,name,params=m.group(1),m.group(2),m.group(3)
    if name not in end: return m.group(0)
    verb,uri=end[name]
    ps=[p.strip() for p in re.split(r',(?![^<]*>)',params) if p.strip()]
    ps=[p.split('=')[0].strip() for p in ps]
    pnames=[p.rsplit(' ',1)[-1] for p in ps]
    json='"{}"'
    for t,n in ((p.rsplit(' ',1)[0],p.rsplit(' ',1)[1]) for p in ps):
        if 'Model' in t or 'Request' in t:
            json=f'JsonUtility.ToJson({n})'; break
    uri_expr=f'"{uri}"'
    if '{' in uri and pnames:
        uri_expr=f'string.Format("{uri}", {", ".join(pnames)})'
    call='Web.Get' if verb=='Get' else 'Web.Post'
    args=f'{uri_expr}, accessToken, false, onDone' if verb=='Get' else f'{uri_expr}, {json}, accessToken, false, onDone'
    done+=1
    return f'public static void {name}({", ".join(ps+[f"Action<{resp}> onDone"])})\n\t\t{{\n\t\t\t{call}<{resp}>({args});\n\t\t}}'

out=pat.sub(repl,src)
open(CS,'w').write(out)
print('converted',done)

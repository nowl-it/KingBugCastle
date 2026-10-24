#!/usr/bin/env python3
"""Sinh overload callback cho RestAPI tu bang docs/restapi-endpoints.txt."""
import re, sys

CS = '/home/nowl/Code/kgc/unity/kgc-rebuild/ExportedProject/Assets/Scripts/Assembly-CSharp/Awesomepiece/RestAPI.cs'
src = open(CS, errors='replace').read()

# --- 1. bang endpoint ---
end = {}
for line in open('/home/nowl/Code/kgc/docs/restapi-endpoints.txt'):
    if line.startswith('#'):
        continue
    p, v, mo, u = line.rstrip('\n').split('\t')
    if u == '?' or v == '?':
        continue
    end.setdefault(p, (v, u))

# --- 2. khai bao hien co ---
decl_re = re.compile(r'public static (?:UniTask<(\w+)>|void)\s+(\w+)\s*\(([^)]*)\)')
existing = {}   # name -> list of (resp, params)
for m in decl_re.finditer(src):
    resp, name, params = m.group(1), m.group(2), m.group(3)
    existing.setdefault(name, []).append((resp, params))


def split_params(p):
    out, depth, cur = [], 0, ''
    for ch in p:
        if ch in '<([{':
            depth += 1
        elif ch in '>)]}':
            depth -= 1
        if ch == ',' and depth == 0:
            out.append(cur.strip()); cur = ''
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def already_cb(name, nparams):
    for resp, params in existing.get(name, []):
        ps = split_params(params)
        if len(ps) == nparams + 1 and ps[-1].startswith('Action<'):
            return True
    return False


gen = []
skipped_nosig = skipped_exists = 0
for name, (verb, uri) in sorted(end.items()):
    cands = [(r, p) for r, p in existing.get(name, []) if r and not p.count('Action<')]
    if not cands:
        skipped_nosig += 1
        continue
    # uu tien overload it tham so nhat (thuong la ban that)
    resp, params = min(cands, key=lambda x: len(split_params(x[1])))
    ps = split_params(params)
    if already_cb(name, len(ps)):
        skipped_exists += 1
        continue
    ptypes = [p.rsplit(' ', 1)[0].strip() for p in ps]
    pnames = [p.rsplit(' ', 1)[1].strip() for p in ps]
    json = '"{}"'
    for t, n in zip(ptypes, pnames):
        if 'Model' in t or 'Request' in t:
            json = f'JsonUtility.ToJson({n})'
            break
    uri_expr = f'"{uri}"'
    if '{' in uri and pnames:
        args = ', '.join(pnames)
        uri_expr = f'string.Format("{uri}", {args})'
    call = ('Web.Get' if verb == 'Get' else 'Web.Post')
    if verb == 'Get':
        args = f'{uri_expr}, accessToken, false, onDone'
    else:
        args = f'{uri_expr}, {json}, accessToken, false, onDone'
    ps = [p.split('=')[0].strip() for p in ps]
    sig = f'public static void {name}({", ".join(ps + [f"Action<{resp}> onDone"])})\n\t\t{{\n\t\t\t{call}<{resp}>({args});\n\t\t}}\n'
    gen.append(sig)

# --- 3. chen truoc } cuoi cua class ---
i1 = src.rfind('}')                     # namespace
idx = src.rfind('}', 0, i1)             # class
body = '\n\t\t// ==== generated callback overloads ====\n' + '\n'.join(gen)
out = src[:idx] + body + '\n\t' + src[idx:]
open(CS, 'w').write(out)
print(f'gen={len(gen)} skip_nosig={skipped_nosig} skip_exists={skipped_exists}')

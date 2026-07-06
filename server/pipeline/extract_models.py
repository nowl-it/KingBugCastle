#!/usr/bin/env python3
"""Parse Il2CppDumper dump.cs -> JSON registry of Awesomepiece.Model classes.

Output: generated/models.json   { ClassName: {base, fields:[{name,ctype,jtype}], ns} }
Also:   generated/restapi.json   { MethodName: {request, response} } from RestAPI declarations.

il2cpp method bodies are empty in dump.cs, but class field layouts and method
signatures are complete -> enough to reconstruct exact JSON wire shapes.
"""
import json, re, sys, pathlib

DUMP = sys.argv[1] if len(sys.argv) > 1 else "/home/nowl/Code/kgc/il2cpp/v169.1.05/dump.cs"
OUT = pathlib.Path(__file__).parent.parent / "generated"

src = pathlib.Path(DUMP).read_text(errors="replace")
lines = src.splitlines()

# C# type -> JSON/python default mapping
def jtype(ct):
    ct = ct.strip()
    if ct.endswith("[]") or ct.startswith("List<") or ct.startswith("Dictionary<") or ct.endswith(">"):
        if ct.startswith("Dictionary<"):
            return "object", {}
        return "array", []
    if ct in ("int", "long", "short", "byte", "uint", "ulong"):
        return "int", 0
    if ct in ("float", "double", "decimal"):
        return "number", 0
    if ct == "bool":
        return "bool", False
    if ct == "string":
        return "string", None
    return "object", None  # nested model / enum / DateTime

# --- pass 1: all classes with namespace + base + serializable fields ---
classes = {}
cur_ns = None
i = 0
field_re = re.compile(r"^\s*public\s+([A-Za-z0-9_.<>,\[\]\? ]+?)\s+([A-Za-z0-9_]+);\s*//\s*0x")
class_re = re.compile(r"^(?:public |internal |private )?(?:sealed )?(?:abstract )?class ([A-Za-z0-9_]+)(?:\s*:\s*([A-Za-z0-9_,. <>]+))?\s*//\s*TypeDefIndex")
ns_re = re.compile(r"^// Namespace: (.+)$")

while i < len(lines):
    ln = lines[i]
    m = ns_re.match(ln)
    if m:
        cur_ns = m.group(1).strip()
        i += 1
        continue
    cm = class_re.match(ln)
    if cm:
        name = cm.group(1)
        bases = (cm.group(2) or "").strip()
        base = bases.split(",")[0].strip() if bases else None
        # collect fields until closing brace of class (track depth)
        fields = []
        depth = 0
        j = i
        started = False
        while j < len(lines):
            l2 = lines[j]
            depth += l2.count("{") - l2.count("}")
            if "{" in l2:
                started = True
            fm = field_re.match(l2)
            if fm and "const" not in l2 and "static" not in l2:
                ct = fm.group(1).strip()
                fname = fm.group(2)
                jt, default = jtype(ct)
                fields.append({"name": fname, "ctype": ct, "jtype": jt, "default": default})
            if started and depth <= 0:
                break
            j += 1
        classes[name] = {"ns": cur_ns, "base": base, "fields": fields}
        i = j + 1
        continue
    i += 1

# resolve inherited fields for Model classes (flatten base chain)
def all_fields(name, seen=None):
    seen = seen or set()
    if name in seen or name not in classes:
        return []
    seen.add(name)
    c = classes[name]
    base_fields = all_fields(c["base"], seen) if c["base"] else []
    return base_fields + c["fields"]

models = {}
for name, c in classes.items():
    if (c["ns"] or "").startswith("Awesomepiece.Model") or name.endswith("RequestModel") or name.endswith("ResponseModel"):
        # client-only fields not serialized to wire
        skip = {"www", "errorHandled"}
        flat = [f for f in all_fields(name) if f["name"] not in skip]
        models[name] = {"ns": c["ns"], "base": c["base"], "fields": flat}

# --- pass 2: RestAPI method -> (request model, response model) ---
restapi = {}
m = re.search(r"public class RestAPI\b", src)
if m:
    block = src[m.start():]
    end = block.find("\n}\n")
    block = block[: end if end > 0 else 200000]
    for mm in re.finditer(r"public static UniTask<([A-Za-z0-9_]+)>\s+([A-Za-z0-9_]+)\(([^)]*)\)", block):
        resp, meth, args = mm.group(1), mm.group(2), mm.group(3)
        req = None
        am = re.search(r"([A-Za-z0-9_]+RequestModel)\s+\w+", args)
        if am:
            req = am.group(1)
        restapi[meth] = {"request": req, "response": resp, "args": args.strip()}

OUT.mkdir(exist_ok=True)
(OUT / "models.json").write_text(json.dumps(models, indent=1))
(OUT / "restapi.json").write_text(json.dumps(restapi, indent=1))
print(f"models: {len(models)}  restapi methods: {len(restapi)}")
print("sample AuthResponseModel:", json.dumps(models.get("AuthResponseModel"), indent=1))

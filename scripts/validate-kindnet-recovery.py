#!/usr/bin/env python3
"""Validate immutable kindnet recovery identities without broad selectors or retries."""
import argparse, hashlib, json, os, pathlib

def load(path): return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
def pods(value): return sorted(value.get("items", value) if isinstance(value, dict) else value, key=lambda x: x["spec"]["nodeName"])
def identity(ds, items, image):
    assert ds["metadata"]["name"] == "kindnet" and ds["metadata"]["namespace"] == "kube-system"
    assert ds["spec"]["selector"]["matchLabels"] == {"k8s-app": "kindnet"}
    assert ds["spec"]["template"]["spec"]["containers"][0]["image"] == image
    assert ds["status"]["desiredNumberScheduled"] == 3 and len(items) == 3
    result={"schemaVersion":1,"daemonSet":{"uid":ds["metadata"]["uid"],"generation":ds["metadata"]["generation"],"image":image},
      "pods":[{"name":p["metadata"]["name"],"uid":p["metadata"]["uid"],"node":p["spec"]["nodeName"]} for p in pods(items)]}
    assert len({p["node"] for p in result["pods"]}) == 3
    return result
def main():
    p=argparse.ArgumentParser(); s=p.add_subparsers(dest="cmd",required=True)
    q=s.add_parser("preflight"); q.add_argument("--daemonset"); q.add_argument("--pods"); q.add_argument("--image"); q.add_argument("--output")
    q=s.add_parser("confirmation"); q.add_argument("--identity"); q.add_argument("--context")
    q=s.add_parser("plan"); q.add_argument("--identity")
    q=s.add_parser("unchanged"); q.add_argument("--identity"); q.add_argument("--daemonset"); q.add_argument("--pod"); q.add_argument("--node"); q.add_argument("--uid")
    q=s.add_parser("replacement"); q.add_argument("--pods"); q.add_argument("--node"); q.add_argument("--old-name"); q.add_argument("--old-uid"); q.add_argument("--image")
    q=s.add_parser("manifest"); q.add_argument("--root")
    a=p.parse_args()
    if a.cmd=="preflight":
      value=identity(load(a.daemonset),load(a.pods)["items"],a.image); pathlib.Path(a.output).write_text(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n"); return
    value=load(a.identity) if hasattr(a,"identity") else None
    if a.cmd=="confirmation": print(a.context+"/kindnet/"+value["daemonSet"]["uid"]+"/"+",".join(x["uid"] for x in value["pods"])); return
    if a.cmd=="plan":
      for x in value["pods"]: print("|".join((x["node"],x["name"],x["uid"])))
      return
    if a.cmd=="unchanged":
      ds=load(a.daemonset); pod=load(a.pod); assert ds["metadata"]["uid"]==value["daemonSet"]["uid"] and ds["metadata"]["generation"]==value["daemonSet"]["generation"]
      assert pod["metadata"]["uid"]==a.uid and pod["spec"]["nodeName"]==a.node; return
    if a.cmd=="replacement":
      items=pods(load(a.pods)); assert len(items)==1; pod=items[0]; assert pod["spec"]["nodeName"]==a.node and pod["metadata"]["uid"]!=a.old_uid and pod["metadata"]["name"]!=a.old_name
      assert pod["spec"]["containers"][0]["image"]==a.image; return
    root=pathlib.Path(a.root); files={}
    for path in sorted(root.rglob("*")):
      if path.name=="evidence-manifest.json": continue
      assert not path.is_symlink() and (path.is_dir() or path.is_file())
      if path.is_file(): files[str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
    tmp=root/".manifest.tmp"; tmp.write_text(json.dumps({"schemaVersion":1,"files":files},sort_keys=True,separators=(",",":"))+"\n"); os.replace(tmp,root/"evidence-manifest.json")
if __name__=="__main__": main()

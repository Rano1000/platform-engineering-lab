#!/usr/bin/env python3
"""Fail closed when kindnet readiness and watcher health disagree."""
import argparse, hashlib, json, os, pathlib, re
ERRORS=re.compile(r"Failed to watch|failed to list|TLS handshake timeout|i/o timeout|Could not receive message",re.I)
def main():
 p=argparse.ArgumentParser(); s=p.add_subparsers(dest="cmd",required=True)
 q=s.add_parser("preflight"); q.add_argument("--daemonset"); q.add_argument("--pods"); q.add_argument("--logs")
 q=s.add_parser("dns-manifest"); q.add_argument("--root"); q.add_argument("--name"); q.add_argument("--node"); q.add_argument("--uid")
 q=s.add_parser("evidence"); q.add_argument("--root")
 a=p.parse_args()
 if a.cmd=="preflight":
  ds=json.load(open(a.daemonset)); pods=json.load(open(a.pods))["items"]
  assert ds["status"]["desiredNumberScheduled"]==ds["status"]["numberReady"]==3
  assert len(pods)==3 and len({x["spec"]["nodeName"] for x in pods})==3
  for pod in pods:
   assert pod["status"]["phase"]=="Running" and pod["status"]["containerStatuses"][0]["ready"] is True
  logs=pathlib.Path(a.logs).read_text(encoding="utf-8",errors="replace")
  if ERRORS.search(logs): raise SystemExit("kindnet watcher/API errors exist in the bounded preflight window")
  return
 if a.cmd=="dns-manifest":
  root=pathlib.Path(a.root); kinds={"created":"created.json","log":"pod.log","pod":"pod.json","describe":"describe.txt","events":"events.json","cleanup":"cleanup.json"}
  files={kind:f"{a.name}.{suffix}" for kind,suffix in kinds.items()}
  assert all((root/name).is_file() and (root/name).stat().st_size>0 for name in files.values())
  value={"schemaVersion":1,"name":a.name,"namespace":"gitops","node":a.node,"uid":a.uid,"files":files}
  tmp=root/f".{a.name}.artifacts.tmp"; tmp.write_text(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n"); os.replace(tmp,root/f"{a.name}.artifacts.json")
  return
 root=pathlib.Path(a.root); assert root.is_absolute() and root.is_dir() and not root.is_symlink()
 for index in (0,1):
  worker=root/f"worker-{index}"; assert (worker/"evidence-manifest.json").is_file()
  manifests=list(root.glob(f"kindnet-dns-{index}-*.artifacts.json")); assert len(manifests)==1
  record=json.loads(manifests[0].read_text()); assert record["node"] and record["uid"]
  assert set(record["files"])=={"created","log","pod","describe","events","cleanup"}
  assert all((root/name).is_file() and (root/name).stat().st_size>0 for name in record["files"].values())
 files={}
 for path in sorted(root.rglob("*")):
  if path==root/"evidence-manifest.json": continue
  assert not path.is_symlink() and (path.is_dir() or path.is_file())
  if path.is_file(): files[str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
 tmp=root/".manifest.tmp"; tmp.write_text(json.dumps({"schemaVersion":1,"files":files},sort_keys=True,separators=(",",":"))+"\n"); os.replace(tmp,root/"evidence-manifest.json")
if __name__=="__main__": main()

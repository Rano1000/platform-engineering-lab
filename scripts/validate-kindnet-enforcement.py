#!/usr/bin/env python3
"""Fail closed on kindnet health and incomplete or unsafe enforcement evidence."""
import argparse, hashlib, json, os, pathlib, re

ERRORS=re.compile(r"Failed to watch|failed to list|TLS handshake timeout|i/o timeout|Could not receive message",re.I)
SAFE_CLEANUP={"deleted","already_absent","already_absent_after_race"}
ROOT_FILES={"daemonset.json","pods.json","kindnet.log","identity.json"}
WORKER_FILES={"endpoint-identity.json","endpointslices.json","node.json","networkpolicies.yaml"}
POD_FILES={"pod.json","pod.log","describe.txt","events.json"}
DNS_SUFFIXES={"created.json","pod.log","pod.json","describe.txt","events.json","cleanup.json","artifacts.json"}

def fail(message): raise ValueError(message)
def load(path): return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))

def validate_projection(path,kind):
 value=load(path)
 if value.get("schemaVersion")!=1 or value.get("projectionType")!=kind: fail(f"{path.name} is not a {kind} projection")
 if kind=="kindnet-pod-list" and (not isinstance(value.get("items"),list) or len(value["items"])!=3): fail("kindnet PodList projection must contain exactly three Pods")
 text=path.read_text(encoding="utf-8")
 for field in ('"env"','"envFrom"','"volumes"','"initContainers"','"ephemeralContainers"','"value"'):
  if field in text: fail(f"unsafe workload field {field} remains in {path.name}")

def reject_raw_kindnet(value,relative):
 if not isinstance(value,dict): return
 metadata=value.get("metadata",{}) if isinstance(value.get("metadata",{}),dict) else {}
 labels=metadata.get("labels",{}) if isinstance(metadata.get("labels",{}),dict) else {}
 items=value.get("items",[]) if isinstance(value.get("items",[]),list) else []
 item=any(isinstance(x,dict) and x.get("metadata",{}).get("labels",{}).get("app")=="kindnet" for x in items)
 if (value.get("kind") in {"DaemonSet","Pod"} and (metadata.get("name")=="kindnet" or labels.get("app")=="kindnet")) or item:
  fail(f"unprojected kindnet workload object found at {relative}")

def validate_cleanup(path):
 value=load(path)
 if value.get("success") is not True or value.get("cleanupResult") not in SAFE_CLEANUP: fail(f"cleanup evidence is not successful: {path}")

def validate_worker(worker):
 if {p.name for p in worker.iterdir() if p.is_file()}!=WORKER_FILES: fail(f"worker files are incomplete or unexpected: {worker.name}")
 pods,cleanup=worker/"pods",worker/"cleanup"
 if not pods.is_dir() or not cleanup.is_dir(): fail(f"worker directories are missing: {worker.name}")
 pod_dirs=[p for p in pods.iterdir() if p.is_dir()]
 if len(pod_dirs)!=13 or any({p.name for p in d.iterdir()}!=POD_FILES for d in pod_dirs): fail(f"worker Pod diagnostics differ: {worker.name}")
 records=[p for p in cleanup.iterdir() if p.is_file()]
 if len(records)!=14 or any(p.suffix!=".json" for p in records): fail(f"worker cleanup records differ: {worker.name}")
 for path in records: validate_cleanup(path)
 return len(records)

def validate_dns(root):
 count=0
 for index in (0,1):
  manifests=list(root.glob(f"kindnet-dns-{index}-*.artifacts.json"))
  if len(manifests)!=1: fail(f"worker {index} DNS manifest is missing or ambiguous")
  record=load(manifests[0])
  if set(record.get("files",{}))!={"created","log","pod","describe","events","cleanup"}: fail("DNS artifact manifest is incomplete")
  prefix=manifests[0].name.removesuffix(".artifacts.json")
  if {p.name for p in root.glob(f"{prefix}.*")}!={f"{prefix}.{suffix}" for suffix in DNS_SUFFIXES}: fail("DNS evidence filenames differ")
  validate_cleanup(root/f"{prefix}.cleanup.json"); count+=1
 return count

def evidence(root,write_manifest=True):
 root=pathlib.Path(root)
 if not root.is_absolute() or not root.is_dir() or root.is_symlink(): fail("kindnet evidence root is unsafe")
 for path in root.rglob("*"):
  if path.is_symlink() or (not path.is_dir() and not path.is_file()): fail(f"unsafe evidence entry: {path}")
  if path.is_file() and path.stat().st_size==0: fail(f"empty evidence file: {path}")
 regular={p.name for p in root.iterdir() if p.is_file() and not p.name.startswith("kindnet-dns-")}
 if regular!=ROOT_FILES: fail("root evidence filenames are incomplete or unexpected")
 validate_projection(root/"daemonset.json","kindnet-daemonset")
 validate_projection(root/"pods.json","kindnet-pod-list")
 workers=[root/"worker-0",root/"worker-1"]
 if any(not worker.is_dir() for worker in workers): fail("both worker evidence trees are required")
 if sum(validate_worker(worker) for worker in workers)+validate_dns(root)!=30: fail("exactly thirty cleanup records are required")
 files={}
 for path in sorted(root.rglob("*")):
  if path.name=="evidence-manifest.json": continue
  if path.is_file():
   relative=str(path.relative_to(root))
   if path.suffix==".json": reject_raw_kindnet(load(path),relative)
   files[relative]=hashlib.sha256(path.read_bytes()).hexdigest()
 if len(files)!=158: fail(f"complete evidence must contain 158 files, found {len(files)}")
 if write_manifest:
  temporary=root/".manifest.tmp"
  temporary.write_text(json.dumps({"schemaVersion":1,"files":files},sort_keys=True,separators=(",",":"))+"\n")
  os.replace(temporary,root/"evidence-manifest.json")

def main():
 parser=argparse.ArgumentParser(); commands=parser.add_subparsers(dest="cmd",required=True)
 command=commands.add_parser("preflight"); command.add_argument("--daemonset"); command.add_argument("--pods"); command.add_argument("--logs")
 command=commands.add_parser("dns-manifest"); command.add_argument("--root"); command.add_argument("--name"); command.add_argument("--node"); command.add_argument("--uid")
 command=commands.add_parser("inventory"); command.add_argument("--root")
 command=commands.add_parser("evidence"); command.add_argument("--root"); args=parser.parse_args()
 try:
  if args.cmd=="preflight":
   daemonset,pods=load(args.daemonset),load(args.pods)["items"]
   if daemonset["status"]["desiredNumberScheduled"]!=daemonset["status"]["numberReady"] or len(pods)!=3: fail("kindnet readiness differs")
   if len({pod["spec"]["nodeName"] for pod in pods})!=3: fail("kindnet Pods are not distributed")
   if any(pod["status"]["phase"]!="Running" or pod["status"]["containerStatuses"][0]["ready"] is not True for pod in pods): fail("kindnet Pod is not Ready")
   if ERRORS.search(pathlib.Path(args.logs).read_text(encoding="utf-8",errors="replace")): fail("kindnet watcher/API errors exist")
  elif args.cmd=="dns-manifest":
   root=pathlib.Path(args.root); suffixes={"created":"created.json","log":"pod.log","pod":"pod.json","describe":"describe.txt","events":"events.json","cleanup":"cleanup.json"}
   files={kind:f"{args.name}.{suffix}" for kind,suffix in suffixes.items()}
   if not all((root/name).is_file() and (root/name).stat().st_size>0 for name in files.values()): fail("DNS diagnostics are incomplete")
   temporary=root/f".{args.name}.artifacts.tmp"; temporary.write_text(json.dumps({"schemaVersion":1,"name":args.name,"namespace":"gitops","node":args.node,"uid":args.uid,"files":files},sort_keys=True,separators=(",",":"))+"\n"); os.replace(temporary,root/f"{args.name}.artifacts.json")
  else: evidence(args.root,args.cmd=="evidence")
 except (AssertionError,KeyError,TypeError,ValueError,json.JSONDecodeError,OSError) as error: raise SystemExit(f"FAIL  {error}") from error
if __name__=="__main__": main()

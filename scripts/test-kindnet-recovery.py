#!/usr/bin/env python3
"""Offline regression coverage for guarded kindnet recovery and enforcement."""
import json, pathlib, subprocess, tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
VALIDATOR=ROOT/"scripts/validate-kindnet-recovery.py"
ENFORCEMENT=ROOT/"scripts/validate-kindnet-enforcement.py"
IMAGE="docker.io/kindest/kindnetd:v20251212-v0.29.0-alpha-105-g20ccfc88"
def fixture():
 ds={"metadata":{"name":"kindnet","namespace":"kube-system","uid":"ds-uid","generation":7},"spec":{"selector":{"matchLabels":{"k8s-app":"kindnet"}},"template":{"spec":{"containers":[{"image":IMAGE}]}}},"status":{"desiredNumberScheduled":3}}
 pods={"items":[{"metadata":{"name":f"kindnet-{n}","uid":f"uid-{n}"},"spec":{"nodeName":n,"containers":[{"image":IMAGE}]}} for n in ("control-plane","worker","worker2")]}
 return ds,pods
def run(*args,ok=True):
 value=subprocess.run(["python3",str(VALIDATOR),*args],text=True,capture_output=True)
 assert (value.returncode==0)==ok,(args,value.stderr); return value
def main():
 with tempfile.TemporaryDirectory() as directory:
  root=pathlib.Path(directory); ds,pods=fixture()
  (root/"ds.json").write_text(json.dumps(ds)); (root/"pods.json").write_text(json.dumps(pods))
  run("preflight","--daemonset",str(root/"ds.json"),"--pods",str(root/"pods.json"),"--image",IMAGE,"--output",str(root/"identity.json"))
  confirmation=run("confirmation","--identity",str(root/"identity.json"),"--context","kind-platform-engineering-lab").stdout.strip()
  assert confirmation=="kind-platform-engineering-lab/kindnet/ds-uid/uid-control-plane,uid-worker,uid-worker2"
  bad=json.loads(json.dumps(ds)); bad["metadata"]["generation"]=8; (root/"bad.json").write_text(json.dumps(bad))
  run("unchanged","--identity",str(root/"identity.json"),"--daemonset",str(root/"bad.json"),"--pod",str(root/"pods.json"),"--node","worker","--uid","uid-worker",ok=False)
  wrong=json.loads(json.dumps(ds)); wrong["spec"]["template"]["spec"]["containers"][0]["image"]="latest"; (root/"wrong.json").write_text(json.dumps(wrong))
  run("preflight","--daemonset",str(root/"wrong.json"),"--pods",str(root/"pods.json"),"--image",IMAGE,"--output",str(root/"x"),ok=False)
  ready_ds=json.loads(json.dumps(ds)); ready_ds["status"]["numberReady"]=3
  ready_pods=json.loads(json.dumps(pods))
  for pod in ready_pods["items"]:
   pod["status"]={"phase":"Running","containerStatuses":[{"ready":True}]}
  (root/"ready-ds.json").write_text(json.dumps(ready_ds)); (root/"ready-pods.json").write_text(json.dumps(ready_pods))
  (root/"clean.log").write_text("kindnet watcher healthy\n")
  value=subprocess.run(["python3",str(ENFORCEMENT),"preflight","--daemonset",str(root/"ready-ds.json"),"--pods",str(root/"ready-pods.json"),"--logs",str(root/"clean.log")],capture_output=True,text=True)
  assert value.returncode==0,value.stderr
  (root/"broken.log").write_text("Failed to watch *v1.Pod: i/o timeout\n")
  value=subprocess.run(["python3",str(ENFORCEMENT),"preflight","--daemonset",str(root/"ready-ds.json"),"--pods",str(root/"ready-pods.json"),"--logs",str(root/"broken.log")],capture_output=True,text=True)
  assert value.returncode!=0 and "watcher/API errors" in value.stderr
 content=(ROOT/"scripts/kindnet-policy-recover.sh").read_text()
 assert content.count('cleanup-kubernetes-resource.py" cleanup')==1
 assert "for IFS='|' read" not in content and "while IFS='|' read" in content
 assert content.index("cleanup-kubernetes-resource.py") < content.index("test-kindnet-policy.sh")
 assert content.index("describe pod") < content.index("cleanup-kubernetes-resource.py")
 assert "--force" not in content and "rollout restart" not in content
 enforcement=(ROOT/"scripts/validate-kindnet-enforcement.py").read_text()
 assert "Failed to watch" in enforcement and "i/o timeout" in enforcement
 assert 'for kpr_node' not in content  # The reviewed plan is consumed sequentially through one pipeline.
 assert content.count('cleanup-kubernetes-resource.py" cleanup')==1
 print("PASS  kindnet recovery rejects identity races, changed images, Ready-but-broken watchers, retries, and parallel restarts.")
if __name__=="__main__": main()

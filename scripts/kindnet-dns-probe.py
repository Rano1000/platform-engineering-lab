#!/usr/bin/env python3
"""Render and validate the bounded structured DNS assertion used by kindnet checks."""

import argparse
import json
import pathlib
import re
import tempfile

IMAGE = re.compile(r"(?:@sha256:[0-9a-f]{64}|:0\.1\.0-[0-9a-f]{12})$")
PROBE = r'''import json,socket,sys,time
started=time.monotonic(); result={"test":"dns","query":"kubernetes.default.svc","port":443}
try:
 address=socket.getaddrinfo(result["query"],result["port"])[0][4][0]
 result.update(observed="success",address=address,error_category="none",exit_code=0)
except socket.gaierror as error:
 result.update(observed="failure",error_category="dns_failure",error=str(error),exit_code=10)
except (socket.timeout,TimeoutError) as error:
 result.update(observed="failure",error_category="dns_timeout",error=str(error),exit_code=11)
except Exception as error:
 result.update(observed="failure",error_category="process_failure",error=type(error).__name__,exit_code=12)
result["duration_seconds"]=round(time.monotonic()-started,3); print(json.dumps(result,sort_keys=True)); sys.exit(result["exit_code"])
'''

def overrides(node, image):
    if not node or not IMAGE.search(image) or image.endswith(":latest"):
        raise ValueError("DNS probe node or immutable image identity is invalid")
    return {"spec":{"nodeName":node,"automountServiceAccountToken":False,"restartPolicy":"Never",
        "terminationGracePeriodSeconds":1,"securityContext":{"runAsNonRoot":True,"runAsUser":10001,
        "runAsGroup":10001,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"dns",
        "image":image,"imagePullPolicy":"IfNotPresent","command":["python","-c"],"args":[PROBE],
        "resources":{"requests":{"cpu":"5m","memory":"16Mi"},"limits":{"cpu":"25m","memory":"32Mi"}},
        "securityContext":{"allowPrivilegeEscalation":False,"readOnlyRootFilesystem":True,
        "capabilities":{"drop":["ALL"]}}}]}}

def validate(log_path, pod_path, node):
    lines=[line for line in pathlib.Path(log_path).read_text(encoding="utf-8").splitlines() if line]
    if len(lines)!=1: raise ValueError("DNS probe must emit exactly one structured result")
    result=json.loads(lines[0]); pod=json.loads(pathlib.Path(pod_path).read_text(encoding="utf-8"))
    state=pod.get("status",{}).get("containerStatuses",[{}])[0].get("state",{}).get("terminated",{})
    required={"test","query","port","observed","error_category","exit_code","duration_seconds"}
    if not required.issubset(result): raise ValueError("DNS probe result is incomplete")
    if pod.get("spec",{}).get("nodeName")!=node or state.get("exitCode")!=result.get("exit_code"):
        raise ValueError("DNS probe placement or process exit identity differs")
    if result.get("observed")!="success" or result.get("error_category")!="none" or result.get("exit_code")!=0:
        raise ValueError("DNS assertion failed: "+json.dumps(result,sort_keys=True))

def main():
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="command",required=True)
    command=sub.add_parser("pod-overrides"); command.add_argument("--node",required=True); command.add_argument("--image",required=True)
    command=sub.add_parser("validate"); command.add_argument("--log",required=True); command.add_argument("--pod",required=True); command.add_argument("--node",required=True)
    sub.add_parser("self-test"); args=parser.parse_args()
    try:
        if args.command=="pod-overrides": print(json.dumps(overrides(args.node,args.image),separators=(",",":")))
        elif args.command=="validate": validate(args.log,args.pod,args.node)
        else:
            value=overrides("worker one","golden-path-api:0.1.0-"+"a"*12)
            assert value["spec"]["nodeName"]=="worker one"
            assert all(item in PROBE for item in ("dns_failure","dns_timeout","process_failure"))
            with tempfile.TemporaryDirectory() as directory:
                root=pathlib.Path(directory); pod=root/"pod.json"; log=root/"probe.log"
                pod.write_text(json.dumps({"spec":{"nodeName":"worker one"},"status":{"containerStatuses":[{"state":{"terminated":{"exitCode":0}}}]}}))
                log.write_text(json.dumps({"test":"dns","query":"kubernetes.default.svc","port":443,"observed":"success","error_category":"none","exit_code":0,"duration_seconds":0.1,"address":"10.96.0.1"})+"\n")
                validate(str(log),str(pod),"worker one")
                failed=json.loads(log.read_text()); failed.update(observed="failure",error_category="dns_failure",exit_code=10)
                log.write_text(json.dumps(failed)+"\n"); pod.write_text(json.dumps({"spec":{"nodeName":"worker one"},"status":{"containerStatuses":[{"state":{"terminated":{"exitCode":10}}}]}}))
                try: validate(str(log),str(pod),"worker one")
                except ValueError as error: assert "DNS assertion failed" in str(error)
                else: raise AssertionError("DNS failure was accepted")
            print("PASS  structured DNS probe distinguishes success, DNS failure, timeout, and process failure.")
    except (ValueError,json.JSONDecodeError) as error: raise SystemExit("FAIL  "+str(error)) from error

if __name__=="__main__": main()

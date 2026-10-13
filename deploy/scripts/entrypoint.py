"""Build argv without a shell; preserve quoted future CLI flags in POWERK_ARGS."""
import os
import shlex
import sys

args = [sys.executable, "-m", "powerk", "serve", "--data", "/data",
        "--web-port", "8080", "--port", "10086"]
for env, flag in (("POWERK_TOKEN", "--token"), ("POWERK_MAC", "--mac"), ("POWERK_IP", "--ip")):
    if os.environ.get(env):
        args.extend([flag, os.environ[env]])
args.extend(shlex.split(os.environ.get("POWERK_ARGS", "")))
args.extend(sys.argv[1:])
os.execv(sys.executable, args)

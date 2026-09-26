from pathlib import Path
import sys

def app_base_dir():
    if getattr(sys,"frozen",False): return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

if __name__=="__main__":
    if len(sys.argv)==5 and sys.argv[1]=="--apply-update":
        from pstbskx.updater import helper_main
        raise SystemExit(helper_main(sys.argv[2:]))
    from pstbskx.app import run
    raise SystemExit(run(app_base_dir()))

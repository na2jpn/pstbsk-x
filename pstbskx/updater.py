"""Validated one-file Windows release updater; never execute ZIP contents."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
import zipfile

PRODUCT="PSTBSK-X"
EXE="PSTBSK-X.exe"
MANIFEST="config/pstbskx-release.json"
LICENSE="licenses/TBSKmodem_LICENSE.txt"
FILES=(EXE,LICENSE)
MAX_BYTES=512*1024*1024

def version_key(value):
    if not isinstance(value,str) or not re.fullmatch(r"\d{1,4}\.\d{1,6}",value): raise ValueError("バージョン形式が不正です")
    major,frac=value.split(".")
    return int(major),int(frac.ljust(6,"0"))

def digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as fp:
        for block in iter(lambda:fp.read(1024*1024),b""): h.update(block)
    return h.hexdigest()

def create_manifest(root,version):
    root=Path(root); version_key(version)
    data={"product":PRODUCT,"format":1,"platform":"windows","version":version,"config_schema":1,
          "files":{name:digest(root/name) for name in FILES}}
    target=root/MANIFEST; target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return data

def _check_name(name):
    raw=name.rstrip("/"); parts=raw.split("/")
    reserved={"CON","PRN","AUX","NUL",*[f"COM{i}" for i in range(1,10)],*[f"LPT{i}" for i in range(1,10)]}
    if (not raw or name.startswith("/") or "\\" in name or ":" in name or "\x00" in name or
        any(p in ("",".","..") or p.endswith((" ",".")) or p.split(".")[0].upper() in reserved for p in parts)):
        raise ValueError("危険なZIPパスです")

def inspect_zip(path,current_version,installed_root=None):
    path=Path(path); version_key(current_version)
    if path.stat().st_size>MAX_BYTES: raise ValueError("更新ZIPが大きすぎます")
    try:
        with zipfile.ZipFile(path) as archive:
            items=archive.infolist()
            if len(items)>64 or sum(i.file_size for i in items)>MAX_BYTES: raise ValueError("更新ZIPの展開サイズ／件数が上限を超えています")
            seen=set()
            for item in items:
                _check_name(item.filename)
                folded=item.filename.rstrip("/").casefold()
                if folded in seen: raise ValueError("ZIP内に重複パスがあります")
                seen.add(folded)
                if stat.S_ISLNK(item.external_attr>>16) or item.flag_bits&1: raise ValueError("リンク／暗号化ZIPは使用できません")
            expected={MANIFEST,*FILES}; folders={"config/","log/","bak/","licenses/"}
            if any(i.filename not in expected|folders for i in items): raise ValueError("配布ZIPに想定外のファイルがあります")
            if not expected.issubset({i.filename for i in items}): raise ValueError("PSTBSK-X配布ZIPのファイルが不足しています")
            if archive.getinfo(MANIFEST).file_size>16384: raise ValueError("マニフェストが大きすぎます")
            info=json.loads(archive.read(MANIFEST))
            if (not isinstance(info,dict) or info.get("product")!=PRODUCT or info.get("format")!=1 or
                info.get("platform")!="windows" or info.get("config_schema")!=1): raise ValueError("PSTBSK-X Windows配布ZIPではありません")
            new=version_key(info["version"]); old=version_key(current_version)
            if new<old: raise ValueError("旧版への更新はできません")
            if set(info.get("files",{}))!=set(FILES): raise ValueError("更新対象ファイルが不正です")
            for name in FILES:
                h=hashlib.sha256()
                with archive.open(name) as fp:
                    first=fp.read(2)
                    if name==EXE and first!=b"MZ": raise ValueError("Windows EXEではありません")
                    h.update(first)
                    for block in iter(lambda:fp.read(1024*1024),b""): h.update(block)
                if h.hexdigest()!=info["files"][name]: raise ValueError(f"{name} のハッシュが一致しません")
            if new==old:
                if installed_root is None: raise ValueError("同版の検証にはインストール先が必要です")
                if digest(Path(installed_root)/EXE)==info["files"][EXE]: raise ValueError("現在と同じ内容のZIPです")
            return info
    except (zipfile.BadZipFile,KeyError,json.JSONDecodeError,UnicodeError,TypeError) as exc:
        raise ValueError(f"更新ZIPを検証できません: {exc}") from exc

def _no_links(root,names):
    for name in names:
        node=root/name
        if node.is_symlink() or (hasattr(node,"is_junction") and node.is_junction()): raise ValueError(f"リンク先は更新できません: {name}")

def prepare_update(zip_path,root,current_version):
    root=Path(root).resolve(); _no_links(root,("bak","bak/updates","bak/update-snapshots",EXE,MANIFEST,"config","log","licenses"))
    stage=root/"bak"/"updates"/uuid.uuid4().hex; stage.mkdir(parents=True)
    try:
        snapshot=stage/"release.zip"; shutil.copy2(zip_path,snapshot)
        inspect_zip(snapshot,current_version,root)
        (stage/"request.json").write_text(json.dumps({"root":str(root),"version":current_version}),encoding="utf-8")
        return stage
    except Exception:
        shutil.rmtree(stage); raise

def _atomic_copy(source,target):
    temporary=target.with_name(target.name+".update-tmp")
    target.parent.mkdir(parents=True,exist_ok=True)
    try:
        shutil.copy2(source,temporary)
        for n in range(50):
            try: os.replace(temporary,target); break
            except PermissionError:
                if n==49: raise
                time.sleep(.1)
    finally: temporary.unlink(missing_ok=True)

def apply_update(stage,root,current_version):
    stage=Path(stage).resolve(); root=Path(root).resolve()
    if stage.parent!=root/"bak"/"updates": raise ValueError("更新作業場所が不正です")
    _no_links(root,("bak","bak/updates","bak/update-snapshots",EXE,MANIFEST,"config","log","licenses"))
    info=inspect_zip(stage/"release.zip",current_version,root)
    installed=root/MANIFEST
    if not installed.is_file() or not (root/EXE).is_file(): raise ValueError("更新先にPSTBSK-X配布ファイルがありません")
    old=json.loads(installed.read_text(encoding="utf-8"))
    if old.get("product")!=PRODUCT or old.get("version")!=current_version: raise ValueError("更新先のバージョンが変わっています")
    payload=stage/"payload"; payload.mkdir(exist_ok=True)
    with zipfile.ZipFile(stage/"release.zip") as archive:
        for name in (*FILES,MANIFEST):
            target=payload/name; target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(name) as src,target.open("wb") as dst: shutil.copyfileobj(src,dst)
    backup=root/"bak"/"update-snapshots"/(time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:8])
    backup.mkdir(parents=True)
    try:
        for name in (*FILES,MANIFEST):
            target=backup/name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(root/name,target)
        for name in ("config","log","bak"):
            src=root/name
            if src.exists():
                def ignore(directory,names):
                    return [n for n in names if Path(directory)==root/"bak" and n in ("updates","update-snapshots")]
                shutil.copytree(src,backup/name,ignore=ignore,dirs_exist_ok=True)
    except Exception:
        shutil.rmtree(backup); raise
    journal=stage/"result.json"
    def record(status,detail=""):
        journal.write_text(json.dumps({"status":status,"backup":str(backup),"version":info["version"],"detail":detail},ensure_ascii=False),encoding="utf-8")
    record("backed_up"); changed=[]
    try:
        for name in (*FILES,MANIFEST):
            _atomic_copy(payload/name,root/name); changed.append(name)
        record("succeeded"); return backup
    except Exception as exc:
        errors=[]
        for name in reversed(changed):
            try: _atomic_copy(backup/name,root/name)
            except Exception as restore: errors.append(f"{name}: {restore}")
        record("rollback_failed" if errors else "rolled_back",str(exc)+"; "+"; ".join(errors))
        raise RuntimeError(f"更新失敗。バックアップ: {backup} / {exc}"+(" / 復元失敗: "+"; ".join(errors) if errors else " / 旧版に復元済み")) from exc

def launch_updater(stage,root):
    if sys.platform!="win32" or not getattr(sys,"frozen",False): raise RuntimeError("Windows EXE版から更新してください")
    helper=Path(stage)/"PSTBSK-X-updater.exe"; shutil.copy2(sys.executable,helper)
    env=os.environ.copy(); env["PYINSTALLER_RESET_ENVIRONMENT"]="1"
    subprocess.Popen([str(helper),"--apply-update",str(stage),str(root),str(os.getpid())],cwd=stage,env=env,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)

def _wait_parent(pid):
    import ctypes
    from ctypes import wintypes
    api=ctypes.WinDLL("kernel32",use_last_error=True)
    api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]; api.OpenProcess.restype=wintypes.HANDLE
    api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]; api.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=api.OpenProcess(0x00100000,False,pid)
    if not handle:
        if ctypes.get_last_error()==87: return
        raise OSError("アプリの終了を確認できません")
    try:
        if api.WaitForSingleObject(handle,60000)!=0: raise TimeoutError("アプリの終了待ちがタイムアウトしました")
    finally: api.CloseHandle(handle)

def report_startup(root):
    token=os.environ.pop("PSTBSKX_RESTART_TOKEN","")
    if not re.fullmatch(r"[0-9a-f]{32}",token): return
    from . import VERSION
    target=Path(root)/"bak"/"updates"/"restart-ready.json"
    temp=target.with_suffix(".tmp"); temp.write_text(json.dumps({"token":token,"version":VERSION,"pid":os.getpid()}),encoding="utf-8"); os.replace(temp,target)

def helper_main(args):
    import ctypes
    from PySide6.QtCore import QLockFile
    stage,root,pid=Path(args[0]).resolve(),Path(args[1]).resolve(),int(args[2]); lock=None; backup=None
    try:
        request=json.loads((stage/"request.json").read_text(encoding="utf-8"))
        if Path(request["root"]).resolve()!=root or stage.parent!=root/"bak"/"updates": raise ValueError("更新先が一致しません")
        _wait_parent(pid)
        lock=QLockFile(str(root/"config"/"pstbskx.lock")); lock.setStaleLockTime(0)
        if not lock.tryLock(3000): raise RuntimeError("別のPSTBSK-Xが実行中です")
        backup=apply_update(stage,root,request["version"])
    except Exception as exc:
        message=str(exc); (stage/"helper-error.txt").write_text(message,encoding="utf-8"); code=1
    else: code=0
    finally:
        if lock: lock.unlock()
    if code==0:
        try:
            token=uuid.uuid4().hex; env=os.environ.copy(); env["PYINSTALLER_RESET_ENVIRONMENT"]="1"; env["PSTBSKX_RESTART_TOKEN"]=token
            ctypes.windll.kernel32.SetDllDirectoryW(None)
            process=subprocess.Popen([str(root/EXE)],cwd=root,env=env,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            deadline=time.monotonic()+45; receipt=root/"bak"/"updates"/"restart-ready.json"
            while time.monotonic()<deadline:
                try:
                    if json.loads(receipt.read_text(encoding="utf-8")).get("token")==token: return 0
                except (OSError,ValueError): pass
                if process.poll() is not None: raise RuntimeError("再起動したアプリが画面表示前に終了しました")
                time.sleep(.1)
            raise TimeoutError("再起動画面を確認できませんでした")
        except Exception as exc:
            message=f"更新は完了しましたが再起動を確認できません。\n{root/EXE} を起動してください。\nバックアップ: {backup}\n{exc}"
            (stage/"restart-error.txt").write_text(message,encoding="utf-8"); code=2
    ctypes.windll.user32.MessageBoxW(None,message,"PSTBSK-X 更新",0x10)
    return code

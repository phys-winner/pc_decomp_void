"""Run a short owned-window D3D9 device calibration without changing game settings."""
import hashlib
import json
from pathlib import Path
import subprocess
from test_memmove import compiler_environment

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / "build/d3d9-native"
    output.mkdir(parents=True,exist_ok=True)
    source = ROOT / "tests/d3d9_native_probe.c"
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    compiler, env, sdk = compiler_environment()
    executable = output / "probe.exe"
    command = [str(compiler),"/nologo","/O2","/std:c11","/W3",str(source),f"/Fo{output}\\",f"/Fe{executable}",
        "/link","/MACHINE:X86","/NXCOMPAT","user32.lib","d3d9.lib","wtsapi32.lib"]
    built = subprocess.run(command,cwd=ROOT,env=env,text=True,capture_output=True)
    (output / "compile.log").write_text(built.stdout+built.stderr)
    if built.returncode: raise RuntimeError(built.stdout+built.stderr)
    tested = subprocess.run([str(executable)],cwd=ROOT,text=True,capture_output=True,timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW)
    text = tested.stdout+tested.stderr
    (output / "output.txt").write_text(text)
    rows = []
    for line in tested.stdout.splitlines():
        parts = line.split()
        row = {"kind":parts[0]} if parts else {}
        values = [part for part in parts[1:] if "=" not in part]
        if values: row["labels"] = values
        row.update(part.split("=",1) for part in parts[1:] if "=" in part)
        rows.append(row)
    source_unchanged = before==hashlib.sha256(source.read_bytes()).hexdigest()
    receipt = {"status":"RECORDED" if tested.returncode==0 and source_unchanged else "FAILED",
        "compiler":str(compiler),"sdk":sdk,"source_sha256":before,"source_unchanged":source_unchanged,
        "exit":tested.returncode,"output":text,"rows":rows,
        "game_dll_loaded":False,"project_runtime_executed":False,"game_settings_modified":False,
        "uses_own_window_instance_wndproc_and_thread":True,
        "creates_brief_fullscreen_and_windowed_devices":True,
        "executable_sha256":hashlib.sha256(executable.read_bytes()).hexdigest()}
    (output / "result.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(text,end="")
    assert receipt["status"]=="RECORDED",receipt
    assert len([r for r in rows if r.get("kind")=="result"])==4,receipt
    assert all(r["window_destroyed"]=="1" for r in rows if r.get("kind")=="cleanup"),receipt


if __name__=="__main__": main()

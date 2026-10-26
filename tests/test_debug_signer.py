"""Both APK builders use only a fake protected project key; real signers stay untouched."""
import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import debug_signer
import build_game_apk

KEYTOOL = build_game_apk.JAVA_HOME / "bin/keytool.exe"


def file_state(path):
    return (hashlib.sha256(path.read_bytes()).digest(), path.stat().st_mtime_ns) if path.is_file() else None


def generate_fixture(project, keypass="android"):
    key = project / "android/debug.keystore"
    key.parent.mkdir(parents=True)
    subprocess.run([str(KEYTOOL), "-genkeypair", "-storetype", "JKS", "-keystore", str(key),
                    "-storepass", "android", "-keypass", keypass, "-alias", "androiddebugkey",
                    "-keyalg", "RSA", "-keysize", "2048", "-validity", "2", "-dname", "CN=Signer Test"],
                   capture_output=True, check=True)
    return key


def main():
    environment = {key: value for key, value in os.environ.items() if key not in ("VOID_SERIAL", "ANDROID_SERIAL")}
    for flag in ("--install", "--push-lib"):
        stopped = subprocess.run([sys.executable, "-B", str(ROOT / "tools/build_game_apk.py"), flag],
                                 env=environment, capture_output=True, text=True)
        assert stopped.returncode == 2 and "--serial or VOID_SERIAL is required" in stopped.stderr
    real_standard = Path.home() / ".android/debug.keystore"
    real_before = file_state(real_standard)
    recovered = [ROOT / "android/debug.keystore", ROOT / "build/android/debug.keystore"]
    recovered_before = {path: file_state(path) for path in recovered}
    base = ROOT / "build/debug-signer-test"
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="protected-", dir=base) as temp:
        out = Path(temp)
        assert out.resolve().is_relative_to(base.resolve())
        project = out / "project"
        standard = generate_fixture(project)
        original = file_state(standard)
        # A valid global key and a different legacy file must never be fallbacks.
        home = out / "home"
        project_keys = [home / ".android/debug.keystore", project / "build/android/debug.keystore"]
        for n, key in enumerate(project_keys):
            key.parent.mkdir(parents=True)
            key.write_bytes(standard.read_bytes() if n == 0 else b"preserved legacy fixture")
        previous = {key: file_state(key) for key in project_keys}
        with patch.object(debug_signer.Path, "home", return_value=home), \
             patch.object(debug_signer, "keytool_run", wraps=debug_signer.keytool_run) as calls:
            signer = debug_signer.resolve_debug_signer(KEYTOOL, project)
            assert signer["keystore"] == str(standard) and signer["source"] == "project-protected"
            assert debug_signer.resolve_debug_signer(KEYTOOL, project) == signer
            with patch.object(debug_signer, "__file__", str(project / "tools/debug_signer.py")):
                assert debug_signer.resolve_debug_signer(KEYTOOL) == signer
            assert {call.args[1] for call in calls.call_args_list} == {"-certreq", "-exportcert"}
        assert file_state(standard) == original and all(file_state(k) == v for k, v in previous.items())

        class BuildStopped(Exception): pass
        def stop_build(*args, **kwargs): raise BuildStopped()

        # Execute the actual Python builder through its first build operation.
        with patch.object(debug_signer.Path, "home", return_value=home), \
             patch.object(build_game_apk, "ROOT", project), patch.object(build_game_apk, "OUT", out / "not-built"), \
             patch.object(build_game_apk, "resolve_debug_signer", wraps=debug_signer.resolve_debug_signer) as resolve, \
             patch.object(build_game_apk, "run", side_effect=stop_build), \
             patch.object(sys, "argv", ["build_game_apk.py", "--java-only"]), contextlib.redirect_stdout(io.StringIO()):
            try: build_game_apk.main()
            except BuildStopped: pass
            else: raise AssertionError("Python builder did not reach the guarded build boundary")
            assert resolve.call_args.args == (KEYTOOL, project)
        # Execute its actual apksigner call with a recorder, not an APK build.
        tree = ast.parse((ROOT / "tools/build_game_apk.py").read_text())
        call, = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                 and node.func.id == "run" and len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and node.args[1].value == "sign"]
        signed = []
        eval(compile(ast.Expression(call), "builder-sign-call", "eval"),
             dict(run=lambda *args: signed.append(args), TOOLS=build_game_apk.TOOLS,
                  keystore=Path(signer["keystore"]), apk=out / "not-built.apk", aligned=out / "not-built-aligned.apk"))
        assert signed[0][signed[0].index("--ks") + 1] == standard

        # Execute the PowerShell builder's exact resolver block and signing line.
        ps_source = (ROOT / "tools/build_android.ps1").read_text()
        begin = ps_source.index("$signerJson =")
        end = ps_source.index("foreach ($directory", begin)
        block = ps_source[begin:end].replace("$PSScriptRoot", "$HelperRoot")
        sign, = [line for line in ps_source.splitlines() if "apksigner.bat" in line and "@('sign'" in line]
        probe = out / "builder-route.ps1"
        probe.write_text("""param($HelperRoot, $keytool, $Python, $project)
$ErrorActionPreference = 'Stop'
Set-Alias python $Python
""" + block + """
function Run([string]$program, [string[]]$arguments) { $script:signingKey = $arguments[2] }
$tools='not-executed'; $apk='not-built.apk'; $build='not-built'
""" + sign + "\nif ($signingKey -ne $keystore) { throw 'Wrong signing key' }\n$signer | ConvertTo-Json -Compress\n")
        environment = dict(os.environ, USERPROFILE=str(home))
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                   "-File", str(probe), str(ROOT / "tools"), str(KEYTOOL), sys.executable, str(project)]
        completed = subprocess.run(command, env=environment, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout.splitlines()[-1]) == signer

        missing = out / "missing-home"
        directory = out / "directory-home"
        (directory / "android/debug.keystore").mkdir(parents=True)
        invalid = out / "invalid-home"
        (invalid / "android").mkdir(parents=True)
        (invalid / "android/debug.keystore").write_bytes(b"invalid fixture")
        wrong_password = out / "wrong-key-password"
        generate_fixture(wrong_password, "different")
        certificate_only = out / "certificate-only"
        certificate_key = certificate_only / "android/debug.keystore"
        certificate_key.parent.mkdir(parents=True)
        certificate = out / "public-test.cer"
        certificate.write_bytes(debug_signer.keytool_run(KEYTOOL, "-exportcert", "-keystore", standard,
                               "-storepass", "android", "-alias", "androiddebugkey"))
        subprocess.run([str(KEYTOOL), "-importcert", "-noprompt", "-storetype", "JKS", "-keystore", str(certificate_key),
                        "-storepass", "android", "-alias", "androiddebugkey", "-file", str(certificate)], capture_output=True, check=True)
        for fake_project in (missing, directory, invalid, wrong_password, certificate_only):
            key = fake_project / "android/debug.keystore"
            before = file_state(key)
            with patch.object(debug_signer.Path, "home", return_value=home), \
                 patch.object(debug_signer, "keytool_run", wraps=debug_signer.keytool_run) as calls:
                try: debug_signer.resolve_debug_signer(KEYTOOL, fake_project)
                except RuntimeError: pass
                else: raise AssertionError("missing/invalid/unusable protected project key accepted")
                assert all(call.args[1] in ("-certreq", "-exportcert") for call in calls.call_args_list)
            assert file_state(key) == before
        # Missing project key stops the real builder despite a valid global key.
        with patch.object(debug_signer.Path, "home", return_value=home), \
             patch.object(build_game_apk, "ROOT", missing), patch.object(build_game_apk, "OUT", out / "not-built"), \
             patch.object(build_game_apk, "run", side_effect=stop_build) as build_call, \
             patch.object(sys, "argv", ["build_game_apk.py", "--java-only"]):
            try: build_game_apk.main()
            except RuntimeError: pass
            else: raise AssertionError("builder continued without protected project key")
            assert not build_call.called
        failed = subprocess.run([*command[:-1], str(missing)], env=environment, capture_output=True, text=True)
        assert failed.returncode != 0 and not (missing / "android/debug.keystore").exists()
        assert file_state(standard) == original and all(file_state(k) == v for k, v in previous.items())
    assert file_state(real_standard) == real_before
    assert all(file_state(path) == state for path, state in recovered_before.items())
    print("PASS protected-project signer: default root and both actual builder resolver/sign routes; missing/invalid/wrong-keypass/certificate-only fail early despite valid global key; no generation/migration; all real keys unchanged")


if __name__ == "__main__":
    main()

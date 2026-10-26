"""Read-only protected project debug signer shared by both APK builders."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def keytool_run(keytool, *arguments):
    result = subprocess.run([str(keytool), *map(str, arguments)], capture_output=True)
    if result.returncode:
        raise RuntimeError(f"keytool could not validate the protected project debug signer (exit {result.returncode}); no key was changed")
    return result.stdout


def certificate_sha256(keytool, keystore):
    certificate = keytool_run(keytool, "-exportcert", "-keystore", keystore, "-storepass", "android",
                              "-alias", "androiddebugkey")
    return ":".join(f"{byte:02X}" for byte in hashlib.sha256(certificate).digest())


def resolve_debug_signer(keytool, project=None):
    project = Path(project).resolve() if project is not None else Path(__file__).resolve().parents[1]
    keystore = project / "android/debug.keystore"
    if not keystore.is_file():
        raise RuntimeError(f"Protected project debug keystore is missing or not a regular file: {keystore}; no key was generated")
    # A certificate request verifies the private key/password without storing it.
    keytool_run(keytool, "-certreq", "-keystore", keystore, "-storepass", "android", "-keypass", "android",
                "-alias", "androiddebugkey")
    return dict(keystore=str(keystore), certificate_sha256=certificate_sha256(keytool, keystore), source="project-protected")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--keytool", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(resolve_debug_signer(args.keytool, args.project)))


if __name__ == "__main__":
    main()

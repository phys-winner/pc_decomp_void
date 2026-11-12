"""Build update.json, the launcher's update manifest, from a repository's GitHub releases.

    python tools/update_manifest.py --repo OWNER/NAME --out update.json [--state versions.json]

Every published release that is not a draft or pre-release and carries an APK becomes an entry; the
APK's own manifest is the source of truth for package, versionCode and versionName (aapt2 dump
badging), apksigner names its signing certificate, and the SHA-256 comes from GitHub's asset digest
or the downloaded bytes. "latest" is the highest versionCode; the workflow (ci/update-manifest.yml)
attaches update.json to GitHub's latest release, so the launcher reads it from
https://github.com/OWNER/NAME/releases/latest/download/update.json.

versions.json caches what was read from each APK (keyed by asset id and digest), so every APK is
downloaded once: --state reads and writes a local copy, --state-from-releases loads the newest one
attached to a release. --apk TAG=PATH supplies a local copy of a release's APK (its SHA-256 must
equal the asset's). The output has no generation time: unchanged releases give the same bytes.
Standard library only; runs on Windows and Linux.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

SCHEMA = 1
API = "https://api.github.com"
NOTES_LIMIT = 4000
HISTORY_LIMIT = 30
NOTES_KEPT = 10


def request(url, token=None, accept="application/vnd.github+json"):
    headers = {"Accept": accept, "User-Agent": "port-launcher-update-manifest", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = "Bearer " + token
    return urllib.request.Request(url, headers=headers)


def releases(repo, token):
    found, page = [], 1
    while True:
        with urllib.request.urlopen(request(f"{API}/repos/{repo}/releases?per_page=100&page={page}", token), timeout=60) as r:
            batch = json.load(r)
        found += batch
        if len(batch) < 100:
            return found
        page += 1


def build_tools(explicit):
    """The newest build-tools folder that has aapt2 (ANDROID_HOME, ANDROID_SDK_ROOT, ANDROID_SDK)."""
    if explicit:
        return Path(explicit)
    roots = [os.environ.get(name) for name in ("ANDROID_HOME", "ANDROID_SDK_ROOT", "ANDROID_SDK")]
    roots.append(str(Path.home() / "AppData/Local/Android/Sdk"))
    for root in filter(None, roots):
        folder = Path(root) / "build-tools"
        if not folder.is_dir():
            continue
        def key(path):
            return [int(part) if part.isdigit() else -1 for part in re.split(r"[.-]", path.name)]
        for candidate in sorted(folder.iterdir(), key=key, reverse=True):
            if (candidate / "aapt2").is_file() or (candidate / "aapt2.exe").is_file():
                return candidate
    raise SystemExit("No Android build-tools with aapt2: set ANDROID_HOME or pass --build-tools")


def tool(tools, name):
    for candidate in (name + ".exe", name + ".bat", name):
        if (tools / candidate).is_file():
            return str(tools / candidate)
    return None


def run(*args):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def apk_facts(path, tools):
    """package, versionCode, versionName, minSdk, abis and the signing certificate of one APK."""
    result = run(tool(tools, "aapt2"), "dump", "badging", path)
    if result.returncode:
        raise ValueError(f"aapt2 cannot read {path}: {result.stderr.strip()[-500:]}")
    text = result.stdout
    package = re.search(r"^package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'", text, re.M)
    if not package:
        raise ValueError(f"{path}: no package line in aapt2 badging")
    sdk = re.search(r"^(?:minSdkVersion|sdkVersion):'(\d+)'", text, re.M)
    abis = re.search(r"^native-code: (.+)$", text, re.M)
    facts = {
        "package": package.group(1),
        "versionCode": int(package.group(2)),
        "versionName": package.group(3),
        "minSdk": int(sdk.group(1)) if sdk else None,
        "abis": re.findall(r"'([^']+)'", abis.group(1)) if abis else [],
        "signer": None,
    }
    signer = tool(tools, "apksigner")
    if signer:
        verified = run(signer, "verify", "--print-certs", path)
        digest = re.search(r"^Signer #1 certificate SHA-256 digest: ([0-9a-f]{64})$", verified.stdout, re.M)
        if verified.returncode == 0 and digest:
            facts["signer"] = digest.group(1)
        else:
            print(f"warning: apksigner did not verify {path}: {(verified.stderr or verified.stdout).strip()[-300:]}", file=sys.stderr)
    else:
        print("warning: no apksigner in " + str(tools) + "; signer left out", file=sys.stderr)
    return facts


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(asset, token, folder):
    target = Path(folder) / asset["name"]
    url = asset["url"] if token else asset["browser_download_url"]
    with urllib.request.urlopen(request(url, token, "application/octet-stream"), timeout=600) as r, open(target, "wb") as out:
        shutil.copyfileobj(r, out, 1 << 20)
    if target.stat().st_size != asset["size"]:
        raise ValueError(f"{asset['name']}: downloaded {target.stat().st_size} of {asset['size']} bytes")
    return target


def pick_apk(release, pattern):
    apks = [a for a in release.get("assets", []) if re.search(pattern, a["name"], re.I)]
    if len(apks) > 1:
        raise SystemExit(f"{release['tag_name']}: several APKs match {pattern!r}: {', '.join(a['name'] for a in apks)}")
    return apks[0] if apks else None


def state_from_releases(listed, token):
    """The newest versions.json attached to a release (what the previous runs read), or {}."""
    for release in listed:
        for asset in release.get("assets", []):
            if asset["name"] == "versions.json":
                url = asset["url"] if token else asset["browser_download_url"]
                with urllib.request.urlopen(request(url, token, "application/octet-stream"), timeout=60) as r:
                    return json.load(r)
    return {}


def notes(body):
    body = (body or "").replace("\r\n", "\n").strip()
    return body if len(body) <= NOTES_LIMIT else body[:NOTES_LIMIT].rstrip() + "\n…"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="OWNER/NAME (default: $GITHUB_REPOSITORY)")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--state", type=Path, help="local cache of facts read from APKs (read if present, written)")
    parser.add_argument("--state-from-releases", action="store_true", help="start from the newest versions.json asset")
    parser.add_argument("--apk", action="append", default=[], metavar="TAG=PATH", help="a local copy of a release's APK")
    parser.add_argument("--asset-pattern", default=r"\.apk$", help="regex for the APK asset name")
    parser.add_argument("--build-tools", help="folder with aapt2 and apksigner")
    parser.add_argument("--no-download", action="store_true", help="never download; releases without facts are left out")
    parser.add_argument("--include-prereleases", action="store_true",
                        help="treat pre-releases as releases (testing; GitHub's latest link ignores them)")
    args = parser.parse_args()
    if not args.repo or not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        parser.error("--repo OWNER/NAME is required")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    local = {}
    for item in args.apk:
        tag, _, path = item.partition("=")
        if not path or not Path(path).is_file():
            parser.error(f"--apk {item}: expected TAG=PATH to an existing file")
        local[tag] = Path(path)
    tools = build_tools(args.build_tools)
    try:
        listed = releases(args.repo, token)
    except urllib.error.HTTPError as failure:
        raise SystemExit(f"GitHub API: {failure.code} {failure.reason} for {args.repo}") from failure
    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state and args.state.is_file() else {}
    if args.state_from_releases and not state:
        state = state_from_releases(listed, token)

    entries, used = [], {}
    with tempfile.TemporaryDirectory(prefix="update-manifest-") as scratch:
        for release in listed:
            if release.get("draft") or (release.get("prerelease") and not args.include_prereleases):
                continue
            asset = pick_apk(release, args.asset_pattern)
            if asset is None:
                continue
            digest = (asset.get("digest") or "").removeprefix("sha256:") or None
            key = f"{asset['id']}:{digest or asset['size']}"
            facts = state.get(key)
            if facts is None:
                tag = release["tag_name"]
                if tag in local:
                    path = local[tag]
                elif args.no_download:
                    print(f"skipped {tag}: no cached facts and --no-download", file=sys.stderr)
                    continue
                else:
                    print(f"downloading {asset['name']} ({asset['size'] / 1e6:.1f} MB)", file=sys.stderr)
                    path = download(asset, token, scratch)
                actual = sha256(path)
                if digest and actual != digest:
                    raise SystemExit(f"{path}: SHA-256 {actual} differs from the release asset's {digest}")
                if path.stat().st_size != asset["size"]:
                    raise SystemExit(f"{path}: {path.stat().st_size} bytes, the release asset has {asset['size']}")
                facts = apk_facts(path, tools)
                facts["sha256"] = actual
                if path.parent == Path(scratch):
                    path.unlink()
            used[key] = facts
            entries.append({
                "versionCode": facts["versionCode"],
                "versionName": facts["versionName"],
                "tag": release["tag_name"],
                "title": release.get("name") or release["tag_name"],
                "published": release.get("published_at"),
                "page": release["html_url"],
                "apk": {
                    "name": asset["name"],
                    "url": asset["browser_download_url"],
                    "size": asset["size"],
                    "sha256": facts["sha256"],
                    "signer": facts["signer"],
                    "minSdk": facts["minSdk"],
                    "abis": facts["abis"],
                },
                "package": facts["package"],
                "notes": notes(release.get("body")),
            })

    packages = {e["package"] for e in entries}
    if len(packages) > 1:
        raise SystemExit("Releases carry different packages: " + ", ".join(sorted(packages)))
    entries.sort(key=lambda e: (e["versionCode"], e["published"] or ""), reverse=True)
    codes = [e["versionCode"] for e in entries]
    if len(codes) != len(set(codes)):
        print("warning: several releases share a versionCode; the newest published wins", file=sys.stderr)
    latest = dict(entries[0]) if entries else None
    if latest:
        latest.pop("package")
    manifest = {
        "schema": SCHEMA,
        "repository": args.repo,
        "package": entries[0]["package"] if entries else None,
        "latest": latest,
        "history": [
            {k: e[k] for k in ("versionCode", "versionName", "tag", "published", "page")}
            | ({"notes": e["notes"]} if i < NOTES_KEPT else {})
            for i, e in enumerate(entries[:HISTORY_LIMIT])
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    if not args.out.is_file() or args.out.read_text(encoding="utf-8") != text:
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"{args.out}: {len(entries)} releases, latest {codes[0] if codes else '-'}", file=sys.stderr)
    else:
        print(f"{args.out}: unchanged", file=sys.stderr)
    if args.state:
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(dict(sorted(used.items())), indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

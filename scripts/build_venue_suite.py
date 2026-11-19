"""Package the isolated Venue Suite from an approved monitor runtime and tools."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--tools", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--netsync-wheelhouse", type=Path, help="Build from a local cache of the pinned wheels")
    parser.add_argument("--zip", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    output = args.output.resolve()
    if output.exists() or (args.zip and output.with_suffix(".zip").exists()):
        parser.error("Choose a new output folder and archive name.")
    if not (args.runtime / "python.exe").is_file():
        parser.error("The approved portable Windows runtime is required.")
    tool_names = ("monitor-probe.apk", "display-control.jar", "home-lock.apk", "scrcpy-win64-v5.0.1")
    for name in tool_names:
        if not (args.tools / name).exists():
            parser.error(f"Missing approved headset helper: {name}")
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(args.runtime, output / "runtime", ignore=ignore)
    runtime = output / "runtime"
    install = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
               "--require-hashes", "--no-deps", "--only-binary=:all:", "--no-compile",
               "--platform", "win_amd64", "--python-version", "3.11", "--implementation", "cp",
               "--target", str(runtime / "netsync-packages"), "-r", str(root / "scripts/netsync-win311.lock")]
    if args.netsync_wheelhouse:
        install.extend(("--no-index", "--find-links", str(args.netsync_wheelhouse.resolve())))
    subprocess.run(install, check=True)
    pth = runtime / "python311._pth"
    with pth.open("a", encoding="utf-8") as paths:
        paths.write("\nnetsync-packages\n")
    shutil.copytree(root / "immensiva_mdm", output / "immensiva_mdm", ignore=ignore)
    tools = output / "monitor-tools"
    tools.mkdir()
    for name in tool_names:
        source = args.tools / name
        if source.is_dir():
            shutil.copytree(source, tools / name)
        else:
            shutil.copy2(source, tools / name)
    shutil.copy2(root / "monitor-tools/home-menu-policy.py", tools)
    if (args.tools / "screen-recording.apk").is_file():
        shutil.copy2(args.tools / "screen-recording.apk", tools)
    shutil.copy2(root / "docs/SCREEN_RECORDING.md", output / "SCREEN_RECORDING.md")
    shutil.copy2(root / "docs/BROWSER_CONTROL.md", output / "BROWSER_CONTROL.md")
    shutil.copy2(root / "docs/VENUE_SUITE.md", output / "README.md")
    shutil.copy2(root / "LICENSE", output)
    shutil.copy2(root / "NOTICE", output)
    shutil.copy2(root / "scripts/allow_suite_wifi.ps1", output)
    command = '@echo off\ncd /d "%~dp0"\nruntime\\python.exe -m immensiva_mdm.suite_launcher'
    for filename, flags in (("Start Venue Suite.cmd", ""), ("Stop Venue Suite.cmd", " --stop"),
                            ("Configure Venue Wi-Fi.cmd", " --configure-touch")):
        (output / filename).write_text(command + flags + '\nif errorlevel 1 pause\n', encoding="ascii")
    (output / "Allow Venue Suite on Wi-Fi.cmd").write_text(
        '@echo off\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0allow_suite_wifi.ps1"\npause\n',
        encoding="ascii")
    subprocess.run([str(output / "runtime/python.exe"), "-c", "import aiohttp, psutil, qrcode, styly_mdm"],
                   cwd=output, check=True)
    subprocess.run([str(runtime / "python.exe"), "-c",
                    "from importlib.metadata import version; import styly_netsync.server, styly_netsync.rest_bridge; "
                    "assert version('styly-netsync-server') == '0.17.5'"], cwd=output, check=True)
    if args.zip:
        print(shutil.make_archive(str(output), "zip", output.parent, output.name))
    else:
        print(output)


if __name__ == "__main__":
    main()

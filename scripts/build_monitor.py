"""Package the isolated monitor using an existing approved Python runtime."""
import argparse
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--home-lock-apk", type=Path, help="Existing signed Home menu helper APK")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    if args.output.exists():
        raise ValueError("Output exists. Choose a new folder.")
    if not (args.runtime / "python.exe").is_file():
        raise ValueError("A portable Python runtime is required")
    if not (root / "monitor-tools/monitor-probe.apk").is_file():
        raise ValueError("Build monitor-probe.apk first")
    if not (root / "monitor-tools/display-control.jar").is_file():
        raise ValueError("Build display-control.jar first")
    if args.home_lock_apk and not args.home_lock_apk.is_file():
        raise ValueError("The signed Home menu helper APK was not found")
    args.output.mkdir(parents=True)
    shutil.copytree(args.runtime, args.output / "runtime",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(root / "immensiva_mdm", args.output / "immensiva_mdm",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    tools = args.output / "monitor-tools"
    tools.mkdir()
    shutil.copy2(root / "monitor-tools/monitor-probe.apk", tools)
    shutil.copy2(root / "monitor-tools/display-control.jar", tools)
    shutil.copy2(root / "monitor-tools/home-menu-policy.py", tools)
    if args.home_lock_apk:
        shutil.copy2(args.home_lock_apk, tools / "home-lock.apk")
    shutil.copytree(root / "monitor-tools/scrcpy-win64-v5.0.1",
                    tools / "scrcpy-win64-v5.0.1")
    shutil.copy2(root / "docs/MONITOR.md", args.output / "README-Monitor.md")
    (args.output / "Start Monitor.cmd").write_text(
        '@echo off\ncd /d "%~dp0"\nruntime\\python.exe -m immensiva_mdm.monitor_launcher\nif errorlevel 1 pause\n')
    (args.output / "Stop Monitor.cmd").write_text(
        '@echo off\ncd /d "%~dp0"\nruntime\\python.exe -m immensiva_mdm.monitor_launcher --stop\nif errorlevel 1 pause\n')
    print(args.output.resolve())


if __name__ == "__main__":
    main()

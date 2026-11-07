"""Copy only the selected venue setup fields into a fresh suite."""
import json
import math

from .suite_launcher import write_json


def import_setup(data, registry_path=None, outline_path=None):
    copies = []
    if registry_path:
        source = json.loads(registry_path.read_text(encoding="utf-8"))
        labels = {serial: {"label": item["label"][:64]}
                  for serial, item in source["devices"].items()
                  if isinstance(item.get("label"), str)}
        groups = {name: ids for name, ids in source["groups"].items()
                  if isinstance(ids, list) and all(isinstance(serial, str) for serial in ids)}
        copies.append((data / "mdm/device_registry.json", {"devices": labels, "groups": groups}))
    if outline_path:
        source = json.loads(outline_path.read_text(encoding="utf-8"))
        outlines = source["measured_rooms"]
        for points in outlines.values():
            if not isinstance(points, list) or len(points) < 3 or any(
                not isinstance(point, dict) or any(type(point.get(axis)) not in (int, float)
                or not math.isfinite(point[axis]) for axis in ("x", "z")) for point in points
            ):
                raise ValueError("The saved room outline contains invalid coordinates.")
        copies.append((data / "live-ops/sessions.json", {"measured_rooms": outlines}))
    for path, _ in copies:
        if path.exists():
            raise ValueError(f"Import requires a fresh destination. {path} already exists.")
    for path, contents in copies:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, contents)

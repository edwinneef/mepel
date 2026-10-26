"""Keep learned surface identity independent of geometry's display order."""

import re


def _overlap(a: dict, b: dict, kind: str) -> float:
    axis, fixed, tolerance = ("y", "x", 12) if kind == "ropes" else ("x", "y", 24)
    if abs(sum(a[p][fixed] for p in ("start", "end")) / 2
           - sum(b[p][fixed] for p in ("start", "end")) / 2) > tolerance:
        return 0
    al, ar = sorted(a[p][axis] for p in ("start", "end"))
    bl, br = sorted(b[p][axis] for p in ("start", "end"))
    return max(0, min(ar, br) - max(al, bl))


def stabilize(geometry: dict, registry: dict) -> dict:
    previous = registry.get("surfaces", {})
    aliases = registry.setdefault("aliases", {})
    mapping, current = {}, {}
    for kind, letter in (("platforms", "p"), ("ropes", "r")):
        nodes = geometry[kind]
        old = previous.get(kind, [])
        matches = sorted(((-_overlap(a, b, kind), a["id"], index)
                          for a in old for index, b in enumerate(nodes)
                          if _overlap(a, b, kind) > 0))
        used, assigned = set(), {}
        for _, key, index in matches:
            if key not in used and index not in assigned:
                used.add(key)
                assigned[index] = next(a for a in old if a["id"] == key)
        count = max([registry.get(f"next_{letter}", 0)] + [
            int(match.group(1)) for a in old
            if (match := re.fullmatch(f"walk_{letter}(\\d+)", a["id"]))])
        names = set(registry.get("names", []))
        current[kind] = []
        for index, node in enumerate(nodes):
            raw_id = node["id"]
            if index in assigned:
                key, name = assigned[index]["id"], assigned[index]["name"]
            else:
                count += 1
                key = f"walk_{letter}{count}"
                x = (node["start"]["x"] + node["end"]["x"]) / 2
                y = (node["start"]["y"] + node["end"]["y"]) / 2
                side = "Left" if x < registry.get("center_x", 683) - 150 else (
                    "Right" if x > registry.get("center_x", 683) + 150 else "Middle")
                base = f"{side} {'rope' if letter == 'r' else 'ledge'}"
                if letter == "p" and abs(y - registry.get("floor_y", -10000)) <= 12:
                    base = "Ground floor"
                name, suffix = base, 2
                while name in names:
                    name, suffix = f"{base} {suffix}", suffix + 1
                names.add(name)
            mapping[raw_id] = key
            current[kind].append({**node, "id": key, "name": name})
        for a in old:
            if a["id"] not in used:
                merged = sorted((-_overlap(a, b, kind), b["id"]) for b in current[kind]
                                if _overlap(a, b, kind) > 0)
                if merged:
                    aliases[a["id"]] = merged[0][1]
        registry[f"next_{letter}"], registry["names"] = count, sorted(names)
    if any(current.values()):
        registry["surfaces"] = current
    links = [{**link, "from": mapping[link["from"]], "to": mapping[link["to"]]}
             for link in geometry["links"]]
    issue = geometry["problems"]
    return {**geometry, **current, "links": links, "aliases": dict(aliases),
            "problems": {"home": mapping.get(issue["home"]),
                         "unreachable": [mapping[x] for x in issue["unreachable"]],
                         "stranded": [mapping[x] for x in issue["stranded"]]}}

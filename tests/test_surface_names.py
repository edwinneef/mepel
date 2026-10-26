from maplebot.surface_names import stabilize


def segment(key, x, right, y=400):
    return {"id": key, "start": {"x": x, "y": y}, "end": {"x": right, "y": y}}


def geometry(nodes):
    return {"platforms": nodes, "ropes": [], "links": [], "boundary": None,
            "problems": {"home": nodes[0]["id"], "unreachable": [], "stranded": []}}


def test_adding_a_higher_ledge_does_not_rename_the_existing_floor():
    registry = {"floor_y": 600}
    first = stabilize(geometry([segment("walk_p1", 0, 1000, 600)]), registry)
    floor = first["platforms"][0]
    second = stabilize(geometry([segment("walk_p1", 0, 100, 300),
                                 segment("walk_p2", 0, 1000, 600)]), registry)
    assert second["platforms"][1]["id"] == floor["id"]
    assert second["platforms"][1]["name"] == "Ground floor"
    assert second["platforms"][0]["id"] != floor["id"]


def test_merge_alias_and_split_keep_the_largest_overlap_identity():
    registry = {}
    first = stabilize(geometry([segment("a", 0, 100), segment("b", 150, 400)]), registry)
    a, b = first["platforms"]
    merged = stabilize(geometry([segment("a", 0, 400)]), registry)
    assert merged["platforms"][0]["id"] == b["id"]
    assert merged["aliases"][a["id"]] == b["id"]
    split = stabilize(geometry([segment("a", 0, 50), segment("b", 100, 400)]), registry)
    assert split["platforms"][1]["id"] == b["id"]
    assert len({p["id"] for p in split["platforms"]}) == 2
    assert len({p["name"] for p in split["platforms"]}) == 2

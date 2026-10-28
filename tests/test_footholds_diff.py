import pytest

from tools.footholds_diff import chains, compare

K, B = (0.965, 0.94), (5.0, 1300.0)


def area(x, y):
    return {"x": round(K[0] * x + B[0], 1), "y": round(K[1] * y + B[1], 1)}


def source():
    rows = [
        # Floor: flat, then sloping down to the right. Ids link through next/prev.
        (1, 0, 400, 300, 300, 0, 2), (2, 400, 600, 300, 360, 1, 0),
        (3, 600, 600, 360, 200, 0, 0),  # wall, dropped
        (10, 100, 300, 100, 100, 0, 0),  # ledge A
        (20, 350, 450, 0, 0, 0, 0), (21, 470, 570, 0, 0, 0, 0),  # two ledges, 20 px apart
    ]
    footholds = {str(i): {"id": i, "x1": x1, "x2": x2, "y1": y1, "y2": y2, "prev": p, "next": n}
                 for i, x1, x2, y1, y2, p, n in rows}
    return {"id": 1, "miniMap": {"magnification": 4}, "footholds": footholds,
            "ladderRopes": [{"x": 200, "y1": 100, "y2": 300, "isLadder": True},
                            {"x": 520, "y1": 0, "y2": 290, "isLadder": False}],
            "portals": [{"portalName": "out00", "type": 2, "x": 50, "y": 300}]}


def profile():
    return {
        "minimap_calibration": {"transform": {"scale_x": K[0] * 16, "scale_y": K[1] * 16,
                                              "offset_x": 0, "offset_y": 0}},
        "platforms": [
            {"id": "p1", "name": "Floor", "start": area(10, 300), "end": area(590, 357),
             "points": [area(10, 300), area(400, 300), area(590, 357)]},
            {"id": "p2", "name": "Ledge", "start": area(110, 100), "end": area(290, 100)},
            {"id": "p3", "name": "Joined", "start": area(355, 0), "end": area(565, 0)},
            {"id": "p4", "name": "Ghost", "start": area(700, -200), "end": area(800, -200)},
        ],
        "ropes": [{"id": "r1", "name": "Rope", "start": area(200, 110), "end": area(200, 290)}],
    }


def test_chains_join_linked_footholds_and_drop_walls():
    result = chains(source())
    assert [c["id"] for c in result] == ["fh20", "fh21", "fh10", "fh1"]
    assert result[-1]["points"] == [{"x": 0, "y": 300}, {"x": 400, "y": 300},
                                    {"x": 600, "y": 360}]


def test_compare_recovers_the_fit_and_reports_gaps():
    report = compare(profile(), source())
    fitted = report["transform"]["fitted"]
    assert fitted["x"]["scale"] == pytest.approx(K[0], abs=.01)
    assert fitted["y"]["offset"] == pytest.approx(B[1], abs=2)
    platforms, ropes = report["platforms"], report["ropes"]
    assert [m["taught"] for m in platforms["matched"]] == ["p1", "p2"]
    assert platforms["spanning_gaps"] == [{"taught": "p3", "name": "Joined",
                                           "public": ["fh20", "fh21"], "gaps_px": [19.3]}]
    assert [e["taught"] for e in platforms["extra_taught"]] == ["p4"]
    assert platforms["public_never_walked"] == []
    assert [m["public"] for m in ropes["matched"]] == ["rope1"]
    assert [m["public"] for m in ropes["public_never_climbed"]] == ["rope2"]
    assert report["summary"]["taught_surfaces_matched"] == 0.8

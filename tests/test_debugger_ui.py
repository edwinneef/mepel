from importlib.resources import files


def test_debugger_renders_read_only_probe_and_timing_status():
    page = files("maplebot").joinpath("static/index.html").read_text("utf-8")

    assert 'id="bindings"' in page
    assert 'id="stage-timing"' in page
    assert 'id="encoder-timing"' in page
    assert 'data-probe="skill"' in page
    assert 'data-probe="up"' in page
    assert 'data-probe="hp_potion"' in page
    assert "confirm_probe" in page
    assert "reject_probe" in page
    assert "pet_food" not in page
    assert "controls-confirm" not in page

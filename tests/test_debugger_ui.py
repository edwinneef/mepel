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


def test_alarm_acknowledgement_is_always_visible_outside_the_stop_banner():
    page = files("maplebot").joinpath("static/index.html").read_text("utf-8")
    header = page.split("<header>", 1)[1].split("</header>", 1)[0]

    assert 'id="acknowledge"' in header
    assert "$('acknowledge').hidden" not in page


def test_restart_button_waits_for_a_new_bot_before_reloading_the_dashboard():
    page = files("maplebot").joinpath("static/index.html").read_text("utf-8")

    assert 'id="restart-bot"' in page
    assert "api('restart_bot')" in page
    assert "restart_available" in page
    assert "instance_id" in page
    assert "location.reload()" in page

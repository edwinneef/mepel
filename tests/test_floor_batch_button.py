import subprocess

from tools.floor_batch_button import batch, main


def test_actual_button_click_hides_window_runs_once_and_displays_result():
    seen = []
    errors = []
    inspected = []

    def runner(command, **kwargs):
        seen.append((command, kwargs))
        return subprocess.CompletedProcess(command, 1, "offline gate refused; no input", "")

    def ready(window, button, output):
        def click():
            button.invoke()
            assert window.state() == "withdrawn"
            assert str(button["state"]) == "disabled"
            button.invoke()  # Disabled: cannot dispatch a second batch.

        def inspect():
            if str(button["state"]) == "disabled":
                window.after(20, inspect)
                return
            try:
                assert "offline gate refused" in output.get("1.0", "end")
                assert window.state() != "withdrawn"
                inspected.append(True)
            except AssertionError as error:
                errors.append(error)
            window.destroy()

        window.after(0, click)
        window.after(20, inspect)
        window.after(5000, window.destroy)

    main(runner=runner, on_ready=ready)
    assert not errors
    assert inspected, "GUI result callback did not complete before timeout"
    assert len(seen) == 1
    assert seen[0][0][-2:] == ["--run", "--focus"]
    assert seen[0][0][0].endswith("python.exe")



def test_route_mode_starts_one_prepared_route_with_its_arguments():
    # The click path above runs these module arguments unchanged in either mode.
    title, instructions, label, module = batch(
        ["--route", "a" * 32, "fh315", "fh308", "--label", "Stand on Level 8"])
    assert (title, instructions, label) == (
        "Supervised route check", "Stand on Level 8", "Start one route fh315 -> fh308")
    assert module == ["tools.prepared_route_check", "--area", "a" * 32, "--origin",
                      "fh315", "--target", "fh308", "--run", "--focus"]
    assert batch([])[3] == ["tools.prepared_floor_check", "--run", "--focus"]


def test_farm_mode_starts_one_bounded_learn_moves_session():
    title, instructions, label, module = batch(
        ["--farm", "a" * 32, "fh308", "--minutes", "5", "--label", "Stand on Level 7"])
    assert (title, instructions, label) == (
        "Supervised learn_moves farming", "Stand on Level 7",
        "Start one 5-minute learn_moves farm from fh308")
    assert module == ["tools.prepared_farm_check", "--area", "a" * 32, "--origin", "fh308",
                      "--minutes", "5", "--run", "--focus"]


def test_farm_mode_without_an_origin_starts_where_the_character_stands():
    title, instructions, label, module = batch(["--farm", "a" * 32, "--minutes", "5"])
    assert label == "Start one 5-minute learn_moves farm from where you stand"
    assert "--origin" not in module
    assert module == ["tools.prepared_farm_check", "--area", "a" * 32, "--minutes", "5",
                      "--run", "--focus"]

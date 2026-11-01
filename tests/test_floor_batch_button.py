import subprocess

from tools.floor_batch_button import main


def test_actual_button_click_hides_window_runs_once_and_displays_result():
    seen = []
    errors = []

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
            except AssertionError as error:
                errors.append(error)
            window.destroy()

        window.after(0, click)
        window.after(20, inspect)
        window.after(5000, window.destroy)

    main(runner=runner, on_ready=ready)
    assert not errors
    assert len(seen) == 1
    assert seen[0][0][-2:] == ["--run", "--focus"]
    assert seen[0][0][0].endswith("python.exe")

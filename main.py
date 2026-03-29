import sys


def _run() -> None:
    if "--updater-runner" in sys.argv[1:]:
        # Run updater runner mode from the same executable (PyInstaller-friendly).
        from updater_runner import main as updater_main

        argv = [a for a in sys.argv[1:] if a != "--updater-runner"]
        raise SystemExit(updater_main(argv))

    from gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    _run()

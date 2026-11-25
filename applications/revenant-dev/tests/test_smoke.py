import revenant

import revenant_dev


def test_core_and_app_import() -> None:
    assert revenant.Recorder is not None
    assert revenant_dev.__doc__ is not None

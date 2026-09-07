import argparse
import importlib.util
from pathlib import Path

import pytest

from connected_gallery.agent_runtime.organizer import ResultOrganizer

spec = importlib.util.spec_from_file_location("preparation_timeout", Path(__file__).resolve().parents[1] / "scripts/prepare-demo.py")
preparation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparation)


def test_offline_timeout_default_and_explicit_configuration_leave_production_default_unchanged():
    parser = preparation.argument_parser()
    default = parser.parse_args(["--samples", "unused-fixture"])
    selected = parser.parse_args(["--samples", "unused-fixture", "--grouping-timeout-seconds", "90"])
    assert default.grouping_timeout_seconds == 45
    assert selected.grouping_timeout_seconds == 90
    gateway = object()
    assert preparation.preparation_organizer(gateway, selected.grouping_timeout_seconds).timeout == 90
    assert preparation.preparation_organizer(gateway, default.grouping_timeout_seconds).timeout == 45
    assert ResultOrganizer(gateway).timeout == 45


@pytest.mark.parametrize("value", ["44", "91", "0", "240", "45.5", "not-a-number"])
def test_cli_refuses_out_of_range_or_non_integer_grouping_budget(value):
    with pytest.raises(SystemExit) as error:
        preparation.argument_parser().parse_args(["--samples", "unused-fixture", "--grouping-timeout-seconds", value])
    assert error.value.code == 2


@pytest.mark.parametrize("value", [44, 91, None, True, 45.5])
def test_programmatic_configuration_cannot_bypass_bounds(value):
    with pytest.raises(argparse.ArgumentTypeError):
        preparation.preparation_organizer(object(), value)


@pytest.mark.parametrize("value", [45, 60, 90])
def test_bounded_offline_timeout_uses_supplied_value(value):
    assert preparation.preparation_organizer(object(), value).timeout == value

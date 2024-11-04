from __future__ import annotations

from argparse import Namespace
from unittest import mock

import pytest

from devservices.commands.update import update
from devservices.exceptions import BinaryInstallError
from devservices.exceptions import DevservicesUpdateError


@mock.patch("devservices.commands.update.metadata.version", return_value="0.0.1")
@mock.patch("devservices.commands.update.check_for_update", return_value="1.0.0")
@mock.patch("devservices.commands.update.is_in_virtualenv", return_value=True)
def test_update_in_virtualenv(
    mock_metadata_version: mock.Mock,
    mock_check_for_update: mock.Mock,
    mock_is_in_virtualenv: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update(Namespace())
    captured = capsys.readouterr()
    assert "You are running in a virtual environment." in captured.out
    assert (
        "To update, please update your requirements.txt or requirements-dev.txt file with the new version."
        in captured.out
    )
    assert (
        "For example, update the line in requirements.txt to: devservices==1.0.0"
        in captured.out
    )
    assert "Then, run: pip install --update -r requirements.txt" in captured.out


@mock.patch("devservices.commands.update.metadata.version", return_value="0.0.1")
@mock.patch("devservices.commands.update.check_for_update", return_value=None)
@mock.patch("devservices.commands.update.is_in_virtualenv", return_value=False)
@mock.patch("devservices.commands.update.install_binary")
def test_update_check_for_update_error(
    mock_metadata_version: mock.Mock,
    mock_check_for_update: mock.Mock,
    mock_is_in_virtualenv: mock.Mock,
    mock_install_binary: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(DevservicesUpdateError, match="Failed to check for updates."):
        update(Namespace())


@mock.patch("devservices.commands.update.metadata.version", return_value="1.0.0")
@mock.patch("devservices.commands.update.check_for_update", return_value="1.0.0")
@mock.patch("devservices.commands.update.is_in_virtualenv", return_value=False)
@mock.patch("devservices.commands.update.install_binary")
def test_update_already_on_latest_version(
    mock_metadata_version: mock.Mock,
    mock_check_for_update: mock.Mock,
    mock_is_in_virtualenv: mock.Mock,
    mock_install_binary: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update(Namespace())
    captured = capsys.readouterr()
    assert "You're already on the latest version." in captured.out


@mock.patch("devservices.commands.update.metadata.version", return_value="0.0.1")
@mock.patch("devservices.commands.update.check_for_update", return_value="1.0.0")
@mock.patch("devservices.commands.update.is_in_virtualenv", return_value=False)
@mock.patch("devservices.commands.update.install_binary")
def test_update_success(
    mock_metadata_version: mock.Mock,
    mock_check_for_update: mock.Mock,
    mock_is_in_virtualenv: mock.Mock,
    mock_install_binary: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update(Namespace())
    captured = capsys.readouterr()
    assert "A new version of devservices is available: 1.0.0" in captured.out
    assert "Devservices 1.0.0 updated successfully" in captured.out


@mock.patch("devservices.commands.update.metadata.version", return_value="0.0.1")
@mock.patch("devservices.commands.update.check_for_update", return_value="1.0.0")
@mock.patch("devservices.commands.update.is_in_virtualenv", return_value=False)
@mock.patch(
    "devservices.commands.update.install_binary",
    side_effect=BinaryInstallError("Installation error"),
)
def test_update_install_binary_error(
    mock_metadata_version: mock.Mock,
    mock_check_for_update: mock.Mock,
    mock_is_in_virtualenv: mock.Mock,
    mock_install_binary: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        update(Namespace())

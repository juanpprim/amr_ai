"""Tests for the download CLI script (scripts/download.py).

Mocks the underlying pipeline functions to test argument parsing,
output formatting, and exit behaviour without network calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from scripts.download import list_sources, main
from src.models import DownloadResult
from src.pipeline.sources import PHASE_1_SOURCES


def _ok_result(source_id: str = "test-source") -> DownloadResult:
    return DownloadResult(
        source_id=source_id,
        success=True,
        markdown_path=f"data/markdown/{source_id}.md",
        char_count=1234,
    )


def _fail_result(source_id: str = "test-source") -> DownloadResult:
    return DownloadResult(
        source_id=source_id,
        success=False,
        error_message="download failed",
    )


# ===========================================================================
# list_sources
# ===========================================================================


def test_list_sources(capsys):
    """--list prints all source IDs."""
    list_sources()
    captured = capsys.readouterr().out

    for source in PHASE_1_SOURCES:
        assert source.source_id in captured
    assert f"Total: {len(PHASE_1_SOURCES)}" in captured


# ===========================================================================
# main() — single source
# ===========================================================================


@pytest.mark.asyncio
async def test_main_single_source_success(monkeypatch, mock_settings):
    """--source with a known ID calls download_and_convert and prints OK."""
    monkeypatch.setattr(
        "sys.argv", ["download.py", "--source", "who-amr-topics"]
    )

    mock_dc = AsyncMock(return_value=_ok_result("who-amr-topics"))

    with patch("scripts.download.download_and_convert", mock_dc):
        await main()

    mock_dc.assert_awaited_once()
    args = mock_dc.call_args
    assert args[0][0].source_id == "who-amr-topics"


@pytest.mark.asyncio
async def test_main_unknown_source_exits(monkeypatch, mock_settings):
    """--source with an unknown ID prints an error and exits with code 1."""
    monkeypatch.setattr(
        "sys.argv", ["download.py", "--source", "nonexistent"]
    )

    with pytest.raises(SystemExit) as exc_info:
        await main()

    assert exc_info.value.code == 1


@pytest.mark.asyncio
async def test_main_failed_source_exits(monkeypatch, mock_settings):
    """A failing single-source download exits with code 1."""
    monkeypatch.setattr(
        "sys.argv", ["download.py", "--source", "who-amr-topics"]
    )

    mock_dc = AsyncMock(return_value=_fail_result("who-amr-topics"))

    with patch("scripts.download.download_and_convert", mock_dc):
        with pytest.raises(SystemExit) as exc_info:
            await main()

    assert exc_info.value.code == 1


# ===========================================================================
# main() — download all
# ===========================================================================


@pytest.mark.asyncio
async def test_main_download_all(monkeypatch, mock_settings):
    """No --source flag calls download_all with PHASE_1_SOURCES."""
    monkeypatch.setattr("sys.argv", ["download.py"])

    results = [_ok_result(s.source_id) for s in PHASE_1_SOURCES]
    mock_da = AsyncMock(return_value=results)

    with patch("scripts.download.download_all", mock_da):
        await main()

    mock_da.assert_awaited_once()
    sources_arg = mock_da.call_args[0][0]
    assert len(sources_arg) == len(PHASE_1_SOURCES)

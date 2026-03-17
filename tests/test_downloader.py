"""Tests for the download pipeline orchestrator (src/pipeline/downloader.py).

Uses local HTML/PDF fixture files and mocks to avoid network calls
and Docling initialisation.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.models import SourceConfig
from src.pipeline.downloader import download_all, download_and_convert

FAKE_MARKDOWN = "# AMR Test\n\nSample markdown content for testing purposes."


# ---------------------------------------------------------------------------
# Helper mock factories
# ---------------------------------------------------------------------------


def _make_crawl_mock(fixture_paths: list[Path]) -> AsyncMock:
    """Return an AsyncMock for crawl_html that copies fixtures into raw_dir."""

    async def _crawl(source: SourceConfig, raw_dir: Path) -> list[Path]:
        results: list[Path] = []
        for i, src_path in enumerate(fixture_paths, start=1):
            suffix = src_path.suffix.lstrip(".")
            name = f"{source.source_id}_{i:04d}_{src_path.stem}.{suffix}"
            dest = raw_dir / name
            shutil.copy(src_path, dest)
            results.append(dest)
        return results

    return AsyncMock(side_effect=_crawl)


def _make_download_pdf_mock(fixture_path: Path) -> AsyncMock:
    """Return an AsyncMock for download_pdf that copies the fixture into raw_dir."""

    async def _download(source: SourceConfig, raw_dir: Path) -> Path:
        dest = raw_dir / f"{source.source_id}.pdf"
        shutil.copy(fixture_path, dest)
        return dest

    return AsyncMock(side_effect=_download)


# ===========================================================================
# HTML (Scrapy) path tests
# ===========================================================================


@pytest.mark.asyncio
async def test_html_download_and_convert_success(
    sample_source, tmp_settings, fixture_index_html
):
    """Successful HTML download + conversion produces a markdown file."""
    crawl_mock = _make_crawl_mock([fixture_index_html])

    with (
        patch("src.pipeline.downloader.crawl_html", crawl_mock),
        patch(
            "src.pipeline.downloader.convert_file_to_markdown",
            return_value=FAKE_MARKDOWN,
        ),
    ):
        result = await download_and_convert(sample_source, tmp_settings)

    assert result.success is True
    assert result.char_count > 0
    assert result.markdown_path is not None
    assert Path(result.markdown_path).exists()
    crawl_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_html_skips_when_markdown_exists(sample_source, tmp_settings):
    """Existing markdown files cause a skip when force=False."""
    md_dir = tmp_settings.data_markdown_dir
    existing = md_dir / f"{sample_source.source_id}_0001_page.md"
    existing.write_text("# Existing", encoding="utf-8")

    crawl_mock = AsyncMock()

    with patch("src.pipeline.downloader.crawl_html", crawl_mock):
        result = await download_and_convert(sample_source, tmp_settings, force=False)

    assert result.success is True
    assert result.char_count > 0
    crawl_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_html_force_redownloads(
    sample_source, tmp_settings, fixture_index_html
):
    """force=True causes a re-crawl even when markdown exists."""
    md_dir = tmp_settings.data_markdown_dir
    existing = md_dir / f"{sample_source.source_id}_0001_page.md"
    existing.write_text("# Old", encoding="utf-8")

    crawl_mock = _make_crawl_mock([fixture_index_html])

    with (
        patch("src.pipeline.downloader.crawl_html", crawl_mock),
        patch(
            "src.pipeline.downloader.convert_file_to_markdown",
            return_value=FAKE_MARKDOWN,
        ),
    ):
        result = await download_and_convert(sample_source, tmp_settings, force=True)

    assert result.success is True
    crawl_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_html_crawl_returns_no_pages(sample_source, tmp_settings):
    """Empty crawl result produces a failure with descriptive message."""
    crawl_mock = AsyncMock(return_value=[])

    with patch("src.pipeline.downloader.crawl_html", crawl_mock):
        result = await download_and_convert(sample_source, tmp_settings)

    assert result.success is False
    assert "no pages" in (result.error_message or "").lower()


@pytest.mark.asyncio
async def test_html_crawl_raises_exception(sample_source, tmp_settings):
    """Exception in crawl_html is caught and reported."""
    crawl_mock = AsyncMock(side_effect=RuntimeError("network timeout"))

    with patch("src.pipeline.downloader.crawl_html", crawl_mock):
        result = await download_and_convert(sample_source, tmp_settings)

    assert result.success is False
    assert "network timeout" in (result.error_message or "")


@pytest.mark.asyncio
async def test_html_conversion_failure_partial(
    sample_source, tmp_settings, fixture_index_html, fixture_subpage_html
):
    """If one page conversion fails but another succeeds, result is still success."""
    crawl_mock = _make_crawl_mock([fixture_index_html, fixture_subpage_html])
    call_count = 0

    def _convert_side_effect(path: Path) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("Docling parse error")
        return FAKE_MARKDOWN

    with (
        patch("src.pipeline.downloader.crawl_html", crawl_mock),
        patch(
            "src.pipeline.downloader.convert_file_to_markdown",
            side_effect=_convert_side_effect,
        ),
    ):
        result = await download_and_convert(sample_source, tmp_settings)

    assert result.success is True
    assert result.char_count == len(FAKE_MARKDOWN)


# ===========================================================================
# PDF (Docling) path tests
# ===========================================================================


@pytest.mark.asyncio
async def test_pdf_download_and_convert_success(
    sample_pdf_source, tmp_settings, fixture_pdf
):
    """Successful PDF download + conversion produces a markdown file."""
    pdf_mock = _make_download_pdf_mock(fixture_pdf)

    with (
        patch("src.pipeline.downloader.download_pdf", pdf_mock),
        patch(
            "src.pipeline.downloader.convert_file_to_markdown",
            return_value=FAKE_MARKDOWN,
        ),
    ):
        result = await download_and_convert(sample_pdf_source, tmp_settings)

    assert result.success is True
    assert result.char_count == len(FAKE_MARKDOWN)
    assert result.markdown_path is not None
    assert Path(result.markdown_path).exists()
    assert result.raw_path is not None
    pdf_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_pdf_skips_when_markdown_exists(sample_pdf_source, tmp_settings):
    """Existing markdown file causes a skip when force=False."""
    md_path = tmp_settings.data_markdown_dir / f"{sample_pdf_source.source_id}.md"
    md_path.write_text("# Already converted", encoding="utf-8")

    pdf_mock = AsyncMock()

    with patch("src.pipeline.downloader.download_pdf", pdf_mock):
        result = await download_and_convert(
            sample_pdf_source, tmp_settings, force=False
        )

    assert result.success is True
    assert result.char_count > 0
    pdf_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_pdf_download_returns_none(sample_pdf_source, tmp_settings):
    """download_pdf returning None results in failure."""
    pdf_mock = AsyncMock(return_value=None)

    with patch("src.pipeline.downloader.download_pdf", pdf_mock):
        result = await download_and_convert(sample_pdf_source, tmp_settings)

    assert result.success is False
    assert "no content" in (result.error_message or "").lower()


@pytest.mark.asyncio
async def test_pdf_conversion_raises(
    sample_pdf_source, tmp_settings, fixture_pdf
):
    """Conversion error is caught; raw_path is still reported."""
    pdf_mock = _make_download_pdf_mock(fixture_pdf)

    with (
        patch("src.pipeline.downloader.download_pdf", pdf_mock),
        patch(
            "src.pipeline.downloader.convert_file_to_markdown",
            side_effect=ValueError("corrupt PDF"),
        ),
    ):
        result = await download_and_convert(sample_pdf_source, tmp_settings)

    assert result.success is False
    assert result.raw_path is not None
    assert "corrupt PDF" in (result.error_message or "")


# ===========================================================================
# download_all tests
# ===========================================================================


@pytest.mark.asyncio
async def test_download_all_mixed_sources(
    sample_source,
    sample_pdf_source,
    tmp_settings,
    fixture_index_html,
    fixture_pdf,
):
    """download_all processes both HTML and PDF sources."""
    crawl_mock = _make_crawl_mock([fixture_index_html])
    pdf_mock = _make_download_pdf_mock(fixture_pdf)

    with (
        patch("src.pipeline.downloader.crawl_html", crawl_mock),
        patch("src.pipeline.downloader.download_pdf", pdf_mock),
        patch(
            "src.pipeline.downloader.convert_file_to_markdown",
            return_value=FAKE_MARKDOWN,
        ),
    ):
        results = await download_all(
            [sample_source, sample_pdf_source], tmp_settings
        )

    assert len(results) == 2
    assert all(r.success for r in results)


@pytest.mark.asyncio
async def test_download_all_continues_on_failure(
    sample_source,
    sample_pdf_source,
    tmp_settings,
    fixture_pdf,
):
    """A failing source does not stop the pipeline from processing the rest."""
    crawl_mock = AsyncMock(side_effect=RuntimeError("spider crash"))
    pdf_mock = _make_download_pdf_mock(fixture_pdf)

    with (
        patch("src.pipeline.downloader.crawl_html", crawl_mock),
        patch("src.pipeline.downloader.download_pdf", pdf_mock),
        patch(
            "src.pipeline.downloader.convert_file_to_markdown",
            return_value=FAKE_MARKDOWN,
        ),
    ):
        results = await download_all(
            [sample_source, sample_pdf_source], tmp_settings
        )

    assert len(results) == 2
    assert results[0].success is False
    assert results[1].success is True

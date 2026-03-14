"""Download logic for AMR data sources.

Handles two source types:
- Static HTML sources: Scrapy spider with configurable crawl depth
- PDF sources: httpx download of PDF files to disk

HTML sources are crawled using a generic Scrapy spider that follows
links to configurable depth, filtering subpages by AMR-related keywords.

Reference: SPEC-01, Section 3a.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
import scrapy
from scrapy.crawler import CrawlerProcess
from tenacity import retry, stop_after_attempt, wait_exponential

from src.models import SourceConfig

logger = logging.getLogger(__name__)

USER_AGENT = "AMRPlatformBot/1.0 (educational research)"
REQUEST_TIMEOUT = 60.0
RATE_LIMIT_DELAY = 1.0  # seconds between requests

AMR_KEYWORDS = re.compile(
    r"(?i)\b(AMR|antimicrobial|antibiotic|anti-?infective"
    r"|drug.resistance|resistant.organism)\b"
)


# --- Scrapy Spider ---


class AMRSpider(scrapy.Spider):
    """Generic spider that crawls a source URL to configurable depth.

    Follows links from the start URL, filtering subpages by AMR keywords.
    Skips PDF links and pages outside the source domain.
    """

    name = "amr_spider"

    custom_settings: dict = {
        "DEPTH_LIMIT": 1,
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": RATE_LIMIT_DELAY,
        "USER_AGENT": USER_AGENT,
        "LOG_LEVEL": "WARNING",
        "REQUEST_FINGERPRINTER_IMPLEMENTATION": "2.7",
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
    }

    def __init__(
        self,
        source_config_json: str = "",
        output_dir: str = "",
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        config = json.loads(source_config_json)
        self.source_id: str = config["source_id"]
        self.start_urls = [config["url"]]
        self.allowed_domains = [urlparse(config["url"]).netloc]
        self.custom_settings = {
            **self.custom_settings,
            "DEPTH_LIMIT": config.get("crawl_depth", 1),
        }
        self.output_dir = Path(output_dir)
        self.page_count = 0

    def parse(self, response: scrapy.http.Response) -> scrapy.http.Response:
        """Parse the start page and follow links."""
        self._save_page(response)

        if self.custom_settings.get("DEPTH_LIMIT", 1) <= 1:
            return

        for href in response.css("a::attr(href)").getall():
            url = response.urljoin(href)
            if not url.startswith("http"):
                continue
            if url.lower().endswith(".pdf"):
                continue
            if urlparse(url).netloc not in self.allowed_domains:
                continue
            yield response.follow(href, callback=self.parse_subpage)

    def parse_subpage(self, response: scrapy.http.Response) -> None:
        """Parse a subpage, saving only if it contains AMR keywords."""
        body_text = response.text
        if AMR_KEYWORDS.search(body_text):
            self._save_page(response)
        else:
            logger.debug(
                "Skipping %s (no AMR keywords found)", response.url
            )

    def _save_page(self, response: scrapy.http.Response) -> None:
        """Save response body as an HTML file."""
        self.page_count += 1
        filename = f"{self.source_id}_{self.page_count:04d}.html"
        path = self.output_dir / filename
        path.write_bytes(response.body)
        logger.info("Saved page: %s (%d bytes)", filename, len(response.body))


def _run_spider_subprocess(source_json: str, output_dir: str) -> None:
    """Entry point for the spider subprocess.

    Called via subprocess to avoid Twisted reactor conflicts with asyncio.
    """
    process = CrawlerProcess()
    process.crawl(
        AMRSpider,
        source_config_json=source_json,
        output_dir=output_dir,
    )
    process.start()


async def crawl_html(source: SourceConfig, raw_dir: Path) -> list[Path]:
    """Run Scrapy spider in a subprocess and return list of saved HTML paths.

    Uses a subprocess because Scrapy's Twisted reactor cannot coexist
    with asyncio in the same process.

    Args:
        source: Source configuration with crawl_depth.
        raw_dir: Directory to save raw HTML files.

    Returns:
        List of paths to saved HTML files.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    source_json = source.model_dump_json()

    # Run spider in subprocess to avoid reactor conflicts
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        (
            "import json, sys; "
            "sys.path.insert(0, '.'); "
            "from src.pipeline.scraper import _run_spider_subprocess; "
            f"_run_spider_subprocess({source_json!r}, {str(raw_dir)!r})"
        ),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.warning(
            "Spider subprocess failed for %s (exit %d): %s",
            source.source_id,
            proc.returncode,
            stderr.decode(errors="replace")[:500],
        )
        return []

    # Collect all HTML files written by the spider
    pattern = f"{source.source_id}_*.html"
    pages = sorted(raw_dir.glob(pattern))

    if not pages:
        logger.warning("Spider produced no pages for %s", source.source_id)
    else:
        logger.info(
            "Spider crawled %d pages for %s", len(pages), source.source_id
        )

    return pages


# --- PDF Download ---


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def _fetch_url(url: str, headers: dict[str, str] | None = None) -> httpx.Response:
    """Fetch a URL with retry logic and timeout."""
    default_headers = {"User-Agent": USER_AGENT}
    if headers:
        default_headers.update(headers)
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT, follow_redirects=True
    ) as client:
        response = await client.get(url, headers=default_headers)
        response.raise_for_status()
        return response


async def download_pdf(source: SourceConfig, raw_dir: Path) -> Path | None:
    """Download a PDF file to disk.

    For sources whose URL is a landing page (not a direct PDF link),
    saves the HTML response for Docling to handle.

    Args:
        source: Source configuration.
        raw_dir: Directory to save raw PDF files.

    Returns:
        Path to saved PDF file, or None on failure.
    """
    try:
        url = source.url
        logger.info("Downloading PDF: %s", url)
        response = await _fetch_url(url)

        # Check if we got HTML instead of PDF (landing page)
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            logger.info(
                "Got HTML landing page for %s, saving as HTML for Docling",
                source.source_id,
            )
            output_path = raw_dir / f"{source.source_id}.html"
            output_path.write_text(response.text, encoding="utf-8")
        else:
            output_path = raw_dir / f"{source.source_id}.pdf"
            output_path.write_bytes(response.content)

        logger.info("Saved: %s (%d bytes)", output_path, len(response.content))
        await asyncio.sleep(RATE_LIMIT_DELAY)
        return output_path
    except httpx.HTTPError as e:
        logger.warning("Failed to download PDF for %s: %s", source.source_id, e)
        return None


# --- Dispatcher ---


async def download_raw(
    source: SourceConfig, raw_dir: Path
) -> list[Path] | Path | None:
    """Download raw source content to disk.

    Routes to the appropriate download function based on scraping method.
    Returns a list of paths for HTML (Scrapy) sources, or a single path
    for PDF sources.

    Args:
        source: Source configuration.
        raw_dir: Directory to save raw files.

    Returns:
        List of paths (HTML crawl), single Path (PDF), or None on failure.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)

    if source.scraping_method == "scrapy":
        return await crawl_html(source, raw_dir)

    if source.document_format == "pdf" or source.scraping_method == "docling":
        return await download_pdf(source, raw_dir)

    logger.warning(
        "Unsupported scraping method for %s: %s",
        source.source_id,
        source.scraping_method,
    )
    return None

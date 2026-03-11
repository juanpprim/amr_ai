"""Download logic for AMR data sources.

Handles three source types:
- REST API sources: async httpx calls to PubMed, WHO, etc.
- Static HTML sources: httpx download of web pages
- PDF sources: httpx download of PDF files to disk

All downloads respect rate limits and include proper User-Agent headers.

Reference: SPEC-01, Section 3a.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from xml.etree import ElementTree

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import Settings
from src.models import SourceConfig

logger = logging.getLogger(__name__)

USER_AGENT = "AMRPlatformBot/1.0 (educational research)"
REQUEST_TIMEOUT = 60.0
RATE_LIMIT_DELAY = 1.0  # seconds between requests


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def _fetch_url(url: str, headers: dict | None = None) -> httpx.Response:
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


async def download_html(source: SourceConfig, raw_dir: Path) -> Path | None:
    """Download an HTML page and save to disk.

    Args:
        source: Source configuration.
        raw_dir: Directory to save raw HTML files.

    Returns:
        Path to saved HTML file, or None on failure.
    """
    try:
        logger.info("Downloading HTML: %s", source.url)
        response = await _fetch_url(source.url)
        output_path = raw_dir / f"{source.source_id}.html"
        output_path.write_text(response.text, encoding="utf-8")
        logger.info("Saved HTML: %s (%d chars)", output_path, len(response.text))
        await asyncio.sleep(RATE_LIMIT_DELAY)
        return output_path
    except httpx.HTTPError as e:
        logger.warning("Failed to download HTML for %s: %s", source.source_id, e)
        return None


async def download_pdf(source: SourceConfig, raw_dir: Path) -> Path | None:
    """Download a PDF file to disk.

    For sources whose URL is a landing page (not a direct PDF link),
    attempts to find the actual PDF download URL.

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


async def fetch_pubmed(
    settings: Settings, query: str = "antimicrobial resistance", max_results: int = 100
) -> str | None:
    """Fetch PubMed abstracts via NCBI E-utilities.

    Uses esearch to find PMIDs, then efetch to retrieve abstracts.
    Rate limit: 3 req/s without key, 10/s with PUBMED_API_KEY.

    Args:
        settings: Application settings with API key and email.
        query: PubMed search query.
        max_results: Maximum number of results to fetch.

    Returns:
        Formatted text content with titles and abstracts, or None on failure.
    """
    base_params: dict[str, str] = {
        "db": "pubmed",
        "tool": "AMRPlatformBot",
    }
    if settings.pubmed_email:
        base_params["email"] = settings.pubmed_email
    if settings.pubmed_api_key:
        base_params["api_key"] = settings.pubmed_api_key

    try:
        # Step 1: Search for PMIDs
        search_params = {
            **base_params,
            "term": f"{query}[Title/Abstract]",
            "retmax": str(max_results),
            "sort": "relevance",
            "usehistory": "y",
        }
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            search_resp = await client.get(
                search_url,
                params=search_params,
                headers={"User-Agent": USER_AGENT},
            )
            search_resp.raise_for_status()

        root = ElementTree.fromstring(search_resp.text)
        id_list = root.findall(".//Id")
        pmids = [id_elem.text for id_elem in id_list if id_elem.text]

        if not pmids:
            logger.warning("No PubMed results found for query: %s", query)
            return None

        logger.info("Found %d PubMed articles for '%s'", len(pmids), query)
        await asyncio.sleep(RATE_LIMIT_DELAY)

        # Step 2: Fetch abstracts
        fetch_params = {
            **base_params,
            "id": ",".join(pmids),
            "rettype": "abstract",
            "retmode": "xml",
        }
        fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            fetch_resp = await client.get(
                fetch_url,
                params=fetch_params,
                headers={"User-Agent": USER_AGENT},
            )
            fetch_resp.raise_for_status()

        # Parse XML and extract articles
        articles_root = ElementTree.fromstring(fetch_resp.text)
        articles: list[str] = []

        for article in articles_root.findall(".//PubmedArticle"):
            title_elem = article.find(".//ArticleTitle")
            abstract_elem = article.find(".//AbstractText")
            pmid_elem = article.find(".//PMID")

            title = (
                title_elem.text
                if title_elem is not None and title_elem.text
                else "Untitled"
            )
            abstract = (
                abstract_elem.text
                if abstract_elem is not None and abstract_elem.text
                else ""
            )
            pmid = (
                pmid_elem.text
                if pmid_elem is not None and pmid_elem.text
                else ""
            )

            entry = f"## {title}\n\n**PMID:** {pmid}\n\n{abstract}"
            articles.append(entry)

        content = "# PubMed: Antimicrobial Resistance Research\n\n"
        content += f"Query: {query} | Results: {len(articles)}\n\n---\n\n"
        content += "\n\n---\n\n".join(articles)

        logger.info("Fetched %d PubMed articles", len(articles))
        return content

    except (httpx.HTTPError, ElementTree.ParseError) as e:
        logger.warning("PubMed fetch failed: %s", e)
        return None


async def fetch_api_content(
    source: SourceConfig, settings: Settings
) -> str | None:
    """Fetch content from API sources and format as text.

    Dispatcher for API-type sources. Currently supports PubMed.
    Other API sources return a placeholder.

    Args:
        source: Source configuration.
        settings: Application settings.

    Returns:
        Formatted text content, or None on failure.
    """
    if source.source_id == "pubmed-amr":
        return await fetch_pubmed(settings)

    # For other API sources, fetch raw content and return as text
    try:
        logger.info("Fetching API content: %s", source.url)
        response = await _fetch_url(source.url)
        return response.text
    except httpx.HTTPError as e:
        logger.warning("API fetch failed for %s: %s", source.source_id, e)
        return None


async def download_raw(
    source: SourceConfig, raw_dir: Path, settings: Settings
) -> Path | None:
    """Download raw source content to disk.

    Dispatcher that routes to the appropriate download function
    based on the source's scraping method and document format.

    Args:
        source: Source configuration.
        raw_dir: Directory to save raw files.
        settings: Application settings.

    Returns:
        Path to downloaded file, or None on failure.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)

    if source.scraping_method == "REST_API":
        # API sources are handled separately via fetch_api_content
        content = await fetch_api_content(source, settings)
        if content:
            output_path = raw_dir / f"{source.source_id}.txt"
            output_path.write_text(content, encoding="utf-8")
            return output_path
        return None

    if source.scraping_method == "GitHub_API":
        content = await fetch_api_content(source, settings)
        if content:
            output_path = raw_dir / f"{source.source_id}.txt"
            output_path.write_text(content, encoding="utf-8")
            return output_path
        return None

    if source.document_format == "pdf" or source.scraping_method == "docling":
        return await download_pdf(source, raw_dir)

    if source.document_format == "html" or source.scraping_method == "scrapy":
        return await download_html(source, raw_dir)

    if source.scraping_method == "direct_download":
        return await download_pdf(source, raw_dir)

    logger.warning(
        "Unsupported scraping method for %s: %s",
        source.source_id,
        source.scraping_method,
    )
    return None

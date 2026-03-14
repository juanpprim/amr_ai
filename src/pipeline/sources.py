"""Phase 1 source registry for the AMR data pipeline.

Single source of truth for all sources to be scraped and ingested.
Each source is defined as a SourceConfig with full metadata.

Reference: SPEC-01, Section 1 and Section 4.
"""

from src.models import SourceConfig

PHASE_1_SOURCES: list[SourceConfig] = [
    # --- Static HTML Sources ---
    SourceConfig(
        source_id="who-amr-topics",
        title="WHO Health Topics - Antimicrobial Resistance",
        url="https://www.who.int/health-topics/antimicrobial-resistance",
        organisation="WHO",
        scraping_method="scrapy",
        expertise_level="beginner",
        content_category="learning",
        document_format="html",
        authority_tier=1,
        crawl_depth=2,
    ),
    SourceConfig(
        source_id="cdc-amr-hub",
        title="CDC Antimicrobial Resistance Hub",
        url="https://www.cdc.gov/antimicrobial-resistance/about/index.html",
        organisation="CDC",
        scraping_method="scrapy",
        expertise_level="beginner",
        content_category="learning",
        document_format="html",
        authority_tier=1,
        crawl_depth=2,
    ),
    SourceConfig(
        source_id="fao-amr",
        title="FAO Antimicrobial Resistance",
        url="https://www.fao.org/antimicrobial-resistance/background/what-is-it/en/",
        organisation="FAO",
        scraping_method="scrapy",
        expertise_level="beginner",
        content_category="learning",
        document_format="html",
        authority_tier=1,
        crawl_depth=2,
    ),
    SourceConfig(
        source_id="uk-amr-plan",
        title="UK 5-Year AMR Action Plan 2024-2029",
        url="https://www.gov.uk/government/publications/uk-5-year-action-plan-for-antimicrobial-resistance-2024-to-2029/confronting-antimicrobial-resistance-2024-to-2029",
        organisation="UK Government",
        scraping_method="scrapy",
        expertise_level="intermediate",
        content_category="action_plan",
        document_format="html",
        authority_tier=1,
        crawl_depth=2,
    ),
    SourceConfig(
        source_id="lancet-gram-pmc",
        title="Lancet GRAM Study 2019 (PMC)",
        url="https://pmc.ncbi.nlm.nih.gov/articles/PMC8841637/",
        organisation="The Lancet / PMC",
        scraping_method="scrapy",
        expertise_level="advanced",
        content_category="impact",
        document_format="html",
        authority_tier=2,
        crawl_depth=2,
    ),
    # --- PDF Sources ---
    SourceConfig(
        source_id="who-gap-2015",
        title="WHO Global Action Plan on AMR (2015)",
        url="https://www.who.int/publications/i/item/9789241509763",
        organisation="WHO",
        scraping_method="docling",
        expertise_level="intermediate",
        content_category="action_plan",
        document_format="pdf",
        authority_tier=1,
    ),
    SourceConfig(
        source_id="us-carb-nap",
        title="US CARB National Action Plan 2020-2025",
        url="https://www.hhs.gov/sites/default/files/carb-national-action-plan-2020-2025.pdf",
        organisation="US HHS",
        scraping_method="docling",
        expertise_level="intermediate",
        content_category="action_plan",
        document_format="pdf",
        authority_tier=1,
    ),
    SourceConfig(
        source_id="un-declaration-2024",
        title="UN Political Declaration on AMR (2024)",
        url="https://www.un.org/pga/wp-content/uploads/sites/108/2024/09/FINAL-Text-AMR-to-PGA.pdf",
        organisation="United Nations",
        scraping_method="docling",
        expertise_level="intermediate",
        content_category="action_plan",
        document_format="pdf",
        authority_tier=1,
    ),
    SourceConfig(
        source_id="world-bank-amr",
        title="World Bank - Drug-Resistant Infections: A Threat to Our Economic Future",
        url="https://documents1.worldbank.org/curated/en/323311493396993758/pdf/final-report.pdf",
        organisation="World Bank",
        scraping_method="docling",
        expertise_level="intermediate",
        content_category="impact",
        document_format="pdf",
        authority_tier=1,
    ),
    SourceConfig(
        source_id="cdc-threats-report",
        title="CDC Antibiotic Resistance Threats in the United States",
        url="https://stacks.cdc.gov/view/cdc/82532",
        organisation="CDC",
        scraping_method="docling",
        expertise_level="intermediate",
        content_category="risk",
        document_format="pdf",
        authority_tier=1,
    ),
]


def get_source_by_id(source_id: str) -> SourceConfig | None:
    """Look up a source by its source_id."""
    for source in PHASE_1_SOURCES:
        if source.source_id == source_id:
            return source
    return None


def get_sources_by_method(method: str) -> list[SourceConfig]:
    """Filter sources by scraping method."""
    return [s for s in PHASE_1_SOURCES if s.scraping_method == method]

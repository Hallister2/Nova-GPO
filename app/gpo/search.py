from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

from app.core.log import get_logger
from app.gpo.backup_catalog import BackupCatalogItem, scan_backup_library
from app.gpo.backup_loader import load_gpo_backup
from app.gpo.gpreport_parser import load_gpreport

_log = get_logger(__name__)


@dataclass(frozen=True)
class SearchResult:
    source_index: int
    source_path: str
    backup_name: str
    backup_path: str
    result_type: str
    scope: str
    name: str
    category: str
    value: str
    source_file: str
    # Which displayed fields ("name", "category", "value") actually contain one
    # of the search terms — lets the results table bold the field that matched
    # instead of leaving the reader to guess why a row is here.
    matched_fields: tuple[str, ...] = ()


def search_backup_library(
    roots: list[str],
    query: str,
    limit: int = 1000,
    source_filter: int | None = None,
    type_filter: str = "All Types",
    scope_filter: str = "All Scopes",
    category_filter: str = "All Categories",
    field_filter: str = "All Fields",
    security_only: bool = False,
    exact: bool = False,
    include_descriptions: bool = False,
    progress_callback: Callable[[str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    catalog_items: list[BackupCatalogItem] | None = None,
) -> list[SearchResult]:
    """Search across every backup under `roots`.

    Pass `catalog_items` (e.g. the Backup Library's already-scanned catalog)
    to search that instead of re-walking every backup folder on disk — the
    filesystem walk is redundant if the caller already has a fresh scan.
    `roots` is still required for the "no catalog given" fallback path and
    for progress-message context.
    """
    terms = [term for term in query.lower().split() if term]
    if not terms:
        return []

    results: list[SearchResult] = []

    for catalog_item in _iter_catalog_items(roots, catalog_items, source_filter, should_cancel, progress_callback):
        if should_cancel and should_cancel():
            break
        candidates = _search_backup(
            catalog_item,
            terms,
            limit - len(results),
            field_filter,
            exact,
            include_descriptions,
            should_cancel=should_cancel,
        )
        results.extend([
            result for result in candidates
            if _filter_result(result, type_filter, scope_filter, category_filter, security_only)
        ])
        if len(results) >= limit:
            _log.info("Search '%s': hit limit of %d results", query, limit)
            return results[:limit]

    _log.info("Search '%s': returned %d result(s)", query, len(results))
    return results


def _iter_catalog_items(
    roots: list[str],
    catalog_items: list[BackupCatalogItem] | None,
    source_filter: int | None,
    should_cancel: Callable[[], bool] | None,
    progress_callback: Callable[[str], None] | None,
) -> Iterator[BackupCatalogItem]:
    if catalog_items is not None:
        grouped: dict[int, list[BackupCatalogItem]] = {}
        for item in catalog_items:
            grouped.setdefault(item.source_index, []).append(item)
        source_indexes = sorted(grouped)
        total = len(source_indexes)
        for progress_index, source_index in enumerate(source_indexes, start=1):
            if should_cancel and should_cancel():
                return
            if source_filter is not None and source_filter != source_index:
                continue
            if progress_callback:
                progress_callback(f"Searching source {source_index} of {total}...")
            for item in grouped[source_index]:
                if should_cancel and should_cancel():
                    return
                if progress_callback:
                    progress_callback(f"Searching {item.display_name}...")
                yield item
        return

    for source_index, root in enumerate(roots, start=1):
        if should_cancel and should_cancel():
            return
        if source_filter is not None and source_filter != source_index:
            continue
        if progress_callback:
            progress_callback(f"Searching source {source_index} of {len(roots)}...")
        for item in scan_backup_library(root, source_index=source_index, should_cancel=should_cancel):
            if should_cancel and should_cancel():
                return
            if progress_callback:
                progress_callback(f"Searching {item.display_name}...")
            yield item


def _search_backup(
    catalog_item,
    terms: list[str],
    remaining: int,
    field_filter: str = "All Fields",
    exact: bool = False,
    include_descriptions: bool = False,
    should_cancel: Callable[[], bool] | None = None,
) -> list[SearchResult]:
    if remaining <= 0:
        return []
    if should_cancel and should_cancel():
        return []

    results: list[SearchResult] = []

    if _matches(terms, catalog_item.display_name, catalog_item.domain, catalog_item.path, exact=exact):
        results.append(
            SearchResult(
                source_index=catalog_item.source_index,
                source_path=catalog_item.source_path,
                backup_name=catalog_item.display_name,
                backup_path=catalog_item.path,
                result_type="GPO Backup",
                scope="Backup",
                name=catalog_item.display_name,
                category=catalog_item.domain or "Not reported",
                value=catalog_item.detail,
                source_file="",
                matched_fields=_term_hit_fields(
                    terms, name=catalog_item.display_name, category=catalog_item.domain or ""
                ),
            )
        )

    try:
        backup = load_gpo_backup(catalog_item.path)
    except Exception:
        return results

    report = load_gpreport(catalog_item.path)
    if report:
        for policy in report.policies:
            if should_cancel and should_cancel():
                return results
            if len(results) >= remaining:
                return results

            if not _matches(
                terms,
                *_search_values_for_policy(policy, field_filter, include_descriptions),
                exact=exact,
            ):
                continue

            policy_value = "; ".join(policy.settings) or policy.state
            results.append(
                SearchResult(
                    source_index=catalog_item.source_index,
                    source_path=catalog_item.source_path,
                    backup_name=backup.name,
                    backup_path=backup.path,
                    result_type=policy.policy_type,
                    scope=policy.scope,
                    name=policy.name,
                    category=policy.category,
                    value=policy_value,
                    source_file=policy.source,
                    matched_fields=_term_hit_fields(
                        terms, name=policy.name, category=policy.category, value=policy_value
                    ),
                )
            )

    for setting in backup.settings:
        if should_cancel and should_cancel():
            return results
        if len(results) >= remaining:
            return results

        # Backup Metadata (GPO GUID, domain, comment) already surfaces at the
        # GPO Backup result level — exclude here to avoid domain-name noise.
        if setting.category == "Backup Metadata":
            continue

        if not _matches(
            terms,
            *_search_values_for_setting(setting, field_filter),
            exact=exact,
        ):
            continue

        results.append(
            SearchResult(
                source_index=catalog_item.source_index,
                source_path=catalog_item.source_path,
                backup_name=backup.name,
                backup_path=backup.path,
                result_type="Artifact",
                scope=_scope_from_source(setting.source_file),
                name=setting.name,
                category=setting.category,
                value=setting.value,
                source_file=setting.source_file,
                matched_fields=_term_hit_fields(
                    terms, name=setting.name, category=setting.category, value=setting.value
                ),
            )
        )

    return results


def _term_hit_fields(terms: list[str], **named_values: str) -> tuple[str, ...]:
    """Which of the given named fields contain at least one search term.

    This is a lighter-weight check than `_matches` (any term, not all terms,
    and no `exact` phrase handling) — it's a display hint for which field(s)
    to bold in the results table, not a re-verification of the match itself.
    """
    hits = []
    for field_name, value in named_values.items():
        text = (value or "").lower()
        if any(term in text for term in terms):
            hits.append(field_name)
    return tuple(hits)


def _matches(terms: list[str], *values: str, exact: bool = False) -> bool:
    haystack = " ".join(value or "" for value in values).lower()
    if exact:
        needle = " ".join(terms)
        return needle in haystack
    return all(term in haystack for term in terms)


def _filter_result(
    result: SearchResult,
    type_filter: str,
    scope_filter: str,
    category_filter: str = "All Categories",
    security_only: bool = False,
) -> bool:
    if type_filter != "All Types" and result.result_type != type_filter:
        return False

    if scope_filter != "All Scopes" and result.scope != scope_filter:
        return False

    if category_filter != "All Categories" and category_filter.lower() not in result.category.lower():
        return False

    if security_only and not _is_security_result(result):
        return False

    return True


def _is_security_result(result: SearchResult) -> bool:
    text = " ".join(
        [
            result.result_type,
            result.scope,
            result.name,
            result.category,
            result.value,
            result.source_file,
        ]
    ).lower()
    return any(
        token in text
        for token in (
            "security",
            "password",
            "lockout",
            "kerberos",
            "audit",
            "privilege",
            "firewall",
            "applocker",
            "defender",
            "administrator",
        )
    )


def _search_values_for_policy(policy, field_filter: str, include_descriptions: bool = False) -> list[str]:
    if field_filter == "Values Only":
        return [" ".join(policy.settings), policy.state]
    if field_filter == "Names Only":
        return [policy.name]
    if field_filter == "Paths/Categories":
        return [policy.category, policy.scope, policy.source]
    values = [
        policy.name,
        policy.state,
        policy.policy_type,
        policy.category,
        policy.scope,
        policy.source,
        " ".join(policy.settings),
    ]
    if include_descriptions:
        # policy.explain is Microsoft's boilerplate help text for the setting —
        # common words there (e.g. "desktop") drown results in unrelated
        # policies that just happen to mention the word in a paragraph of
        # documentation, so it's opt-in rather than part of the default search.
        values.append(policy.explain)
    return values


def _search_values_for_setting(setting, field_filter: str) -> list[str]:
    if field_filter == "Values Only":
        return [setting.value]
    if field_filter == "Names Only":
        return [setting.key, setting.name]
    if field_filter == "Paths/Categories":
        return [setting.category, setting.source_file]
    return [
        setting.key,
        setting.category,
        setting.name,
        setting.value,
        setting.source_file,
    ]


def _scope_from_source(source_file: str) -> str:
    normalized = source_file.replace("\\", "/").lower()
    if "/user/" in f"/{normalized}/":
        return "User Configuration"
    if "/machine/" in f"/{normalized}/" or "/computer/" in f"/{normalized}/":
        return "Computer Configuration"
    return "Artifacts"

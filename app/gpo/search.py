from __future__ import annotations

from dataclasses import dataclass

from app.core.log import get_logger
from app.gpo.backup_catalog import scan_backup_library
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


def search_backup_library(
    roots: list[str],
    query: str,
    limit: int = 1000,
    source_filter: int | None = None,
    type_filter: str = "All Types",
    scope_filter: str = "All Scopes",
    exact: bool = False,
) -> list[SearchResult]:
    terms = [term for term in query.lower().split() if term]
    if not terms:
        return []

    results: list[SearchResult] = []

    for source_index, root in enumerate(roots, start=1):
        if source_filter is not None and source_filter != source_index:
            continue

        for catalog_item in scan_backup_library(root, source_index=source_index):
            candidates = _search_backup(catalog_item, terms, limit - len(results), exact)
            results.extend([
                result for result in candidates
                if _filter_result(result, type_filter, scope_filter)
            ])
            if len(results) >= limit:
                _log.info("Search '%s': hit limit of %d results", query, limit)
                return results[:limit]

    _log.info("Search '%s': returned %d result(s)", query, len(results))
    return results


def _search_backup(catalog_item, terms: list[str], remaining: int, exact: bool = False) -> list[SearchResult]:
    if remaining <= 0:
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
            )
        )

    try:
        backup = load_gpo_backup(catalog_item.path)
    except Exception:
        return results

    report = load_gpreport(catalog_item.path)
    if report:
        for policy in report.policies:
            if len(results) >= remaining:
                return results

            if not _matches(
                terms,
                policy.name,
                policy.state,
                policy.policy_type,
                policy.category,
                policy.scope,
                policy.source,
                policy.explain,
                " ".join(policy.settings),
                exact=exact,
            ):
                continue

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
                    value="; ".join(policy.settings) or policy.state,
                    source_file=policy.source,
                )
            )

    for setting in backup.settings:
        if len(results) >= remaining:
            return results

        # Backup Metadata (GPO GUID, domain, comment) already surfaces at the
        # GPO Backup result level — exclude here to avoid domain-name noise.
        if setting.category == "Backup Metadata":
            continue

        if not _matches(
            terms,
            setting.key,
            setting.category,
            setting.name,
            setting.value,
            setting.source_file,
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
            )
        )

    return results


def _matches(terms: list[str], *values: str, exact: bool = False) -> bool:
    haystack = " ".join(value or "" for value in values).lower()
    if exact:
        needle = " ".join(terms)
        return needle in haystack
    return all(term in haystack for term in terms)


def _filter_result(result: SearchResult, type_filter: str, scope_filter: str) -> bool:
    if type_filter != "All Types" and result.result_type != type_filter:
        return False

    if scope_filter != "All Scopes" and result.scope != scope_filter:
        return False

    return True


def _scope_from_source(source_file: str) -> str:
    normalized = source_file.replace("\\", "/").lower()
    if "/user/" in f"/{normalized}/":
        return "User Configuration"
    if "/machine/" in f"/{normalized}/" or "/computer/" in f"/{normalized}/":
        return "Computer Configuration"
    return "Artifacts"

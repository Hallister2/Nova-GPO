from __future__ import annotations

from app.gpo.gpo_model import DiffStatus, GpoBackup, GpoDiffItem, GpoSetting

# Maps semantically equivalent boolean/toggle strings to a canonical form so
# that "Enabled" vs "1" vs "true" do not produce false change entries.
_BOOL_CANONICAL: dict[str, str] = {
    "0": "0", "false": "0", "no": "0", "disabled": "0", "off": "0",
    "1": "1", "true": "1",  "yes": "1", "enabled": "1",  "on": "1",
}


def _normalize_value(value: str) -> str:
    """Return a canonical form of *value* for semantic comparison."""
    stripped = (value or "").strip()
    canonical = _BOOL_CANONICAL.get(stripped.lower())
    if canonical is not None:
        return canonical
    try:
        return str(int(stripped))
    except ValueError:
        return stripped.lower()


def compare_backups(old_backup: GpoBackup, new_backup: GpoBackup) -> list[GpoDiffItem]:
    old_map = _to_map(old_backup.settings)
    new_map = _to_map(new_backup.settings)

    all_keys = sorted(set(old_map) | set(new_map))
    diff_items: list[GpoDiffItem] = []

    for key in all_keys:
        old_item = old_map.get(key)
        new_item = new_map.get(key)

        if old_item is None and new_item is not None:
            diff_items.append(
                GpoDiffItem(
                    status=DiffStatus.ADDED,
                    key=key,
                    category=new_item.category,
                    name=new_item.name,
                    old_value="",
                    new_value=new_item.value,
                )
            )
            continue

        if old_item is not None and new_item is None:
            diff_items.append(
                GpoDiffItem(
                    status=DiffStatus.REMOVED,
                    key=key,
                    category=old_item.category,
                    name=old_item.name,
                    old_value=old_item.value,
                    new_value="",
                )
            )
            continue

        if old_item is None or new_item is None:
            continue

        if _normalize_value(old_item.value) != _normalize_value(new_item.value):
            diff_items.append(
                GpoDiffItem(
                    status=DiffStatus.CHANGED,
                    key=key,
                    category=new_item.category,
                    name=new_item.name,
                    old_value=old_item.value,
                    new_value=new_item.value,
                )
            )
        else:
            diff_items.append(
                GpoDiffItem(
                    status=DiffStatus.UNCHANGED,
                    key=key,
                    category=new_item.category,
                    name=new_item.name,
                    old_value=old_item.value,
                    new_value=new_item.value,
                )
            )

    return diff_items


def _to_map(settings: list[GpoSetting]) -> dict[str, GpoSetting]:
    return {setting.key: setting for setting in settings}
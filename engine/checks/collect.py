from core.config import Settings
from core.config import read_json_if_exists


def check_collect(settings: Settings, run_info: dict) -> list[str]:
    items_file = read_json_if_exists("items.json")
    if items_file is None:
        return ["items: items.json not found"]
    approved = {source["id"] for source in settings.sources}
    errors = []
    for index, item in enumerate(items_file["items"]):
        if item.get("source") not in approved:
            errors.append(f"items: items[{index}] comes from `{item.get('source')}`, not an approved connection")
        if not run_info["since"] <= str(item.get("date")) <= run_info["until"]:
            errors.append(f"items: items[{index}] is dated {item.get('date')}, outside the window")
    return errors

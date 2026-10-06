import json
from pathlib import Path

LOCALES = {
    lang: json.loads((Path(__file__).parent.parent / "locales" / f"{lang}.json").read_text())
    for lang in ("ar", "en")
}


def tr(language, key, **values):
    return (
        LOCALES.get(language, LOCALES["ar"]).get(key, LOCALES["ar"].get(key, key)).format(**values)
    )

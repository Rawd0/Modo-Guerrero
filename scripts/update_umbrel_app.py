"""Actualiza la ficha de Umbrel con una nueva versión (lo usa la acción de release).

Uso: python scripts/update_umbrel_app.py <version> <imagen@sha256:...> <archivo-con-notas>
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "modo-guerrero-app"


def main(version: str, image: str, notes_file: str):
    notes = Path(notes_file).read_text(encoding="utf-8").strip() or f"Versión {version}."
    notes_block = "\n".join("  " + line if line.strip() else "" for line in notes.splitlines())

    compose = APP / "docker-compose.yml"
    c = compose.read_text(encoding="utf-8")
    c = re.sub(r"^(\s*image:\s*).*$", lambda m: m.group(1) + image, c, count=1, flags=re.M)
    compose.write_text(c, encoding="utf-8")

    manifest = APP / "umbrel-app.yml"
    m = manifest.read_text(encoding="utf-8")
    m = re.sub(r'^version:.*$', f'version: "{version}"', m, count=1, flags=re.M)
    m = re.sub(r"^releaseNotes: >-\n(?:(?:  .*)?\n)*?(?=^\S)", f"releaseNotes: >-\n{notes_block}\n", m, count=1, flags=re.M)
    manifest.write_text(m, encoding="utf-8")
    print(f"Ficha actualizada a {version} ({image})")


if __name__ == "__main__":
    main(*sys.argv[1:4])

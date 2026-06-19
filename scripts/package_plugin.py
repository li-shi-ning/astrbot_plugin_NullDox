from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PLUGIN_ROOT / "dist"
EXCLUDED_DIRS = {
    ".git",
    ".idea",
    ".omx",
    ".pytest_cache",
    "__pycache__",
    "dist",
    "scripts",
    "tests",
}
EXCLUDED_FILES = {
    ".gitignore",
    "CONSTRAINTS.md",
    ".env",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Package this AstrBot plugin into a local-install zip.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output zip path. Defaults to dist/<plugin-name>-<version>.zip.",
    )
    args = parser.parse_args()

    output_path = args.output or default_output_path()
    package_plugin(output_path)
    print(output_path)
    return 0


def default_output_path() -> Path:
    plugin_name, version = read_metadata_name_and_version()
    safe_version = version.replace("/", "-").replace("\\", "-")
    return DEFAULT_OUTPUT_DIR / f"{plugin_name}-{safe_version}.zip"


def read_metadata_name_and_version() -> tuple[str, str]:
    metadata_path = PLUGIN_ROOT / "metadata.yaml"
    name = ""
    version = ""
    for line in metadata_path.read_text(encoding="utf-8").splitlines():
        line = line.lstrip("\ufeff")
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("version:"):
            version = line.split(":", 1)[1].strip()
    if not name or not version:
        raise RuntimeError("metadata.yaml must contain name and version.")
    return name, version


def package_plugin(output_path: Path) -> Path:
    package_files = list_package_files()
    if not package_files:
        raise RuntimeError("No plugin files found.")

    plugin_name, _ = read_metadata_name_and_version()
    package_root = plugin_name.strip().strip("/\\")
    if not package_root:
        raise RuntimeError("metadata.yaml must contain a valid plugin name.")

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # AstrBot v4.22.x expects the first zip entry to be a directory.
        zf.writestr(f"{package_root}/", "")
        for relative_path in package_files:
            source_path = PLUGIN_ROOT / relative_path
            archive_name = f"{package_root}/{relative_path.as_posix()}"
            zf.write(source_path, archive_name)
    return output_path


def list_package_files() -> list[Path]:
    files: list[Path] = []
    for path in PLUGIN_ROOT.rglob("*"):
        relative_path = path.relative_to(PLUGIN_ROOT)
        if should_skip(relative_path, path):
            continue
        if path.is_file():
            files.append(relative_path)
    return sorted(files, key=lambda item: item.as_posix())


def should_skip(relative_path: Path, path: Path) -> bool:
    parts = set(relative_path.parts)
    if parts & EXCLUDED_DIRS:
        return True
    if relative_path.name in EXCLUDED_FILES:
        return True
    if path.is_dir():
        return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())

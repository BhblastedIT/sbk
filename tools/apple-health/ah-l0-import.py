#!/usr/bin/env python3
"""Apple Health import: unpacks the export.zip you export from the Health app on the iPhone (the latest one found,
or --file) and keeps the export.xml for ah-l1-process.py.
"""

import argparse
import logging
import sys
import zipfile
from pathlib import Path

from dotenv import load_dotenv



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

load_dotenv(_TOOLS_DIR.parent / ".env", override=True)

from sbk_config import (  # noqa: E402
    APPLE_HEALTH_IMPORTS_DIR,
    APPLE_HEALTH_RAW_DIR,
    mark_last_run,
)

log = logging.getLogger("ah-l0")


def find_latest_zip(imports_dir: Path) -> Path | None:
    ""
    zips = sorted(imports_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    return zips[0] if zips else None


def extract_zip(zip_path: Path, raw_dir: Path) -> Path:
    ""




    raw_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:

        xml_members = [m for m in zf.namelist() if m.endswith("export.xml")]
        if not xml_members:
            raise FileNotFoundError(f"No export.xml found in {zip_path}")


        xml_member = xml_members[0]
        log.info("Extracting %s from %s", xml_member, zip_path.name)

        content = zf.read(xml_member)
        output_path = raw_dir / "export.xml"
        output_path.write_bytes(content)


        cda_members = [m for m in zf.namelist() if m.endswith("export_cda.xml")]
        if cda_members:
            cda_content = zf.read(cda_members[0])
            (raw_dir / "export_cda.xml").write_bytes(cda_content)

    log.info("Extracted to %s (%d bytes)", output_path, len(content))
    return output_path


def import_health_data(
    file_path: Path | None = None,
    imports_dir: Path | None = None,
    raw_dir: Path | None = None,
) -> Path | None:
    ""









    imp_dir = imports_dir or APPLE_HEALTH_IMPORTS_DIR
    out_dir = raw_dir or APPLE_HEALTH_RAW_DIR

    if file_path:
        zip_path = Path(file_path)
    else:
        zip_path = find_latest_zip(imp_dir)

    if not zip_path or not zip_path.exists():
        log.warning("No Apple Health ZIP file found in %s", imp_dir)
        return None

    log.info("Importing %s", zip_path.name)
    xml_path = extract_zip(zip_path, out_dir)
    mark_last_run("apple-health")
    return xml_path


def main():
    parser = argparse.ArgumentParser(description="Apple Health import — SBK")
    parser.add_argument("--file", type=str, help="Specific ZIP file path")
    parser.add_argument("--keep-raw", action="store_true", help="Keep extracted XML")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    file_path = Path(args.file) if args.file else None
    xml_path = import_health_data(file_path=file_path)

    if xml_path:
        size_mb = xml_path.stat().st_size / (1024 * 1024)
        print("\nApple Health import complete:")
        print(f"  XML: {xml_path} ({size_mb:.1f} MB)")
        print("  Next: run ah-l1-process.py to generate metrics.parquet")
    else:
        print("No ZIP file found. Place export ZIP in ~/.sbk-data/apple-health/imports/")


if __name__ == "__main__":
    main()

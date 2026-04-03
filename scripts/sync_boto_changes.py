import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests

CONFIG = {
    "BOTO_REPO": "https://github.com/boto/botocore.git",
    "CLONE_DIR": Path("botocore_repo"),
    "CHANGES_DIR": Path("botocore_repo/.changes"),
    "OUTPUT_DIR": Path("public/data"),
}

VERSIONS_DIR = CONFIG["OUTPUT_DIR"] / "versions"
SERVICES_DIR = CONFIG["OUTPUT_DIR"] / "services"
TRACK_JSON = CONFIG["OUTPUT_DIR"] / "track.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

class BotoSync:
    def __init__(self):
        self.session = requests.Session()
        self.pypi_dates: Dict[str, str] = {}
        self.existing_services: Set[str] = set()
        self.existing_versions: List[Dict[str, Any]] = []

    @staticmethod
    def format_id(name: str) -> str:
        if not name:
            return "unknown"
        name = name.replace("`", "").lower().strip()
        name = re.sub(r"[\._\s]", "-", name)
        name = re.sub(r"-+", "-", name)
        return name.strip("-")

    @staticmethod
    def version_key(version_str: str) -> tuple:
        try:
            return tuple(map(int, version_str.split(".")))
        except (ValueError, AttributeError):
            return (0, 0, 0)

    def load_json(self, path: Path, default: Any = None) -> Any:
        if not path.exists():
            return default if default is not None else {}
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load {path}: {e}")
            return default if default is not None else {}

    def save_json(self, path: Path, data: Any):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save {path}: {e}")

    def fetch_pypi_dates(self):
        logger.info("Fetching release dates from PyPI...")
        try:
            r = self.session.get("https://pypi.org/pypi/botocore/json", timeout=15)
            r.raise_for_status()
            data = r.json()
            for version, releases in data.get("releases", {}).items():
                if releases and (upload_time := releases[0].get("upload_time")):
                    self.pypi_dates[version] = upload_time.split("T")[0]
        except Exception as e:
            logger.warning(f"Could not fetch PyPI dates: {e}")

    def ensure_repository(self):
        if CONFIG["CLONE_DIR"].exists():
            logger.info("Updating existing repository...")
            try:
                subprocess.run(["git", "-C", str(CONFIG["CLONE_DIR"]), "pull"], check=True, capture_output=True)
            except subprocess.CalledProcessError:
                logger.warning("Update failed, re-cloning...")
                shutil.rmtree(CONFIG["CLONE_DIR"])
                self._clone_repo()
        else:
            self._clone_repo()

    def _clone_repo(self):
        logger.info(f"Cloning {CONFIG['BOTO_REPO']}...")
        subprocess.run(["git", "clone", "--depth", "1", CONFIG["BOTO_REPO"], str(CONFIG["CLONE_DIR"])], check=True)

    def process_new_versions(self) -> List[Dict[str, Any]]:
        processed_ids = {v["id"] for v in self.existing_versions}
        
        all_files = list(CONFIG["CHANGES_DIR"].glob("*.json"))
        new_files = [f for f in all_files if f.stem not in processed_ids]
        
        if not new_files:
            return []

        new_files.sort(key=lambda x: self.version_key(x.stem))
        logger.info(f"Processing {len(new_files)} new versions...")

        new_entries = []
        affected_services: Dict[str, List[Dict]] = {}

        for file_path in new_files:
            version = file_path.stem
            data = self.load_json(file_path, default=[])
            
            processed_changes = []
            for change in data:
                category = self.format_id(change.get("category", "unknown"))
                desc = change.get("description", "")
                ctype = change.get("type", "api-change")

                self.existing_services.add(category)
                processed_changes.append({"category": category, "description": desc, "type": ctype})

                affected_services.setdefault(category, []).append({"v": version, "t": desc})

            self.save_json(VERSIONS_DIR / f"{version}.json", processed_changes)
            new_entries.append({"id": version, "date": self.pypi_dates.get(version)})

        self._update_service_files(affected_services)
        return new_entries

    def _update_service_files(self, affected_services: Dict[str, List[Dict]]):
        for service, new_logs in affected_services.items():
            service_path = SERVICES_DIR / f"{service}.json"
            history = self.load_json(service_path, default=[])
            
            existing_v = {item["v"] for item in history}
            filtered_new = [e for e in new_logs if e["v"] not in existing_v]
            
            if filtered_new:
                updated = filtered_new + history
                updated.sort(key=lambda x: self.version_key(x["v"]), reverse=True)
                self.save_json(service_path, updated)

    def run(self):
        VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
        SERVICES_DIR.mkdir(parents=True, exist_ok=True)

        self.fetch_pypi_dates()
        self.ensure_repository()

        track_data = self.load_json(TRACK_JSON)
        self.existing_versions = track_data.get("versions", [])
        self.existing_services = set(track_data.get("allServices", []))

        for v in self.existing_versions:
            if not v.get("date"):
                v["date"] = self.pypi_dates.get(v["id"])

        new_versions = self.process_new_versions()
        
        combined = new_versions + self.existing_versions
        combined.sort(key=lambda x: self.version_key(x["id"]), reverse=True)

        self.save_json(TRACK_JSON, {
            "versions": combined,
            "allServices": sorted(list(self.existing_services))
        })

        logger.info(f"Sync complete. Added {len(new_versions)} versions.")

if __name__ == "__main__":
    BotoSync().run()

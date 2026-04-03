import os
import json
import re
import shutil
import subprocess
import requests
from pathlib import Path

BOTO_REPO = "https://github.com/boto/botocore.git"
CLONE_DIR = "botocore_repo"
CHANGES_DIR = "botocore_repo/.changes"
OUTPUT_DIR = "public/data"
VERSIONS_DIR = os.path.join(OUTPUT_DIR, "versions")
SERVICES_DIR = os.path.join(OUTPUT_DIR, "services")

def format_id(name):
    if not name:
        return "unknown"
    name = name.replace("`", "").lower().strip()
    name = re.sub(r'[\._\s]', '-', name)
    name = re.sub(r'-+', '-', name)
    name = name.strip('-')
    return name

def version_key(version_str):
    try:
        return tuple(map(int, version_str.split('.')))
    except ValueError:
        return (0, 0, 0)

def get_pypi_release_dates():
    """Fetch all release dates for botocore from PyPI."""
    print("Fetching release dates from PyPI...")
    try:
        response = requests.get("https://pypi.org/pypi/botocore/json", timeout=15)
        response.raise_for_status()
        data = response.json()
        dates = {}
        for version, releases in data.get("releases", {}).items():
            if releases:
                # Use the upload time of the first artifact as the release date
                upload_time = releases[0].get("upload_time")
                if upload_time:
                    dates[version] = upload_time.split("T")[0]
        return dates
    except Exception as e:
        print(f"Warning: Could not fetch release dates from PyPI: {e}")
        return {}

def sync():
    os.makedirs(VERSIONS_DIR, exist_ok=True)
    os.makedirs(SERVICES_DIR, exist_ok=True)

    # Fetch release dates
    pypi_dates = get_pypi_release_dates()

    if os.path.exists(CLONE_DIR):
        print(f"Updating existing repository in {CLONE_DIR}...")
        try:
            subprocess.run(["git", "-C", CLONE_DIR, "pull"], check=True)
        except subprocess.CalledProcessError:
            print("Update failed, re-cloning...")
            shutil.rmtree(CLONE_DIR)
            subprocess.run(["git", "clone", "--depth", "1", BOTO_REPO, CLONE_DIR], check=True)
    else:
        print(f"Cloning {BOTO_REPO}...")
        subprocess.run(["git", "clone", "--depth", "1", BOTO_REPO, CLONE_DIR], check=True)

    if not os.path.exists(CHANGES_DIR):
        print("Error: .changes directory not found.")
        return

    track_path = os.path.join(OUTPUT_DIR, "track.json")
    existing_versions = []
    existing_services = set()
    if os.path.exists(track_path):
        with open(track_path, 'r') as f:
            try:
                track_data = json.load(f)
                existing_versions = track_data.get("versions", [])
                existing_services = set(track_data.get("allServices", []))
            except Exception as e:
                print(f"Warning: Could not parse track.json: {e}")

    # Update existing versions with dates if they are missing
    for v in existing_versions:
        if "date" not in v:
            v["date"] = pypi_dates.get(v["id"])

    processed_version_ids = {v["id"] for v in existing_versions}

    all_change_files = [f for f in os.listdir(CHANGES_DIR) if f.endswith(".json")]
    new_files = [f for f in all_change_files if f.replace(".json", "") not in processed_version_ids]
    
    if not new_files:
        print("No new versions to sync, but updated existing dates if necessary.")
        # Even if no new versions, save if we added dates to existing ones
        track_data = {
            "versions": existing_versions,
            "allServices": sorted(list(existing_services))
        }
        with open(track_path, 'w') as f:
            json.dump(track_data, f, indent=2)
        return

    new_files.sort(key=lambda x: version_key(x.replace(".json", "")))
    print(f"Processing {len(new_files)} new versions...")

    newly_processed_versions = []
    affected_services = {}

    for filename in new_files:
        version = filename.replace(".json", "")
        file_path = os.path.join(CHANGES_DIR, filename)
        
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            print(f"Skipping {filename}: {e}")
            continue

        newly_processed_versions.append({
            "id": version,
            "date": pypi_dates.get(version)
        })
        processed_changes = []

        for change in data:
            category = format_id(change.get("category", "unknown"))
            description = change.get("description", "")
            change_type = change.get("type", "api-change")

            existing_services.add(category)
            
            processed_changes.append({
                "category": category,
                "description": description,
                "type": change_type
            })

            if category not in affected_services:
                affected_services[category] = []
            
            affected_services[category].append({
                "v": version,
                "t": description
            })

        v_file_path = os.path.join(VERSIONS_DIR, f"{version}.json")
        if not os.path.exists(v_file_path):
            with open(v_file_path, 'w') as f:
                json.dump(processed_changes, f, indent=2)

    updated_count = 0
    for service, new_entries in affected_services.items():
        service_file = os.path.join(SERVICES_DIR, f"{service}.json")
        
        history = []
        if os.path.exists(service_file):
            with open(service_file, 'r') as f:
                try:
                    history = json.load(f)
                except:
                    history = []

        existing_v = {item["v"] for item in history}
        filtered_new_entries = [e for e in new_entries if e["v"] not in existing_v]
        
        if not filtered_new_entries:
            continue

        filtered_new_entries.sort(key=lambda x: version_key(x["v"]), reverse=True)
        updated_history = filtered_new_entries + history
        
        with open(service_file, 'w') as f:
            json.dump(updated_history, f, indent=2)
        updated_count += 1
    
    if updated_count > 0:
        print(f"Updated {updated_count} service history files.")

    newly_processed_versions.sort(key=lambda x: version_key(x["id"]), reverse=True)
    combined_versions = newly_processed_versions + existing_versions
    
    track_data = {
        "versions": combined_versions,
        "allServices": sorted(list(existing_services))
    }
    with open(track_path, 'w') as f:
        json.dump(track_data, f, indent=2)

    print(f"Sync complete. Added {len(new_files)} versions.")

if __name__ == "__main__":
    sync()

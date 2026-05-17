import json
import csv
import requests
from datetime import datetime
from pathlib import Path

# Configuration
INDEX_URL = "https://download.geofabrik.de/index-v1.json"
TAG_NAME = "name:etymology:wikidata"
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def fetch_index():
    """Fetch the GeoFabrik index."""
    print(f"Fetching index from {INDEX_URL}...")
    response = requests.get(INDEX_URL)
    response.raise_for_status()
    return response.json()


def fetch_tag_stats(taginfo_url, tag):
    """Fetch tag statistics for a specific area."""
    url = f"{taginfo_url}/api/4/key/stats?key={tag}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None


def extract_stats(stats_data):
    """Extract relevant statistics from the API response."""
    if not stats_data or "data" not in stats_data or not stats_data["data"]:
        return None

    data = stats_data["data"][0]
    return {
        "count": data.get("count", 0),
        "nodes": data.get("nodes", 0),
        "ways": data.get("ways", 0),
        "relations": data.get("relations", 0),
    }


def process_areas(index):
    """Process all areas and collect statistics."""
    results = []

    # Extract all areas from the index
    areas = index.get("features", [])
    print(f"Found {len(areas)} areas in the index\n")

    for idx, feature in enumerate(areas, 1):
        props = feature.get("properties", {})
        area_name = props.get("name", "Unknown")
        area_id = props.get("id", "unknown")

        # Get taginfo URL
        urls = props.get("urls", {})
        taginfo_url = urls.get("taginfo", "")

        if not taginfo_url:
            print(f"[{idx}/{len(areas)}] {area_name}: No taginfo URL available")
            continue

        # Remove trailing slash if present
        taginfo_url = taginfo_url.rstrip("/")

        print(f"[{idx}/{len(areas)}] {area_name}: Fetching statistics...")

        # Fetch statistics
        stats_data = fetch_tag_stats(taginfo_url, TAG_NAME)
        stats = extract_stats(stats_data)

        if stats:
            result = {
                "area": area_name,
                "area_id": area_id,
                "taginfo_url": taginfo_url,
                "count": stats["count"],
                "nodes": stats["nodes"],
                "ways": stats["ways"],
                "relations": stats["relations"],
            }
            results.append(result)
            print(f"  ✓ Count: {stats['count']}")
        else:
            print(f"  ✗ No data available")

    return results


def save_json(data, filepath):
    """Save results to JSON file."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\nSaved JSON to: {filepath}")


def save_csv(data, filepath):
    """Save results to CSV file."""
    if not data:
        return

    fieldnames = [
        "area",
        "area_id",
        "taginfo_url",
        "count",
        "nodes",
        "ways",
        "relations",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    print(f"Saved CSV to: {filepath}")


def main():
    """Main function."""
    print(f"Fetching statistics for tag: {TAG_NAME}\n")

    try:
        # Fetch index
        index = fetch_index()

        # Process all areas
        results = process_areas(index)

        # Sort by count (descending)
        results.sort(key=lambda x: x["count"], reverse=True)

        # Generate filenames with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_file = (
            OUTPUT_DIR / f"tag_stats_{TAG_NAME.replace(':', '_')}_{timestamp}.json"
        )
        csv_file = (
            OUTPUT_DIR / f"tag_stats_{TAG_NAME.replace(':', '_')}_{timestamp}.csv"
        )

        # Save results
        save_json(results, json_file)
        save_csv(results, csv_file)

        # Print summary
        total_count = sum(r["count"] for r in results)
        print(f"\nSummary:")
        print(f"  Total areas processed: {len(results)}")
        print(f"  Total occurrences: {total_count}")
        print(f"\nTop 10 areas:")
        for idx, result in enumerate(results[:10], 1):
            print(f"  {idx}. {result['area']}: {result['count']}")

    except Exception as e:
        print(f"Error: {e}")
        raise


if __name__ == "__main__":
    main()

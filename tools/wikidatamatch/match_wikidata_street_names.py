#!/usr/bin/env python3
"""Compare Wikidata street-name origins with OSM ways and create a JOSM change file."""

# This script finds Wikidata roads, streets, and squares in a municipality,
# matches their names against local OSM ways, and proposes name:etymology:wikidata
# tags for matching ways. Network results and local OSM extraction are cached so
# the workflow can be repeated politely and reviewed before uploading in JOSM.

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

try:
    import osmium
except ImportError:  # pragma: no cover - gives a useful CLI error instead
    osmium = None

try:
    import requests
except ImportError:  # pragma: no cover - gives a useful CLI error instead
    requests = None


WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "OSMToolsWikidataStreetMatch/1.0 (https://github.com/PeterBrodersen/osmtools)"
WIKIDATA_TYPES = ("Q34442", "Q79007", "Q174782")
RETRY_COUNT = 5


class OsmWayHandler(osmium.SimpleHandler if osmium else object):
    """Collect named OSM ways that can represent streets or squares."""

    def __init__(self) -> None:
        if osmium:
            super().__init__()
        self.ways: list[dict[str, Any]] = []

    def way(self, way: Any) -> None:
        tags = dict(way.tags)
        if "name" not in tags or ("highway" not in tags and "place" not in tags):
            return
        if tags.get("highway") in {"platform", "bus_stop"}:
            return
        self.ways.append(
            {
                "id": way.id,
                "type": "way",
                "version": getattr(way, "version", None),
                "tags": tags,
            }
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Find OSM ways whose names match Wikidata roads, streets, or squares "
            "in a municipality and create JSON, CSV, and JOSM reports."
        )
    )
    parser.add_argument("municipality", help="Wikidata municipality item, e.g. Q5245991")
    parser.add_argument("osm_file", type=Path, help="Local .pbf, .osm, or compatible OSM file")
    parser.add_argument(
        "--languages",
        default="mul,en",
        help="Comma-separated Wikidata label languages (default: mul,en)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Cache directory (default: <script directory>/cache)",
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=Path("wikidata_street_matches"),
        help="Output path without extension (default: wikidata_street_matches)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore and do not write all caches",
    )
    parser.add_argument(
        "--refresh-wikidata",
        action="store_true",
        help="Refresh the Wikidata street extraction cache",
    )
    parser.add_argument(
        "--refresh-osm",
        action="store_true",
        help="Refresh the local OSM extraction cache",
    )
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING"), default="INFO")
    if len(sys.argv) == 1:
        parser.print_help()
        raise SystemExit(0)
    return parser.parse_args()


def validate_qid(value: str) -> str:
    if not re.fullmatch(r"Q[1-9][0-9]*", value):
        raise ValueError(f"Invalid Wikidata item: {value!r} (expected e.g. Q5245991)")
    return value


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    temporary.replace(path)


def load_or_create_cache(
    path: Path,
    refresh: bool,
    no_cache: bool,
    factory: Any,
) -> Any:
    if not no_cache and path.exists() and not refresh:
        logging.info("Loading cache: %s", path)
        return read_json(path)
    value = factory()
    if not no_cache:
        write_json(path, value)
    return value


def language_parameter(languages: str) -> str:
    values = [part.strip() for part in languages.split(",") if part.strip()]
    if not values:
        raise ValueError("--languages must contain at least one language code")
    return ",".join(values)


def sparql_request(query: str) -> dict[str, Any]:
    if requests is None:
        raise RuntimeError("The 'requests' package is required for Wikidata queries")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/sparql-results+json",
    }
    last_error = "unknown error"
    for attempt in range(RETRY_COUNT):
        try:
            response = requests.post(
                WIKIDATA_ENDPOINT,
                data={"query": query, "format": "json"},
                headers=headers,
                timeout=60,
            )
            if response.status_code == 429 or 500 <= response.status_code < 600:
                retry_after = response.headers.get("Retry-After")
                wait = min(int(retry_after), 120) if retry_after and retry_after.isdigit() else 2**attempt
                last_error = f"HTTP {response.status_code}"
                if attempt < RETRY_COUNT - 1:
                    logging.warning("%s; retrying in %s seconds", last_error, wait)
                    time.sleep(wait)
                    continue
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or "results" not in data:
                raise ValueError("Wikidata returned an unexpected JSON response")
            return data
        except (requests.RequestException, ValueError) as error:
            last_error = str(error)
            if attempt < RETRY_COUNT - 1:
                wait = 2**attempt
                logging.warning("Wikidata request failed (%s); retrying in %s seconds", error, wait)
                time.sleep(wait)
    raise RuntimeError(f"Wikidata request failed after {RETRY_COUNT} attempts: {last_error}")


def binding_value(binding: dict[str, Any], key: str, default: str = "") -> str:
    return binding.get(key, {}).get("value", default)


def item_id(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def fetch_street_items(municipality: str, languages: str) -> list[dict[str, Any]]:
    type_values = " ".join(f"wd:{qid}" for qid in WIKIDATA_TYPES)
    query = f"""
SELECT DISTINCT ?item ?itemLabel ?namedAfter ?namedAfterLabel ?coordinates WHERE {{
  VALUES ?streetType {{ {type_values} }}
  ?item wdt:P31 ?streetType;
        wdt:P131 wd:{municipality};
        wdt:P138 ?namedAfter.
  OPTIONAL {{ ?item wdt:P625 ?coordinates. }}
  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language \"{languages}\".
  }}
}}
"""
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for binding in sparql_request(query)["results"].get("bindings", []):
        street_qid = item_id(binding["item"]["value"])
        origin_qid = item_id(binding["namedAfter"]["value"])
        key = (street_qid, origin_qid)
        rows[key] = {
            "item": street_qid,
            "name": binding_value(binding, "itemLabel"),
            "named_after": origin_qid,
            "named_after_label": binding_value(binding, "namedAfterLabel"),
            "coordinates": binding_value(binding, "coordinates"),
        }
    return list(rows.values())


def extract_osm_ways(osm_file: Path) -> list[dict[str, Any]]:
    if osmium is None:
        raise RuntimeError("The 'pyosmium' package is required to read OSM files")
    if not osm_file.is_file():
        raise FileNotFoundError(f"OSM file does not exist: {osm_file}")
    handler = OsmWayHandler()
    handler.apply_file(str(osm_file), locations=False)
    logging.info("Collected %s named OSM ways", len(handler.ways))
    return handler.ways


def normalized_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = "".join(character for character in value if not unicodedata.category(character).startswith("P"))
    return " ".join(value.split())


def build_matches(street_items: list[dict[str, Any]], osm_ways: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for item in street_items:
        by_name.setdefault(normalized_name(item["name"]), []).append(item)

    matches: list[dict[str, Any]] = []
    for way in osm_ways:
        tags = way["tags"]
        if "name:etymology:wikidata" in tags:
            continue
        candidates = by_name.get(normalized_name(tags["name"]), [])
        for candidate in candidates:
            matches.append(
                {
                    "osm_type": "way",
                    "osm_id": way["id"],
                    "version": way.get("version"),
                    "name": tags["name"],
                    "osm_url": f"https://www.openstreetmap.org/way/{way['id']}",
                    "wikidata": candidate["item"],
                    "wikidata_name": candidate["name"],
                    "name_origin": candidate["named_after"],
                    "name_origin_title": candidate["named_after_label"],
                    "tags": tags,
                }
            )
    return matches


def write_csv(path: Path, matches: list[dict[str, Any]]) -> None:
    fields = [
        "osm_type", "osm_id", "version", "name", "osm_url", "wikidata",
        "wikidata_name", "name_origin", "name_origin_title",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: match.get(field, "") for field in fields} for match in matches)


def write_josm_change(path: Path, matches: list[dict[str, Any]]) -> None:
    root = ET.Element("osmChange", {"version": "0.6", "generator": "OSMToolsWikidataStreetMatch"})
    modify = ET.SubElement(root, "modify")
    for match in matches:
        attributes = {"id": str(match["osm_id"])}
        if match.get("version"):
            attributes["version"] = str(match["version"])
        way = ET.SubElement(modify, "way", attributes)
        tags = dict(match["tags"])
        tags["name:etymology:wikidata"] = match["name_origin"]
        for key in sorted(tags):
            ET.SubElement(way, "tag", {"k": key, "v": str(tags[key])})
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def run(args: argparse.Namespace) -> None:
    municipality = validate_qid(args.municipality)
    languages = language_parameter(args.languages)
    if not args.osm_file.is_file():
        raise FileNotFoundError(f"OSM file does not exist: {args.osm_file}")

    cache_dir = args.cache_dir or Path(__file__).resolve().parent / "cache"
    if not args.no_cache:
        cache_dir.mkdir(parents=True, exist_ok=True)

    wikidata_path = cache_dir / f"wikidata_{municipality}_{languages.replace(',', '_')}.json"
    osm_path = cache_dir / f"osm_{args.osm_file.stem}.json"

    logging.info("Phase 1/4: extracting street items from Wikidata")
    street_items = load_or_create_cache(
        wikidata_path, args.refresh_wikidata, args.no_cache,
        lambda: fetch_street_items(municipality, languages),
    )
    logging.info("Phase 2/4: extracting named ways from OpenStreetMap")
    osm_ways = load_or_create_cache(
        osm_path, args.refresh_osm, args.no_cache,
        lambda: extract_osm_ways(args.osm_file),
    )
    logging.info("Phase 3/4: comparing Wikidata names with OpenStreetMap names")
    matches = build_matches(street_items, osm_ways)

    logging.info("Phase 4/4: writing JSON, CSV, and JOSM reports")
    prefix = args.output_prefix
    prefix.parent.mkdir(parents=True, exist_ok=True)
    write_json(prefix.with_suffix(".json"), matches)
    write_csv(prefix.with_suffix(".csv"), matches)
    write_josm_change(prefix.with_suffix(".osc"), matches)
    logging.info("Wrote %s matches to %s.json, %s.csv, and %s.osc", len(matches), prefix, prefix, prefix)


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")
    try:
        run(args)
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as error:
        logging.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

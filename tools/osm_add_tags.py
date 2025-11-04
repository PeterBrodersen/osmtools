import osmium
import psycopg2
import sys
import os
import argparse
import re


class TagUpdaterHandler(osmium.SimpleHandler):
    """Collect existing tags for a set of node and way ids.

    This handler does not modify tags itself; it records the current tags for
    the objects so the caller can merge and write updated tags later.
    """

    def __init__(self, node_ids, way_ids):
        super().__init__()
        self.node_ids = set(node_ids)
        self.way_ids = set(way_ids)
        self.updated_nodes = {}  # id -> tags (current tags)
        self.updated_ways = {}  # id -> tags (current tags)

    def node(self, n):
        if n.id in self.node_ids:
            self.updated_nodes[n.id] = dict(n.tags)

    def way(self, w):
        if w.id in self.way_ids:
            self.updated_ways[w.id] = dict(w.tags)


# Function to get node and way IDs from Postgres
def get_all_osm_ids_with_gender_from_db(conn):
    """Return mappings of OSM object id -> gender for nodes and ways.

    This queries osmetymology.locations_agg joined to osmetymology.wikidata and
    left-joins osmetymology.gendermap to obtain a gender (e.g. 'male'/'female')
    for the linked Wikidata entry. Only rows where a gender mapping exists are
    returned.
    """
    queries = [("'point'", "node_genders"), ("'line','polygon'", "way_genders")]
    results = {"node_genders": {}, "way_genders": {}}

    with conn.cursor() as cur:
        for geomtype, key in queries:
            cur.execute(
                f"""
                SELECT UNNEST(l.object_ids) AS unnested_id,
                       COALESCE(g.gender, '') AS gender
                FROM osmetymology.locations_agg l
                INNER JOIN osmetymology.wikidata w ON l.wikidatas @> ARRAY[w.itemid]
                LEFT JOIN osmetymology.gendermap g ON (w.claims->'P21'->0->'mainsnak'->'datavalue'->'value'->>'id') = g.itemid
                WHERE l.geomtype IN({geomtype})
                  AND g.gender IS NOT NULL
            """
            )
            for row in cur.fetchall():
                if row[0]:
                    try:
                        oid = int(row[0])
                    except (ValueError, TypeError):
                        continue
                    gender = row[1] or ""
                    results[key][oid] = gender

    print(
        f"Found {len(results['node_genders'])} nodes and {len(results['way_genders'])} ways with gender mapping"
    )
    return results["node_genders"], results["way_genders"]


# Function to update OSM file with key/value for given node and way IDs
def update_osm_tags(input_file, node_genders, way_genders, output_file):
    """Update OSM file adding etymology_has_male/etymology_has_female=yes for objects with genders.

    node_genders and way_genders are dicts mapping OSM id -> gender string.
    """
    handler = TagUpdaterHandler(node_genders.keys(), way_genders.keys())
    handler.apply_file(input_file)
    print(
        f"Nodes to update: {len(handler.updated_nodes)}; Ways to update: {len(handler.updated_ways)}"
    )

    writer = osmium.SimpleWriter(output_file, osmium.osm.osm_entity_bits.ALL)

    class CopyHandler(osmium.SimpleHandler):
        def __init__(self, updated_nodes, updated_ways):
            super().__init__()
            self.updated_nodes = updated_nodes  # id -> tags
            self.updated_ways = updated_ways  # id -> tags

        def node(self, n):
            if n.id in self.updated_nodes:
                mnode = osmium.osm.mutable.Node(n)
                mnode.tags = [(k, v) for k, v in self.updated_nodes[n.id].items()]
                writer.add_node(mnode)
            else:
                writer.add_node(n)

        def way(self, w):
            if w.id in self.updated_ways:
                mway = osmium.osm.mutable.Way(w)
                mway.tags = [(k, v) for k, v in self.updated_ways[w.id].items()]
                writer.add_way(mway)
            else:
                writer.add_way(w)

        def relation(self, r):
            writer.add_relation(r)

    # Build updated maps with correct tag keys based on gender
    updated_nodes_with_tags = {}
    for nid, gender in node_genders.items():
        if gender.lower() == "male":
            updated_nodes_with_tags[nid] = {
                **handler.updated_nodes.get(nid, {}),
                "etymology_has_male": "yes",
            }
        elif gender.lower() == "female":
            updated_nodes_with_tags[nid] = {
                **handler.updated_nodes.get(nid, {}),
                "etymology_has_female": "yes",
            }

    updated_ways_with_tags = {}
    for wid, gender in way_genders.items():
        if gender.lower() == "male":
            updated_ways_with_tags[wid] = {
                **handler.updated_ways.get(wid, {}),
                "etymology_has_male": "yes",
            }
        elif gender.lower() == "female":
            updated_ways_with_tags[wid] = {
                **handler.updated_ways.get(wid, {}),
                "etymology_has_female": "yes",
            }

    copy_handler = CopyHandler(updated_nodes_with_tags, updated_ways_with_tags)
    copy_handler.apply_file(input_file)
    writer.close()
    print(f"Wrote updated data to {output_file}")


# Function to update all OSM names
def get_all_wikidata_descriptions(conn):
    descriptions = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT itemid, COALESCE(name || '; ' || description, name) AS description
            FROM osmetymology.wikidata
            WHERE description IS NOT NULL
        """
        )
        for itemid, description in cur.fetchall():
            descriptions[itemid] = description
    return descriptions


# Function to update names in OSM based on Wikidata descriptions
def update_osm_names_from_description(input_file, descriptions, output_file):
    class NameUpdateHandler(osmium.SimpleHandler):
        def __init__(self, descriptions):
            super().__init__()
            self.descriptions = descriptions
            self.updated_nodes = {}
            self.updated_ways = {}
            self.qid_pattern = re.compile(r"^Q[0-9]+$")

        def node(self, n):
            tags = dict(n.tags)
            name = tags.get("name")
            qid = tags.get("name:etymology:wikidata")
            etym = tags.get("name:etymology")
            desc = None
            if name:
                if qid and self.qid_pattern.match(qid):
                    desc = self.descriptions.get(qid)
                elif etym:
                    desc = etym
                if desc:
                    tags["name"] = f"{name} [{desc}]"
                    self.updated_nodes[n.id] = tags

        def way(self, w):
            tags = dict(w.tags)
            name = tags.get("name")
            qid = tags.get("name:etymology:wikidata")
            etym = tags.get("name:etymology")
            desc = None
            if name:
                if qid and self.qid_pattern.match(qid):
                    desc = self.descriptions.get(qid)
                elif etym:
                    desc = etym
                if desc:
                    tags["name"] = f"{name} [{desc}]"
                    self.updated_ways[w.id] = tags

    handler = NameUpdateHandler(descriptions)
    handler.apply_file(input_file)
    print(
        f"Nodes to update: {len(handler.updated_nodes)}; Ways to update: {len(handler.updated_ways)}"
    )

    writer = osmium.SimpleWriter(output_file, osmium.osm.osm_entity_bits.ALL)

    class CopyHandler(osmium.SimpleHandler):
        def __init__(self, updated_nodes, updated_ways):
            super().__init__()
            self.updated_nodes = updated_nodes
            self.updated_ways = updated_ways

        def node(self, n):
            if n.id in self.updated_nodes:
                mnode = osmium.osm.mutable.Node(n)
                mnode.tags = [(k, v) for k, v in self.updated_nodes[n.id].items()]
                writer.add_node(mnode)
            else:
                writer.add_node(n)

        def way(self, w):
            if w.id in self.updated_ways:
                mway = osmium.osm.mutable.Way(w)
                mway.tags = [(k, v) for k, v in self.updated_ways[w.id].items()]
                writer.add_way(mway)
            else:
                writer.add_way(w)

        def relation(self, r):
            writer.add_relation(r)

    copy_handler = CopyHandler(handler.updated_nodes, handler.updated_ways)
    copy_handler.apply_file(input_file)
    writer.close()
    print(f"Wrote updated data to {output_file}")


def run_add_gender_tags(conn, input_file, output_file):
    node_genders, way_genders = get_all_osm_ids_with_gender_from_db(conn)
    update_osm_tags(input_file, node_genders, way_genders, output_file)


def run_update_names(conn, input_file, output_file):
    descriptions = get_all_wikidata_descriptions(conn)
    update_osm_names_from_description(input_file, descriptions, output_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Update OSM tags or names based on Wikidata."
    )
    parser.add_argument(
        "feature",
        choices=["add_gender_tags", "update_names"],
        help="Feature to run: add_gender_tags or update_names",
    )
    parser.add_argument("input_file", help="Input OSM or PBF file")
    parser.add_argument("output_file", help="Output OSM or PBF file")
    args = parser.parse_args()

    input_file = args.input_file
    output_file = args.output_file

    # Read DB params from environment
    db_params = {
        "dbname": os.environ.get("PGDATABASE"),
        "user": os.environ.get("PGUSER"),
        "password": os.environ.get("PGPASSWORD"),
        "host": os.environ.get("PGHOST", "localhost"),
        "port": int(os.environ.get("PGPORT", 5432)),
    }
    missing = [k for k in ["dbname", "user", "password"] if not db_params[k]]
    if missing:
        print(
            f"Missing required environment variables: {', '.join(['PGDATABASE' if k=='dbname' else 'PGUSER' if k=='user' else 'PGPASSWORD' for k in missing])}"
        )
        sys.exit(1)

    conn = psycopg2.connect(**db_params)
    if args.feature == "add_gender_tags":
        run_add_gender_tags(conn, input_file, output_file)
    elif args.feature == "update_names":
        run_update_names(conn, input_file, output_file)
    conn.close()

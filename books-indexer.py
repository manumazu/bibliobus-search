#!/usr/bin/env python3
"""Setup and (optionally) populate a Meilisearch 'books' index.

Schema reference:
  id            int(11) AUTO_INCREMENT (primary key)
  id_user       int(11) NOT NULL
  id_app        int(11) NULL
  isbn          varchar(32) NULL
  title         varchar(255) NOT NULL
  subtitle      varchar(255) NULL
  ocr_keywords  varchar(255) NULL
  author        varchar(255) NOT NULL
  editor        varchar(255) NULL

Usage:
  uv run meilisearch_books.py --setup                 # create index + settings
  uv run meilisearch_books.py --seed                  # insert sample docs
  uv run meilisearch_books.py --from-mysql            # import from MySQL
  uv run meilisearch_books.py --search "moby dick"    # quick search test
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from dotenv import dotenv_values

import meilisearch

# ---------------------------------------------------------------------------
# Configuration (env overrides)
# ---------------------------------------------------------------------------
config = dotenv_values(".env")
MEILI_URL = f"http://{config["MEILI_HOST"]}:7700"
MEILI_KEY = config["MEILI_MASTER_KEY"]
INDEX_UID = "books"
PRIMARY_KEY = "id"

# MySQL side (only needed for --from-mysql)
MYSQL_DSN = {
    "host": config["MYSQL_HOST"],
    "port": 3306,
    "user": config["MYSQL_USER"],
    "password": config["MYSQL_PASSWORD"],
    "database": config["MYSQL_DB"],
}


@dataclass
class Book:
    """Mirror of the MySQL `books` row. Meili requires ids as strings."""
    id: int
    id_user: int
    id_app: int | None
    isbn: str | None
    title: str
    subtitle: str | None
    ocr_keywords: str | None
    author: str
    editor: str | None

    def to_doc(self) -> dict:
        return {
            "id": str(self.id),          # Meili primary keys must be strings
            "id_user": self.id_user,
            "id_app": self.id_app,
            "isbn": self.isbn,
            "title": self.title,
            "subtitle": self.subtitle,
            "ocr_keywords": self.ocr_keywords,
            "author": self.author,
            "editor": self.editor,
        }


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
SEARCHABLE = [
    "title",
    "subtitle",
    "author",
    "editor",
    "ocr_keywords",
    "isbn",
]

# Attributes you'll filter on (user scoping is the big one here)
FILTERABLE = [
    "id_user",
    "id_app",
    "author",
    "editor",
]

SORTABLE = [
    "title",
    "author",
    "editor",
]

DISPLAYED = [
    "id",
    "id_user",
    "id_app",
    "isbn",
    "title",
    "subtitle",
    "author",
    "editor",
    "ocr_keywords",
]

# ISBNs, OCR noise and ids shouldn't be typo-corrected or split
NON_TYPO_FIELDS = ["isbn"]
SEPARATORS: list[str] = []          # keep default separators


def get_client() -> meilisearch.Client:
    return meilisearch.Client(MEILI_URL, MEILI_KEY or None)


def setup_index(client: meilisearch.Client) -> None:
    """Create the index (if missing) and apply settings."""
    try:
        client.create_index(INDEX_UID, {"primaryKey": PRIMARY_KEY})
        print(f"Created index '{INDEX_UID}' with primary key '{PRIMARY_KEY}'")
    except Exception as exc:  # index may already exist
        if "already exists" not in str(exc).lower():
            raise
        print(f"Index '{INDEX_UID}' already exists")

    index = client.index(INDEX_UID)

    index.update_settings({
        "searchableAttributes": SEARCHABLE,
        "filterableAttributes": FILTERABLE,
        "sortableAttributes": SORTABLE,
        "displayedAttributes": DISPLAYED,
        "rankingRules": [
            "words", "typo", "proximity", "attribute", "sort",
            "exactness", "title:asc",
        ],
        "typoTolerance": {
            "disableOnAttributes": NON_TYPO_FIELDS,
            "minWordSizeForTypos": {
                "oneTypo": 4,
                "twoTypos": 8
            },
        },
        "stopWords": ["the", "a", "an", "le", "la", "les", "de", "du", "des"],
    })
    print("Settings applied.")
    print(f"  searchable: {SEARCHABLE}")
    print(f"  filterable: {FILTERABLE}")
    print(f"  sortable:   {SORTABLE}")


SAMPLE_BOOKS = [
    Book(1, 42, 1, "9780140449136", "The Odyssey", "", "Homer", "Penguin Classics", "odyssey greek epic"),
    Book(2, 42, 1, "9782070413119", "L'Étranger", "", "Albert Camus", "Gallimard", "etranger absurde"),
    Book(3, 7, 2, "9780451524935", "1984", None, "George Orwell", "Signet Classics", "dystopia surveillance"),
]


def seed(client: meilisearch.Client) -> None:
    docs = [b.to_doc() for b in SAMPLE_BOOKS]
    task = client.index(INDEX_UID).add_documents(docs)
    client.wait_for_task(task.task_uid)
    print(f"Seeded {len(docs)} sample documents.")


def import_from_mysql(client: meilisearch.Client, batch_size: int = 1000) -> None:
    """Stream the whole `books` table into Meili in batches."""
    try:
        import mysql.connector
    except ImportError:
        sys.exit("mysql-connector-python required: uv add mysql-connector-python")

    conn = mysql.connector.connect(**MYSQL_DSN)
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, id_user, id_app, isbn, title, subtitle, "
        "ocr_keywords, author, editor FROM biblio_book ORDER BY id"
    )
    index = client.index(INDEX_UID)
    total, batch = 0, []

    for row in cur:
        book = Book(
            row["id"], row["id_user"], row["id_app"], row["isbn"],
            row["title"], row["subtitle"], row["ocr_keywords"],
            row["author"], row["editor"],
        )
        batch.append(book.to_doc())
        if len(batch) >= batch_size:
            index.add_documents_in_batches(batch, batch_size)
            total += len(batch)
            batch = []
            print(f"  indexed {total} rows...")
    if batch:
        index.add_documents_in_batches(batch, batch_size)
        total += len(batch)

    conn.close()
    print(f"Imported {total} documents.")


def search(client: meilisearch.Client, query: str, raw_filter: str | None = None) -> None:
    opts: dict = {"limit": 10}
    if raw_filter:
        opts["filter"] = raw_filter
    result = client.index(INDEX_UID).search(query, opts)
    print(f"{result.get('estimatedTotalHits', 0)} hits for '{query}':")
    for hit in result.get("hits", []):
        print(f"  [{hit['id']}] {hit['title']} — {hit['author']} ({hit.get('editor')})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Meilisearch books index setup")
    parser.add_argument("--setup", action="store_true", help="create index + settings")
    parser.add_argument("--seed", action="store_true", help="insert sample docs")
    parser.add_argument("--from-mysql", action="store_true", help="import from MySQL")
    parser.add_argument("--search", metavar="QUERY", help="test a search query")
    parser.add_argument("--filter", dest="raw_filter", metavar="FILTER",
                        help="Meili filter expression, e.g. 'id_user = 42'")
    args = parser.parse_args()

    client = get_client()
    client.health()  # raises if unreachable

    if args.setup:
        setup_index(client)
    if args.seed:
        seed(client)
    if args.from_mysql:
        import_from_mysql(client)
    if args.search:
        search(client, args.search, args.raw_filter)
    if not any([args.setup, args.seed, args.from_mysql, args.search]):
        parser.print_help()


if __name__ == "__main__":
    main()

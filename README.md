# bibliobus-search

Python script using Meilisearch client for [Bibliobus](https://bibliob.us) datas.

Searchable attributes are ordered `title` first : means title matches rank higher than matches in `ocr_keywords`. 
`ocr_keywords` sits low in the search order, which works well as a "catch-all" boost field for OCRed content.
`isbn` field is searchable but typo-tolerance is disabled on it (an ISBN typo shouldn't silently match a different book).
`id_user` and `id_app are` filterable, so every query can be scoped per user/app: --search "camus" --filter 'id_user = 42', don't rely on search alone.

### Install
```
python3 -m venv venv
. venv/bin/activate
pip install python-dotenv
pip install meilisearch
pip install mysql-connector-python
```

### Usage
```
python books-indexer.py --setup # create index
python books-indexer.py --from-mysql # index the whole books table
python books-indexer.py --search "camus" --filter 'id_user = 42' # search and filter
```
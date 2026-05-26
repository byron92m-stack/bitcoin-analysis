import httpx

CH_URL = "http://localhost:8123"

class ClickHouseError(Exception):
    pass

def query(sql: str) -> list[dict]:
    """Ejecuta SQL en ClickHouse y devuelve lista de dicts."""
    try:
        resp = httpx.get(
            CH_URL,
            params={"query": sql, "default_format": "JSONEachRow"},
            timeout=10.0
        )
        resp.raise_for_status()
        # Parsear JSONEachRow (una línea JSON por fila)
        lines = resp.text.strip().split("\n")
        import json
        return [json.loads(line) for line in lines if line.strip()]
    except httpx.HTTPError as e:
        raise ClickHouseError(f"ClickHouse error: {e}") from e
    except Exception as e:
        raise ClickHouseError(f"Error: {e}") from e

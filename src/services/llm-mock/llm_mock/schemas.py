import json


def example(schema: object, text: str) -> object:
    if not isinstance(schema, dict):
        return text
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    for key in ("anyOf", "oneOf", "allOf"):
        if schema.get(key):
            return example(schema[key][0], text)
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((name for name in kind if name != "null"), kind[0] if kind else None)
    if kind == "object" or (kind is None and "properties" in schema):
        properties = schema.get("properties") or {}
        return {name: example(spec, text) for name, spec in properties.items()}
    if kind == "array":
        return [example(schema.get("items"), text) for _ in range(schema.get("minItems", 0))]
    if kind == "string":
        return text.ljust(schema.get("minLength", 0), ".")[: schema.get("maxLength")]
    if kind in ("integer", "number"):
        return schema.get("minimum", 0)
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    return text


def dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def broken(text: str) -> str:
    return text[: max(1, len(text) // 2)]

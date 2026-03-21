"""Base class for agent tools."""

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Abstract base for all agent tools."""

    _TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        pass

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        pass

    def cast_params(self, params: dict[str, Any]) -> dict[str, Any]:
        schema = self.parameters or {}
        if schema.get("type", "object") != "object":
            return params
        return self._cast_object(params, schema)

    def _cast_object(self, obj: Any, schema: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(obj, dict):
            return obj
        props = schema.get("properties", {})
        return {k: self._cast_value(v, props[k]) if k in props else v for k, v in obj.items()}

    def _cast_value(self, val: Any, schema: dict[str, Any]) -> Any:
        target_type = schema.get("type")
        if target_type == "integer" and isinstance(val, str):
            try:
                return int(val)
            except ValueError:
                return val
        if target_type == "number" and isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                return val
        if target_type == "string":
            return val if val is None else str(val)
        if target_type == "boolean" and isinstance(val, str):
            if val.lower() in ("true", "1", "yes"):
                return True
            if val.lower() in ("false", "0", "no"):
                return False
        if target_type == "array" and isinstance(val, list):
            item_schema = schema.get("items")
            return [self._cast_value(item, item_schema) for item in val] if item_schema else val
        if target_type == "object" and isinstance(val, dict):
            return self._cast_object(val, schema)
        return val

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        if not isinstance(params, dict):
            return [f"parameters must be an object, got {type(params).__name__}"]
        schema = self.parameters or {}
        errors = []
        for k in schema.get("required", []):
            if k not in params:
                errors.append(f"missing required parameter: {k}")
        return errors

    def to_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

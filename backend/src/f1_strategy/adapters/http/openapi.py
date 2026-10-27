import json
import sys

from f1_strategy.adapters.http.app import create_app


def render_openapi() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    sys.stdout.buffer.write(render_openapi().encode())

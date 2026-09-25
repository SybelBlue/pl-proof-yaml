from collections.abc import Callable
from pathlib import Path
from typing import Any

import pl_proof_yaml

type ElementData = dict[str, Any]
type RenderMethod = Callable[[str | bytes, ElementData], str]
type LifecycleMethod = Callable[[str | bytes, ElementData], None]

LIFECYCLE_METHOD_NAMES = ("render", "prepare", "parse", "grade", "test")


MODULE_PATH = Path(pl_proof_yaml.__file__)


def assert_element_lifecycle_methods_exist() -> None:
    for method_name in LIFECYCLE_METHOD_NAMES:
        assert hasattr(pl_proof_yaml, method_name), (
            f"pl_proof_yaml is missing lifecycle method {method_name!r}"
        )


render: RenderMethod = pl_proof_yaml.render
prepare: LifecycleMethod = pl_proof_yaml.prepare
parse: LifecycleMethod = pl_proof_yaml.parse
grade: LifecycleMethod = pl_proof_yaml.grade
test: LifecycleMethod = pl_proof_yaml.test

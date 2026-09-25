import unittest
from dataclasses import fields, is_dataclass
from typing import Any, TypeGuard, overload


class TestCase(unittest.TestCase):
    @overload
    def assertIsInstance[T](
        self: unittest.TestCase,
        obj: object,
        cls: type[T],
        msg: Any = None,
    ) -> TypeGuard[T]: ...

    @overload
    def assertIsInstance(
        self: unittest.TestCase,
        obj: object,
        cls: tuple[type[Any], ...],
        msg: Any = None,
    ) -> bool: ...

    def assertIsInstance(  # pyright: ignore[reportIncompatibleMethodOverride]
        self: unittest.TestCase,
        obj: object,
        cls: type[Any] | tuple[type[Any], ...],
        msg: Any = None,
    ) -> bool:
        unittest.TestCase.assertIsInstance(self, obj, cls, msg)
        return True

    def assertNotIsInstance(  # pyright: ignore[reportIncompatibleMethodOverride]
        self: unittest.TestCase,
        obj: object,
        cls: type[Any] | tuple[type[Any], ...],
        msg: Any = None,
    ) -> bool:
        unittest.TestCase.assertNotIsInstance(self, obj, cls, msg)
        return True

    def assertIs[T](  # pyright: ignore[reportIncompatibleMethodOverride]
        self: unittest.TestCase,
        expr1: object,
        expr2: T,
        msg: Any = None,
    ) -> TypeGuard[T]:
        unittest.TestCase.assertIs(self, expr1, expr2, msg)
        return True

    def assertIsNone(  # pyright: ignore[reportIncompatibleMethodOverride]
        self: unittest.TestCase,
        obj: object,
        msg: Any = None,
    ) -> TypeGuard[None]:
        unittest.TestCase.assertIsNone(self, obj, msg)
        return True

    def assertIsNotNone[T](  # pyright: ignore[reportIncompatibleMethodOverride]
        self: unittest.TestCase,
        obj: T | None,
        msg: Any = None,
    ) -> TypeGuard[T]:
        unittest.TestCase.assertIsNotNone(self, obj, msg)
        return True


def assert_dataclass_equal(
    testcase: unittest.TestCase,
    actual: Any,
    expected: Any,
    message_prefix: str,
) -> None:
    try:
        _assert_recursive_equal(testcase, actual, expected, message_prefix, "")
    except AssertionError as exc:
        # Keep the assertion text, but hide the recursive helper frames.
        exc.__traceback__ = None
        raise


def _assert_recursive_equal(
    testcase: unittest.TestCase,
    actual: Any,
    expected: Any,
    message_prefix: str,
    path: str,
) -> None:
    if _is_line_instance(actual) or _is_line_instance(expected):
        testcase.assertTrue(
            _is_line_instance(actual) and _is_line_instance(expected),
            _message(message_prefix, path, "type mismatch"),
        )
        testcase.assertIs(
            type(actual),
            type(expected),
            _message(message_prefix, path, "type mismatch"),
        )
        actual_depends = set(actual.depends) | set(actual.implicit_depends)
        expected_depends = set(expected.depends)
        testcase.assertTrue(
            expected_depends.issubset(actual_depends),
            _message(message_prefix, path, "depends mismatch"),
        )
        for field in fields(actual):
            if not field.compare or field.name in {"depends", "implicit_depends"}:
                continue
            child_path = _join_path(path, field.name)
            _assert_recursive_equal(
                testcase,
                getattr(actual, field.name),
                getattr(expected, field.name),
                message_prefix,
                child_path,
            )
        return

    actual_is_dataclass = _is_dataclass_instance(actual)
    expected_is_dataclass = _is_dataclass_instance(expected)
    if actual_is_dataclass or expected_is_dataclass:
        testcase.assertTrue(
            actual_is_dataclass and expected_is_dataclass,
            _message(message_prefix, path, "type mismatch"),
        )
        testcase.assertIs(
            type(actual),
            type(expected),
            _message(message_prefix, path, "type mismatch"),
        )
        for field in fields(actual):
            if not field.compare:
                continue
            child_path = _join_path(path, field.name)
            _assert_recursive_equal(
                testcase,
                getattr(actual, field.name),
                getattr(expected, field.name),
                message_prefix,
                child_path,
            )
        return

    actual_is_list = isinstance(actual, list)
    expected_is_list = isinstance(expected, list)
    if actual_is_list or expected_is_list:
        testcase.assertTrue(
            actual_is_list and expected_is_list,
            _message(message_prefix, path, "type mismatch"),
        )
        testcase.assertEqual(
            len(actual),
            len(expected),
            _message(message_prefix, path, "length mismatch"),
        )
        for index, (actual_item, expected_item) in enumerate(zip(actual, expected)):
            child_path = _join_path(path, f"[{index}]")
            _assert_recursive_equal(
                testcase,
                actual_item,
                expected_item,
                message_prefix,
                child_path,
            )
        return

    actual_is_dict = isinstance(actual, dict)
    expected_is_dict = isinstance(expected, dict)
    if actual_is_dict or expected_is_dict:
        testcase.assertTrue(
            actual_is_dict and expected_is_dict,
            _message(message_prefix, path, "type mismatch"),
        )
        testcase.assertEqual(
            set(actual),
            set(expected),
            _message(message_prefix, path, "keys mismatch"),
        )
        for key in actual:
            child_path = _join_path(path, f"[{key!r}]")
            _assert_recursive_equal(
                testcase,
                actual[key],
                expected[key],
                message_prefix,
                child_path,
            )
        return

    testcase.assertEqual(
        actual,
        expected,
        _message(message_prefix, path, "mismatch"),
    )


def _is_dataclass_instance(value: Any) -> bool:
    return is_dataclass(value) and not isinstance(value, type)


def _is_line_instance(value: Any) -> bool:
    return (
        _is_dataclass_instance(value)
        and value.__class__.__name__ == "Line"
        and value.__class__.__module__ == "convert"
    )


def _join_path(path: str, fragment: str) -> str:
    if not path:
        return fragment
    if fragment.startswith("["):
        return f"{path}{fragment}"
    return f"{path}.{fragment}"


def _message(message_prefix: str, path: str, suffix: str) -> str:
    if path:
        return f"{message_prefix}:{path} {suffix}."
    return f"{message_prefix} {suffix}."

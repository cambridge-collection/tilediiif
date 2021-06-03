import hashlib
import re
from dataclasses import dataclass, field
from functools import partial, reduce, wraps
from pathlib import Path
from typing import AbstractSet, Callable, Dict, Union

from tilediiif.core.filesystem import validate_relative_path


class TemplateError(ValueError):
    pass


template_chunk = re.compile(
    r"""
# Placeholders with invalid contents or not terminated
(?P<invalid_placeholder>{(?![\w.-]+}))|
# Valid placeholders
{(?P<placeholder>[\w.-]+)}|
# Escape sequences
(?P<escape>\\[{\\])|
# Invalid escape sequences
(?P<invalid_escape>\\.)|
# Unescaped literal text
(?P<unescaped>[^{\\]+)
""",
    re.VERBOSE,
)


def render_placeholder(name, bindings):
    value = bindings.get(name)
    if not isinstance(value, str):
        raise TemplateError(f"No value for {name!r} exists in bound values: {bindings}")
    return value


def render_literal(value, _):
    return value


class Template:
    def __init__(self, chunks, var_names):
        self.chunks = tuple(chunks)
        self.var_names = frozenset(var_names)

    def render(self, bindings: Dict[str, str]):
        if bindings.keys() < self.var_names:
            missing = ", ".join(f"{v!r}" for v in self.var_names - bindings.keys())
            raise TemplateError(
                f"Variables for placeholders {missing} are missing from bound values:"
                f" {bindings}"
            )

        return "".join(c(bindings) for c in self.chunks)


def parse_template(template):
    def append_segment(
        segments,
        offset=None,
        invalid_placeholder=None,
        placeholder=None,
        escape=None,
        invalid_escape=None,
        unescaped=None,
    ):
        assert (
            sum(
                bool(x)
                for x in [
                    invalid_placeholder,
                    placeholder,
                    escape,
                    invalid_escape,
                    unescaped,
                ]
            )
            == 1
        )

        if invalid_placeholder or invalid_escape:
            thing = "placeholder" if invalid_placeholder else "escape sequence"
            raise TemplateError(
                f"""\
Invalid {thing} at offset {offset}:
    {template}
    {' ' * offset}^"""
            )
        elif placeholder:
            return segments + (("placeholder", placeholder),)

        literal = unescaped if unescaped else escape[1]
        # Merge consecutive literals
        if segments and segments[-1][0] == "literal":
            return segments[:-1] + (("literal", segments[-1][1] + literal),)
        return segments + (("literal", literal),)

    segments = reduce(
        lambda segments, match: append_segment(
            segments, offset=match.start(), **match.groupdict()
        ),
        template_chunk.finditer(template),
        (),
    )

    chunks = (
        partial(render_placeholder, value)
        if type == "placeholder"
        else partial(render_literal, value)
        for (type, value) in segments
    )
    var_names = (value for (type, value) in segments if type == "placeholder")
    return Template(chunks, var_names)


Field = Union[str, Callable[[Dict], str]]
Fields = Dict[str, Field]


@dataclass(frozen=True)
class TemplateRenderer:
    template: Template = field()
    fields: Fields

    def __call__(self, context: Dict):
        return self.template.render(TemplateBindings(self.fields, context))


@dataclass(frozen=True)
class TemplateBindings:
    fields: Fields
    context: Dict

    def keys(self):
        return self.fields.keys()

    def get(self, name: str, default=None):
        field = self.fields.get(name)
        if field is None:
            return default

        if isinstance(field, str):
            return field
        return field(self.context)


def use_context(*names):
    if len(names) == 1:
        (name,) = names

        def decorate(f):
            @wraps(f)
            def _use_context_single(context):
                return f(context[name])

            return _use_context_single

    else:

        def decorate(f):
            @wraps(f)
            def _use_context(context):
                return f(*[context[n] for n in names])

            return _use_context

    return decorate


def shard_prefix(key, *, segment_count, encoding="utf-8"):
    if segment_count < 1:
        raise ValueError(f"segment_count must be >= 1, got: {segment_count}")
    if segment_count > hashlib.blake2b.MAX_DIGEST_SIZE:
        raise ValueError(
            f"Unsupported segment_count: {segment_count: m}, maximum "
            f"segment_count: {hashlib.blake2b.MAX_DIGEST_SIZE}"
        )

    shard_key = hashlib.blake2b(
        key.encode(encoding), digest_size=segment_count
    ).hexdigest()
    return "/".join(shard_key[i * 2 : i * 2 + 2] for i in range(segment_count))


@use_context("identifier")
def identifier_shard_field(identifier):
    return shard_prefix(identifier, segment_count=2)


@use_context("image_request")
def image_request_region_field(image_request):
    return str(image_request.region)


@use_context("image_request")
def image_request_size_field(image_request):
    return str(image_request.size)


@use_context("image_request")
def image_request_rotation_field(image_request):
    return str(image_request.rotation)


@use_context("image_request")
def image_request_quality_field(image_request):
    return str(image_request.quality)


@use_context("image_request")
def image_request_format_field(image_request):
    return str(image_request.format)


@use_context("image_request")
def image_request_shard_field(image_request):
    return shard_prefix(key=str(image_request), segment_count=1)


def context_value_field(name):
    @use_context(name)
    def get_context_value(val):
        return val

    return get_context_value


INFO_JSON_TEMPLATE_KEYS = frozenset(("identifier", "identifier-shard"))


def get_info_json_path_renderer(base_dir: Path, path_template: str):
    template = _parse_template_with_placeholders(path_template, INFO_JSON_TEMPLATE_KEYS)
    _validate_path_template(template)

    render_info_json_path_template = TemplateRenderer(
        template,
        {
            "identifier": context_value_field("identifier"),
            "identifier-shard": identifier_shard_field,
        },
    )

    def get_info_json_path(identifier):
        path = Path(render_info_json_path_template({"identifier": identifier}))
        validate_relative_path(path, prefix="rendered path")

        return base_dir / path

    return get_info_json_path


def _validate_path_template(template):
    path = Path(template.render({n: "*example*" for n in template.var_names}))
    validate_relative_path(path, prefix="template", exc_cls=TemplateError)


def _parse_template_with_placeholders(
    template_str: str, placeholders: AbstractSet[str]
):
    template = parse_template(template_str)
    if not template.var_names <= placeholders:
        unexpected_placeholders = ",".join(template.var_names - placeholders)
        raise TemplateError(
            f"template contains unexpected placeholders: {unexpected_placeholders!r}"
        )
    return template


IMAGE_TEMPLATE_KEYS = frozenset(
    INFO_JSON_TEMPLATE_KEYS
    | {"region", "size", "rotation", "quality", "format", "image-shard"}
)


def get_image_path_renderer(base_dir: Path, path_template: str):
    template = _parse_template_with_placeholders(path_template, IMAGE_TEMPLATE_KEYS)
    _validate_path_template(template)

    render_image_path_template = TemplateRenderer(
        template,
        {
            "identifier": context_value_field("identifier"),
            "identifier-shard": identifier_shard_field,
            "region": image_request_region_field,
            "size": image_request_size_field,
            "rotation": image_request_rotation_field,
            "quality": image_request_quality_field,
            "format": image_request_format_field,
            "image-shard": image_request_shard_field,
        },
    )

    def get_info_json_path(identifier, image_request):
        path = Path(
            render_image_path_template(
                {"identifier": identifier, "image_request": image_request}
            )
        )
        validate_relative_path(path, prefix="rendered path")

        return base_dir / path

    return get_info_json_path

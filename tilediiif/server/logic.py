import hashlib
from dataclasses import dataclass, field
from functools import partial, wraps
from pathlib import Path
from typing import Callable, Dict, Union

from tilediiif.tilelayout import parse_template, Template, TemplateError

_info_json_template_fields = frozenset({'identifier-shard'})

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
        name, = names

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


def shard_prefix(key, *, segment_count, encoding='utf-8'):
    if segment_count < 1:
        raise ValueError(f'segment_count must be >= 1, got: {segment_count}')
    if segment_count > hashlib.blake2b.MAX_DIGEST_SIZE:
        raise ValueError(
            f'Unsupported segment_count: {segment_count: m}, maximum '
            f'segment_count: {hashlib.blake2b.MAX_DIGEST_SIZE}')

    shard_key = hashlib.blake2b(key.encode(encoding),
                                digest_size=segment_count).hexdigest()
    return '/'.join(shard_key[i*2:i*2+2] for i in range(segment_count))


identifier_shard_field = use_context('identifier')(
    partial(shard_prefix, segment_count=2))


def context_value_field(name):
    @use_context(name)
    def get_context_value(val):
        return val

    return get_context_value


INFO_JSON_TEMPLATE_KEYS = frozenset(('identifier', 'identifier-shard'))


def get_info_json_path_renderer(base_dir: Path, path_template: str):
    template = parse_template(path_template)
    if not template.var_names <= INFO_JSON_TEMPLATE_KEYS:
        unexpected_placeholders = ','.join(
            template.var_names - INFO_JSON_TEMPLATE_KEYS)
        raise TemplateError(f'template contains unexpected placeholders: '
                            f'{unexpected_placeholders!r}')

    _validate_path_template(template)

    render_info_json_path_template = TemplateRenderer(template, {
        'identifier': context_value_field('identifier'),
        'identifier-shard': identifier_shard_field
    })

    def get_info_json_path(identifier):
        path = Path(render_info_json_path_template({'identifier': identifier}))
        _validate_relative_path(path, prefix='rendered path')

        return base_dir / path

    return get_info_json_path


def _validate_path_template(template):
    path = Path(template.render({n: '*example*' for n in template.var_names}))
    _validate_relative_path(path, prefix='template', exc_cls=TemplateError)


def _validate_relative_path(path: Path, prefix='path', exc_cls=ValueError):
    if '..' in path.parts:
        raise exc_cls(f'{prefix} contains a ".." (parent) segment: {path}')
    if path.is_absolute():
        raise exc_cls(f'{prefix} is not relative: {path}')

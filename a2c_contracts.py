"""Contracts to models (A2C v1.2, wave C design note C-02, item A-5).

    "a2c_sdlc": {"contracts": ["contracts/events/settlement-event.v1.schema.json"]}

Each JSON Schema becomes Pydantic models (Python) or Java records (Jackson), plus a
generated test that round-trips the schema's `examples`. The generator is part of A2C:
no network, no new tool. It supports a declared subset of JSON Schema and refuses
anything else by name, so a model never silently drops a rule:

    type (incl. [T, "null"]), properties, required, additionalProperties: false, enum,
    const, format (uuid, date-time, date, decimal), pattern, minLength, maxLength,
    minimum, maximum, items, local $ref / $defs, default, examples, and the
    "present only when" idiom: if {properties: {p: {const: v}}} then {required: [x]}
    else {not: {required: [x]}}.
"""
import json
import pprint
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ANNOTATIONS = {'$schema', '$id', '$comment', 'title', 'description', 'examples', 'default', '$defs',
               'definitions', 'readOnly', 'writeOnly', 'deprecated'}
SUPPORTED = ANNOTATIONS | {'type', 'properties', 'required', 'additionalProperties', 'enum', 'const', 'format',
                           'pattern', 'minLength', 'maxLength', 'minimum', 'maximum', 'items', '$ref',
                           'if', 'then', 'else'}
FORMATS = {'uuid', 'date-time', 'date', 'decimal'}


class ContractError(ValueError):
    """The schema uses something the generator does not support."""


def pascal(text: str) -> str:
    return ''.join(p[:1].upper() + p[1:] for p in re.split(r'[^A-Za-z0-9]+', text) if p)


def camel(text: str) -> str:
    p = pascal(text)
    return p[:1].lower() + p[1:]


def constant(text: str) -> str:
    c = re.sub(r'[^A-Za-z0-9]+', '_', str(text)).strip('_').upper()
    return c if c and not c[0].isdigit() else f'V_{c}'


def root_name(path: str, schema: Dict[str, Any]) -> str:
    stem = Path(path).name.split('.')[0]            # settlement-event.v1.schema.json -> settlement-event
    return pascal(schema.get('x-a2c-name') or stem)


# ------------------------------------------------------------------ the model
class Field:
    def __init__(self, name, spec, required, owner):
        self.name, self.spec, self.required, self.owner = name, spec, required, owner


class Model:
    def __init__(self, name: str, schema: Dict[str, Any]):
        self.name, self.schema = name, schema
        self.fields: List[Field] = []
        self.closed = schema.get('additionalProperties') is False
        self.present_when: Optional[Tuple[str, Any, str]] = None      # (property, value, field)


def load(path: str, base: Path = None) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_absolute() and base is not None and not p.exists():
        p = base / p
    return json.loads(p.read_text(encoding='utf-8'))


def _check(node: Any, where: str) -> None:
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key.startswith('x-'):
            continue
        if key not in SUPPORTED:
            raise ContractError(f'{where}: unsupported JSON Schema keyword "{key}"')
        if key == 'format' and value not in FORMATS:
            raise ContractError(f'{where}: unsupported format "{value}" (supported: {", ".join(sorted(FORMATS))})')
        if key == 'additionalProperties' and value not in (False, True):
            raise ContractError(f'{where}: additionalProperties must be true or false')
        if key == '$ref' and not str(value).startswith('#/'):
            raise ContractError(f'{where}: only local $ref ("#/$defs/...") is supported, not {value}')
        if key in ('properties', '$defs', 'definitions'):
            for name, sub in value.items():
                _check(sub, f'{where}/{key}/{name}')
        elif key in ('items',):
            _check(value, f'{where}/items')
    if any(k in node for k in ('if', 'then', 'else')):
        _present_when(node, where)


def _present_when(node, where) -> Tuple[str, Any, str]:
    try:
        (prop, cond), = node['if']['properties'].items()
        value = cond['const']
        (field,) = node['then']['required']
        (other,) = node['else']['not']['required']
        assert other == field and set(node['if']) == {'properties'} and set(node['then']) == {'required'}
    except (KeyError, ValueError, TypeError, AssertionError):
        raise ContractError(f'{where}: if/then/else is supported only as "x is present exactly when '
                            f'p == value" (if.properties.p.const, then.required [x], else.not.required [x])')
    return prop, value, field


class Contract:
    """One schema, resolved into models (root first, nested in order)."""

    def __init__(self, path: str, schema: Dict[str, Any]):
        _check(schema, Path(path).name)
        if schema.get('type') != 'object':
            raise ContractError(f'{Path(path).name}: the root must be an object')
        self.path, self.schema = path, schema
        self.root = root_name(path, schema)
        self.defs = dict(schema.get('$defs') or schema.get('definitions') or {})
        self.models: List[Model] = []
        self._names = set()
        self._model(self.root, schema)

    def _unique(self, name: str, parent: str) -> str:
        if name in self._names:
            name = parent + name
        self._names.add(name)
        return name

    def _model(self, name: str, schema: Dict[str, Any]) -> Model:
        model = Model(name, schema)
        self._names.add(name)
        self.models.append(model)
        required = set(schema.get('required', []))
        if any(k in schema for k in ('if', 'then', 'else')):
            model.present_when = _present_when(schema, name)
        for prop, spec in (schema.get('properties') or {}).items():
            model.fields.append(Field(prop, self._resolve(spec, prop, name), prop in required, name))
        return model

    def _resolve(self, spec: Dict[str, Any], prop: str, parent: str) -> Dict[str, Any]:
        if '$ref' in spec:
            ref = spec['$ref'].split('/')[-1]
            target = self.defs.get(ref)
            if target is None:
                raise ContractError(f'{parent}.{prop}: unknown $ref {spec["$ref"]}')
            if target.get('type') == 'object':
                name = pascal(ref)
                if name not in self._names:
                    self._model(name, target)
                return dict(target, _model=name)
            return target
        if spec.get('type') == 'object':
            return dict(spec, _model=self._model(self._unique(pascal(prop), parent), spec).name)
        if spec.get('type') == 'array' and isinstance(spec.get('items'), dict):
            return dict(spec, items=self._resolve(spec['items'], prop + '_item', parent))
        return spec


def _types(spec) -> Tuple[List[str], bool]:
    t = spec.get('type')
    types = t if isinstance(t, list) else ([t] if t else [])
    nullable = 'null' in types
    return [x for x in types if x != 'null'], nullable


# --------------------------------------------------------------------- Python
def _py_type(spec: Dict[str, Any], imports: set) -> str:
    if '_model' in spec:
        return spec['_model']
    if 'const' in spec:
        imports.add('Literal')
        return f'Literal[{spec["const"]!r}]'
    if 'enum' in spec:
        imports.add('Literal')
        return 'Literal[' + ', '.join(repr(v) for v in spec['enum']) + ']'
    types, nullable = _types(spec)
    base = types[0] if types else 'string'
    fmt = spec.get('format')
    if base == 'string':
        py = {'date-time': 'datetime', 'date': 'date', 'decimal': 'Decimal'}.get(fmt, 'str')
    elif base == 'integer':
        py = 'int'
    elif base == 'number':
        py = 'Decimal' if fmt == 'decimal' else 'float'
    elif base == 'boolean':
        py = 'bool'
    elif base == 'array':
        imports.add('List')
        py = f'List[{_py_type(spec.get("items") or {}, imports)}]'
    else:
        imports.add('Any')
        py = 'Any'
    if nullable:
        imports.add('Optional')
        py = f'Optional[{py}]'
    return py


def _py_constraints(spec: Dict[str, Any]) -> List[str]:
    out = []
    pattern = spec.get('pattern')
    if spec.get('format') == 'uuid' and not pattern:
        pattern = r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
    if pattern and spec.get('format') != 'decimal':
        out.append(f'pattern={pattern!r}')
    for key, arg in (('minLength', 'min_length'), ('maxLength', 'max_length'), ('minimum', 'ge'), ('maximum', 'le')):
        if key in spec:
            out.append(f'{arg}={spec[key]!r}')
    return out


def python(contract: Contract) -> str:
    imports, body = set(), []
    for model in reversed(contract.models):              # nested models first
        doc = model.schema.get('description') or model.schema.get('title') or f'{model.name} (generated).'
        lines = [f'class {model.name}(BaseModel):', f'    """{doc}"""']
        if model.closed:
            lines.append('    model_config = ConfigDict(extra="forbid")')
        for f in model.fields:
            typ = _py_type(f.spec, imports)
            if not f.required and not typ.startswith('Optional['):
                imports.add('Optional')
                typ = f'Optional[{typ}]'
            # absent -> None; a required nullable field must be present but may be null
            args = (['default=None'] if not f.required else []) + _py_constraints(f.spec)
            if f.spec.get('description'):
                args.append(f'description={f.spec["description"]!r}')
            lines.append(f'    {f.name}: {typ} = Field({", ".join(args)})' if args else f'    {f.name}: {typ}')
        if model.present_when:
            prop, value, field = model.present_when
            lines += ['', '    @model_validator(mode="after")',
                      '    def _present_when(self):',
                      f'        if (self.{prop} == {value!r}) != (self.{field} is not None):',
                      f'            raise ValueError("{field} is present exactly when {prop} is {value}")',
                      '        return self']
        body.append('\n'.join(lines))
    typing = sorted(imports & {'Any', 'List', 'Literal', 'Optional'})
    head = [f'"""Models of {Path(contract.path).name} (generated by A2C from the contract; edit the schema,',
            'not this file)."""',
            'from datetime import date, datetime  # noqa: F401',
            'from decimal import Decimal  # noqa: F401']
    if typing:
        head.append(f'from typing import {", ".join(typing)}')
    head += ['', 'from pydantic import BaseModel, ConfigDict, Field, model_validator  # noqa: F401']
    return '\n'.join(head) + '\n\n\n' + '\n\n\n'.join(body) + '\n'


def python_test(package: str, contracts: List[Contract]) -> str:
    parts = ['"""Generated by A2C: every contract example round-trips through its model."""',
             'import pytest', '']
    cases = []
    for c in contracts:
        module = module_name(c.path)
        parts.append(f'from {package}.contracts.{module} import {c.root}')
        for i, example in enumerate(c.schema.get('examples', [])):
            cases.append((c.root, i, example))
    # a Python literal (None, True), not JSON (null, true)
    parts += ['', '', 'CASES = ' + pprint.pformat([[r, i, e] for r, i, e in cases], width=100), '', '',
              '@pytest.mark.parametrize("model, index, example", CASES)',
              'def test_examples_round_trip(model, index, example):',
              '    parsed = globals()[model].model_validate(example)',
              '    assert globals()[model].model_validate_json(parsed.model_dump_json()) == parsed', '']
    if not cases:
        parts += ['', 'def test_contracts_import():', f'    assert {contracts[0].root}', '']
    return '\n'.join(parts)


def module_name(path: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', Path(path).name.split('.')[0].lower()).strip('_')


# ----------------------------------------------------------------------- Java
def _java_type(spec, model_name: str, enums: Dict[str, List[Any]], field: str) -> str:
    if '_model' in spec:
        return spec['_model']
    if 'enum' in spec:
        name = pascal(field)
        enums[name] = spec['enum']
        return name
    if 'const' in spec:
        return 'String'
    types, _ = _types(spec)
    base, fmt = (types[0] if types else 'string'), spec.get('format')
    if base == 'string':
        return {'uuid': 'java.util.UUID', 'date-time': 'java.time.OffsetDateTime', 'date': 'java.time.LocalDate',
                'decimal': 'java.math.BigDecimal'}.get(fmt, 'String')
    if base == 'array':
        return f'java.util.List<{_java_type(spec.get("items") or {}, model_name, enums, field + "_item")}>'
    return {'integer': 'Long', 'number': 'java.math.BigDecimal' if fmt == 'decimal' else 'Double',
            'boolean': 'Boolean'}.get(base, 'Object')


def java(contract: Contract, package: str) -> Dict[str, str]:
    """One file per model: a record with Jackson names; enums nested in the record."""
    files = {}
    for model in contract.models:
        enums: Dict[str, List[Any]] = {}
        comps = []
        for f in model.fields:
            typ = _java_type(f.spec, model.name, enums, f.name)
            comps.append(f'        @JsonProperty("{f.name}") {typ} {camel(f.name)}')
        enum_src = ''
        for name, values in enums.items():
            consts = ',\n'.join(f'        @JsonProperty("{v}") {constant(v)}' for v in values)
            enum_src += f'\n    public enum {name} {{\n{consts}\n    }}\n'
        doc = (model.schema.get('description') or model.name).replace('*/', '* /')
        files[f'{model.name}.java'] = (
            f'package {package};\n\nimport com.fasterxml.jackson.annotation.JsonIgnoreProperties;\n'
            f'import com.fasterxml.jackson.annotation.JsonProperty;\n\n'
            f'/** {doc} Generated by A2C from {Path(contract.path).name}; edit the schema, not this file. */\n'
            f'@JsonIgnoreProperties(ignoreUnknown = {"false" if model.closed else "true"})\n'
            f'public record {model.name}(\n' + ',\n'.join(comps) + f') {{\n{enum_src}}}\n')
    return files


# ------------------------------------------------------------------ entry points
def contracts_from(paths: List[str], base: Path = None) -> List[Contract]:
    return [Contract(str(p), load(p, base)) for p in paths or []]

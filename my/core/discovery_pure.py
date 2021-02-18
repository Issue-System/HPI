'''
The idea of this module is to avoid imports of external HPI modules and code evaluation via ast module etc.

This potentially allows it to be:

- robust: can discover modules that can't be imported, generally makes it foolproof
- faster: importing is slow and with tens of modules can be noteiceable
- secure: can be executed in a sandbox & used during setup
'''

REQUIRES = 'REQUIRES'
NOT_HPI_MODULE_VAR = '__NOT_HPI_MODULE__'

###

from typing import Optional, Sequence, NamedTuple, Iterable
from pathlib import Path
import re
import logging

'''
None means that requirements weren't defined (different from empty requirements)
'''
Requires = Optional[Sequence[str]]


class HPIModule(NamedTuple):
    name: str
    skip_reason: Optional[str]
    doc: Optional[str] = None
    file: Optional[Path] = None
    requires: Requires = None


def ignored(m: str) -> bool:
    excluded = [
        # legacy stuff left for backwards compatibility
        'core.*',
        'config.*',
    ]
    exs = '|'.join(excluded)
    return re.match(f'^my.({exs})$', m) is not None


import ast

# todo should be defensive? not sure
def _extract_requirements(a: ast.Module) -> Requires:
    # find the assignment..
    for x in a.body:
        if not isinstance(x, ast.Assign):
            continue
        tg = x.targets
        if len(tg) != 1:
            continue
        t = tg[0]
        # could be Subscript.. so best to keep dynamic
        id_ = getattr(t, 'id', None)
        if id_ != REQUIRES:
            continue
        vals = x.value
        # could be List/Tuple/Set?
        elts = getattr(vals, 'elts', None)
        if elts is None:
            continue
        deps = []
        for c in elts:
            if isinstance(c, ast.Constant):
                deps.append(c.value)
            elif isinstance(c, ast.Str):
                deps.append(c.s)
            else:
                raise RuntimeError(f"Expecting string contants only in {REQUIRES} declaration")
        return tuple(deps)
    return None


# todo should probably be more defensive..
def all_modules() -> Iterable[HPIModule]:
    """
    Experimental version, which isn't importing the modules, making it more robust and safe.
    """
    my_root = Path(__file__).absolute().parent.parent
    for f in sorted(my_root.rglob('*.py')):
        if f.is_symlink():
            continue  # meh
        mp = f.relative_to(my_root.parent)
        if mp.name == '__init__.py':
            mp = mp.parent
        m = str(mp.with_suffix('')).replace('/', '.')
        if ignored(m):
            continue
        a: ast.Module = ast.parse(f.read_text())
        is_not_module = any(
            getattr(node, 'name', None) == NOT_HPI_MODULE_VAR  # direct definition
            or any(getattr(n, 'name', None) == NOT_HPI_MODULE_VAR for n in getattr(node, 'names', []))  # import from
            for node in a.body
        )
        if is_not_module:
            continue
        doc = ast.get_docstring(a, clean=False)

        requires: Requires = None
        try:
            requires = _extract_requirements(a)
        except Exception as e:
            logging.exception(e)

        yield HPIModule(
            name=m,
            skip_reason=None,
            doc=doc,
            file=f.relative_to(my_root.parent),
            requires=requires,
        )


def module_by_name(name: str) -> HPIModule:
    for m in all_modules():
        if m.name == name:
            return m
    raise RuntimeError(f'No such module: {name}')


### tests


def test() -> None:
    # TODO this should be a 'sanity check' or something
    assert len(list(all_modules())) > 10  # kinda arbitrary


def test_demo() -> None:
    demo = module_by_name('my.demo')
    assert demo.doc is not None
    assert str(demo.file) == 'my/demo.py'
    assert demo.requires is None


def test_excluded() -> None:
    for m in all_modules():
        assert 'my.core.' not in m.name


def test_requires() -> None:
    photos = module_by_name('my.photos.main')
    r = photos.requires
    assert r is not None
    assert len(r) == 2  # fragile, but ok for now


def test_pure() -> None:
    """
    We want to keep this module clean of other HPI imports
    """
    src = Path(__file__).read_text()
    assert 'import '  + 'my' not in src
    assert 'from ' + 'my' not in src
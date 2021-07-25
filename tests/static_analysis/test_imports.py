from pathlib import Path

import pytest

from ploomber.static_analysis import imports


def write_recursively(*args, text=None):
    path = Path(*args)
    path.parent.mkdir(parents=True)
    if text:
        path.write_text(text)
    else:
        path.touch()


@pytest.fixture
def sample_files(tmp_directory, tmp_imports):
    Path('package').mkdir()
    Path('package', '__init__.py').touch()
    Path('package', 'sub').mkdir()
    Path('package', 'sub', '__init__.py').write_text("""
def x():
    pass
""")
    Path('package', 'sub_other').mkdir()
    Path('package', 'sub_other', '__init__.py').write_text("""
def a():
    pass
""")

    Path('module.py').write_text("""
def a():
    pass

def b():
    pass
""")

    Path('another_module.py').write_text("""
def a():
    pass

def b():
    pass
""")


@pytest.mark.parametrize(
    'script, expected',
    [
        ["""
from math import *
""", {}],
        ["""
# built-in module
import math

math.square(1)
""", {}],
        ["""
# module
import another_module
""", {}],
        [
            """
# module
import another_module

another_module.a
""", {
                'another_module.a': 'def a():\n    pass'
            }
        ],
        # NOTE: this is only possible if "import package" triggers an
        # "import package.sub" or "from package import sub". In such case "package"
        # is modified and gets a new "sub" attribute. Here's an explanation:
        # http://python-notes.curiousefficiency.org/en/latest/python_concepts/import_traps.html#the-submodules-are-added-to-the-package-namespace-trap
        [
            """
import package

package.sub.x()
""", {
                'package.sub.x': 'def x():\n    pass'
            }
        ],
        [
            """
# submodule
import package.sub

package.sub.x()
""", {
                'package.sub.x': 'def x():\n    pass'
            }
        ],
        ["""
# submodule
import package.sub
""", {}],
        [
            """
# from .. import {sub-module}
from package import sub_other

sub_other.a()
""", {
                'package.sub_other.a': 'def a():\n    pass'
            }
        ],
        [
            """
# from .. import {sub-module}
from package import sub_other

""", {}
        ],
        [
            """
# from .. import attribute1, attrbute2
from module import a, b
""", {
                'module.a': 'def a():\n    pass',
                'module.b': 'def b():\n    pass'
            }
        ],
        [
            """
# module
import another_module as some_alias

some_alias.a
""", {
                'another_module.a': 'def a():\n    pass'
            }
        ],
        [
            """
# submodule
import package.sub as some_alias

some_alias.x()
""", {
                'package.sub.x': 'def x():\n    pass'
            }
        ],
        [
            """
# built-in module
import math
# module
import another_module
# submodule
import package.sub
# from .. import {sub-module}
from package import sub_other
# from .. import {attribute}
from module import a, b

another_module.a()
another_module.b()
package.sub.x()
sub_other.a()
""", {
                'another_module.a': 'def a():\n    pass',
                'another_module.b': 'def b():\n    pass',
                'package.sub.x': 'def x():\n    pass',
                'package.sub_other.a': 'def a():\n    pass',
                'module.a': 'def a():\n    pass',
                'module.b': 'def b():\n    pass'
            }
        ],
    ],
    ids=[
        'import-star',
        'built-in',
        'local-unused',
        'local',
        'local-nested',
        'submodule',
        'submodule-empty',
        'from-import',
        'from-import-empty',
        # FIXME: only retrieve source code if attributes are actually
        # used in the code
        'from-import-multiple',
        'import-as',
        'submodule-import-as',
        'complete',
    ])
def test_extract_from_script(sample_files, script, expected):
    Path('script.py').write_text(script)

    # TODO: finding imports recursively

    # TODO: try with nested imports (i.e. inside a function)

    # TODO: try accessing an attribute that's imported in __init__
    # hence the source isn't there...

    # TODO: try accessing a constant like dictionary defined in a module
    # e.g. module.sub['a'], should we also look for changes there?
    specs = imports.extract_from_script('script.py')

    assert specs == expected


# test relative imports
# from . import y
# from .x import y
# from ..z import y
# NOTE: we don't need any verification logic. just find the package from
# the first argument, then get the parents and locate the symbol/module
# if the relative import is invalid, the task wont run anyway

# TODO: add a test with a namespace module. e.g., the same module
# as two different locations and we must look up in both to find a symbol


def test_extract_attribute_access():
    code = """
import my_module

result = my_module.some_fn(1)

def do_something(x):
    return my_module.another_fn(x) + x


def do_more_stuff(x):
    my_module = dict(something=1)
    return my_module['something']
"""

    assert imports.extract_attribute_access(
        code, 'my_module') == ['some_fn', 'another_fn']


def test_extract_attribute_access_2():
    code = """
import functions

functions.a()
"""
    assert imports.extract_attribute_access(code, 'functions') == ['a']


def test_extract_attribute_access_3():
    code = """
import functions

# some comment
functions.a()
functions.b()
"""
    # TODO: parametrize with and without comments
    assert imports.extract_attribute_access(code, 'functions') == ['a', 'b']


@pytest.mark.parametrize('source, expected', [
    [
        """
mod.sub.some_fn(1)
""",
        ['some_fn'],
    ],
    [
        """
result = mod.sub.some_fn(1)
""",
        ['some_fn'],
    ],
    [
        """
def do_something(x):
    return mod.sub.another_fn(x) + x
""",
        ['another_fn'],
    ],
    [
        """
mod.sub.some_dict[1]
""",
        ['some_dict'],
    ],
    [
        """
mod.sub.nested.attribute
""",
        ['nested.attribute'],
    ],
    [
        """
import mod.sub

result = mod.sub.some_fn(1)

def do_something(x):
    return mod.sub.another_fn(x) + x

mod = something_else()
mod.sub['something']

mod.sub.some_dict[1]

mod.sub.nested.attribute
""",
        ['some_fn', 'another_fn', 'some_dict', 'nested.attribute'],
    ],
],
                         ids=[
                             'function-call',
                             'function-call-assignment',
                             'function-call-nested',
                             'getitem',
                             'nested-attribute',
                             'complete',
                         ])
def test_extract_nested_attribute_access(source, expected):
    assert imports.extract_attribute_access(source, 'mod.sub') == expected


@pytest.mark.parametrize('symbol, source', [
    ['a', 'def a():\n    pass'],
    ['B', 'class B:\n    pass'],
])
def test_extract_symbol(symbol, source):
    code = """
def a():
    pass

class B:
    pass
"""

    assert imports.extract_symbol(code, symbol) == source


def test_get_source_from_function_import(tmp_directory, tmp_imports):
    Path('functions.py').write_text("""
def a():
    pass
""")

    assert imports.get_source_from_import('functions.a', '', 'functions',
                                          Path('.').resolve()) == {
                                              'functions.a':
                                              'def a():\n    pass'
                                          }


def test_get_source_from_module_import(tmp_directory, tmp_imports):
    Path('functions.py').write_text("""
def a():
    pass
""")

    code = """
import functions

functions.a()
"""

    # TODO: what if accessing attributes that do not exist e.g., functions.b()
    assert imports.get_source_from_import('functions', code, 'functions',
                                          Path('.').resolve()) == {
                                              'functions.a':
                                              'def a():\n    pass'
                                          }


def test_missing_init_in_submodule(tmp_directory, tmp_imports):
    write_recursively('package', '__init__.py')
    # note that we are missing package/sub/__init__.py
    # this works since Python 3.3
    # http://python-notes.curiousefficiency.org/en/latest/python_concepts/import_traps.html#the-missing-init-py-trap
    write_recursively('package',
                      'sub',
                      'functions.py',
                      text="""
def a():
    pass
""")

    code = """
from package.sub import functions

functions.a()
"""

    assert imports.get_source_from_import('package.sub.functions.a', code,
                                          'functions',
                                          Path('.').resolve()) == {
                                              'package.sub.functions.a':
                                              'def a():\n    pass'
                                          }


def test_missing_init_in_module(tmp_directory, tmp_imports):
    # note that we are missing package/__init__.py
    # this works since Python 3.3
    # http://python-notes.curiousefficiency.org/en/latest/python_concepts/import_traps.html#the-missing-init-py-trap
    write_recursively('package',
                      'functions.py',
                      text="""
def a():
    pass
""")

    code = """
from package.sub import functions

functions.a()
"""

    assert imports.get_source_from_import('package.functions.a', code,
                                          'functions',
                                          Path('.').resolve()) == {
                                              'package.functions.a':
                                              'def a():\n    pass'
                                          }


# FIXME
def test_missing_spec(tmp_directory, tmp_imports):
    # this will causes the spec.origin to be None
    Path('package').mkdir()

    code = """
import package

package.a()
"""
    assert imports.get_source_from_import('package', code, 'package',
                                          Path('.').resolve())
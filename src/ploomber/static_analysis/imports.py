from itertools import chain
import importlib
from pathlib import Path

import parso

from ploomber.codediffer import _delete_python_comments


def parent_or_child(path_to_script, origin):
    try:
        origin.relative_to(path_to_script)
    except ValueError:
        child = False
    else:
        child = True

    if child:
        return True

    try:
        path_to_script.relative_to(origin)
    except ValueError:
        parent = False
    else:
        parent = True

    return parent


def get_origin(name):
    try:
        return Path(importlib.util.find_spec(name).origin), True
    except ModuleNotFoundError:
        pass

    # name could be an attribute, not a module. so we try to locate
    # the module instead
    name_parent = '.'.join(name.split('.')[:-1])

    # NOTE: find_spec is going to import the package
    return Path(importlib.util.find_spec(name_parent).origin), False


def get_source_from_import(name, source, name_defined, base):
    """
    """
    # if name is a symbol, return a dict with the source, if it's a module
    # return the sources for the attribtues used in source
    origin, is_module = get_origin(name)

    # do not obtain sources for modules that arent in the project
    if not parent_or_child(base, origin):
        return {}

    if is_module:
        # everything except the last element
        accessed_attributes = extract_attribute_access(source, name_defined)

        # TODO: only read origin once
        return {
            f'{name}.{attr}': extract_symbol(origin.read_text(), attr)
            for attr in accessed_attributes
        }

    # is a single symbol
    else:
        symbol = name.split('.')[-1]
        # TODO: only read once
        source = extract_symbol(origin.read_text(), symbol)
        return {name: source}


def extract_from_script(path_to_script):
    """Returns a mapping with name -> source for each import on the script

    Notes
    -----
    Star imports (from module import *) are ignored
    """
    base = Path(path_to_script).parent.resolve()
    source = Path(path_to_script).read_text()

    m = parso.parse(source)

    specs = {}

    

    # this for only iters over top-level imports (?), should we ignored
    # nested ones?
    for import_ in m.iter_imports():
        # iterate over paths. e.g., from mod import a, b
        # iterates over a and b
        for paths, name_defined in zip(import_.get_paths(),
                                       import_.get_defined_names()):
            name = '.'.join([name.value for name in paths])


            # if import_name: import a.b, look for attributes of a.b
            # (e.g.,a.b.c)
            # if import_from: from a import b, look for attributes of b
            # (e.g., b.c)
            # from ipdb import set_trace; set_trace()

            # use the keyword next to import if doing (import X) and we are
            # not using the as keyword
            if (import_.type == 'import_name'
            and 'dotted_as_name' not in [c.type for c in import_.children]):
                name_defined = name
            else:
                name_defined = name_defined.value

            specs = {
                **specs,
                **get_source_from_import(name, source, name_defined, base)
            }

    return specs


def extract_attribute_access(code, name):
    # delete comments otherwise the leaf.parent.get_code() will fail
    m = parso.parse(_delete_python_comments(code))

    attributes = []

    leaf = m.get_first_leaf()


    while leaf is not None:
        extracted_name = '.'.join(
            leaf.parent.get_code().strip().split('.')[:-1])

        # FIXME: does this only match once?
        # the newline leaf also has the dotted path as parent
        if leaf.type != 'newline' and extracted_name == name:

            children = leaf.parent.children
            children_code = [c.get_code() for c in children]

            # get the last accessed attribute
            # case 1 - fn call or getitem: {one}.{two}() or {one}.{two}[]
            # last is the function call or getitem (e.g., a.b(), a.b[1])
            # case 2 - accessing property: {one}.{two}
            # if there is a dot in the last token, then it's case 2
            idx = -1 if children_code[-1][0] == '.' else -2

            # ignore first character (it is the dot)
            last = children[idx].get_code().strip()[1:]


            # sibling = leaf.get_next_sibling()
            # code = None if not sibling else sibling.get_code()

            # ignore anything other than attribute access
            # if sibling and code[0] == '.':
            # attributes.append(code[1:])
            if last:
                attributes.append(last)

        # can i make this faster? is there a way to get the next leaf
        # of certain type?
        leaf = leaf.get_next_leaf()

    return attributes


def extract_symbol(code, name):
    """
    """
    # NOTE: should we import and inspect live objects? for python callables
    # they should already been imported if the task executed but for scripts it
    # means we have to import everything. perhaps do static analysis?
    # we already have some code to find symbols using static analysis, re-use
    # it
    m = parso.parse(code)

    for node in chain(m.iter_funcdefs(), m.iter_classdefs()):
        if node.name.value == name:
            return node.get_code().strip()

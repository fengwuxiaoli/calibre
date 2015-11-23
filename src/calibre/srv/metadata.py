#!/usr/bin/env python2
# vim:fileencoding=utf-8
# License: GPLv3 Copyright: 2015, Kovid Goyal <kovid at kovidgoyal.net>

from __future__ import (unicode_literals, division, absolute_import,
                        print_function)
from copy import copy
from collections import namedtuple
from datetime import datetime, time

from calibre.db.categories import Tag
from calibre.utils.date import isoformat, UNDEFINED_DATE, local_tz
from calibre.utils.config import tweaks
from calibre.utils.formatter import EvalFormatter
from calibre.utils.icu import collation_order

IGNORED_FIELDS = frozenset('cover ondevice path marked id au_map'.split())

def encode_datetime(dateval):
    if dateval is None:
        return "None"
    if not isinstance(dateval, datetime):
        dateval = datetime.combine(dateval, time())
    if hasattr(dateval, 'tzinfo') and dateval.tzinfo is None:
        dateval = dateval.replace(tzinfo=local_tz)
    if dateval <= UNDEFINED_DATE:
        return None
    return isoformat(dateval)

def add_field(field, db, book_id, ans, field_metadata):
    datatype = field_metadata.get('datatype')
    if datatype is not None:
        val = db._field_for(field, book_id)
        if val is not None and val != ():
            if datatype == 'datetime':
                val = encode_datetime(val)
                if val is None:
                    return
            ans[field] = val

def book_as_json(db, book_id):
    db = db.new_api
    with db.safe_read_lock:
        ans = {'formats':db._formats(book_id)}
        fm = db.field_metadata
        for field in fm.all_field_keys():
            if field not in IGNORED_FIELDS:
                add_field(field, db, book_id, ans, fm[field])
    return ans

_include_fields = frozenset(Tag.__slots__) - frozenset({
    'state', 'is_editable', 'is_searchable', 'original_name', 'use_sort_as_name', 'is_hierarchical'
})

def category_as_json(items, category, display_name, count, tooltip=None, parent=None,
        is_editable=True, is_gst=False, is_hierarchical=False, is_searchable=True,
        is_user_category=False):
    ans = {'category': category, 'name': display_name, 'is_category':True, 'count':count}
    if tooltip:
        ans['tooltip'] = tooltip
    if parent:
        ans['parent'] = parent
    if is_editable:
        ans['is_editable'] = True
    if is_gst:
        ans['is_gst'] = True
    if is_hierarchical:
        ans['is_hierarchical'] = is_hierarchical
    if is_searchable:
        ans['is_searchable'] = True
    if is_user_category:
        ans['is_user_category'] = True
    item_id = 'c' + str(len(items))
    items[item_id] = ans
    return item_id

def category_item_as_json(x, clear_rating=False):
    ans = {}
    for k in _include_fields:
        val = getattr(x, k)
        if val is not None:
            ans[k] = val.copy() if isinstance(val, set) else val
    if x.use_sort_as_name:
        ans['name'] = ans['sort']
    if x.original_name != ans['name']:
        ans['original_name'] = x.original_name
    ans.pop('sort', None)
    if clear_rating:
        del ans['avg_rating']
    return ans

CategoriesSettings = namedtuple(
    'CategoriesSettings', 'dont_collapse collapse_model collapse_at sort_by template using_hierarchy grouped_search_terms hidden_categories')

def categories_settings(query, db):
    dont_collapse = frozenset(query.get('dont_collapse', '').split(','))
    partition_method = query.get('partition_method', 'first letter')
    if partition_method not in {'first letter', 'disable', 'partition'}:
        partition_method = 'first letter'
    try:
        collapse_at = max(0, int(query.get('collapse_at', 25)))
    except Exception:
        collapse_at = 25
    sort_by = query.get('sort_tags_by', 'name')
    if sort_by not in {'name', 'popularity', 'rating'}:
        sort_by = 'name'
    collapse_model = partition_method if collapse_at else 'disable'
    template = None
    if collapse_model != 'disable':
        if sort_by != 'name':
            collapse_model = 'partition'
        template = tweaks['categories_collapsed_%s_template' % sort_by]
    using_hierarchy = frozenset(db.pref('categories_using_hierarchy', []))
    hidden_categories = db.pref('tag_browser_hidden_categories', set())
    return CategoriesSettings(
        dont_collapse, collapse_model, collapse_at, sort_by, template, using_hierarchy, db.pref('grouped_search_terms', {}), hidden_categories)

def create_toplevel_tree(category_data, items, field_metadata, opts):
    # Create the basic tree, containing all top level categories , user
    # categories and grouped search terms
    last_category_node, category_node_map, root = None, {}, {'id':None, 'children':[]}
    node_id_map = {}
    category_nodes, recount_nodes = [], []
    order = tweaks['tag_browser_category_order']
    defvalue = order.get('*', 100)
    categories = [category for category in field_metadata if category in category_data]
    scats = sorted(categories, key=lambda x: order.get(x, defvalue))

    for category in scats:
        is_user_category = category.startswith('@')
        is_gst, tooltip = (is_user_category and category[1:] in opts.grouped_search_terms), ''
        cdata = category_data[category]
        if is_gst:
            tooltip = _('The grouped search term name is "{0}"').format(category)
        elif category != 'news':
            cust_desc = ''
            fm = field_metadata[category]
            if fm['is_custom']:
                cust_desc = fm['display'].get('description', '')
                if cust_desc:
                    cust_desc = '\n' + _('Description:') + ' ' + cust_desc
            tooltip = _('The lookup/search name is "{0}"{1}').format(category, cust_desc)

        if is_user_category:
            path_parts = category.split('.')
            path = ''
            last_category_node = None
            current_root = root
            for i, p in enumerate(path_parts):
                path += p
                if path not in category_node_map:
                    last_category_node = category_as_json(
                        items, path, (p[1:] if i == 0 else p), len(cdata),
                        parent=last_category_node, tooltip=tooltip,
                        is_gst=is_gst, is_editable=((not is_gst) and (i == (len(path_parts)-1))),
                        is_hierarchical=False if is_gst else 5, is_user_category=True
                    )
                    node_id_map[last_category_node] = category_node_map[path] = node = {'id':last_category_node, 'children':[]}
                    category_nodes.append(last_category_node)
                    if not is_gst:
                        recount_nodes.append(node)
                    current_root['children'].append(node)
                    current_root = node
                else:
                    current_root = category_node_map[path]
                    last_category_node = current_root['id']
                path += '.'
        else:
            last_category_node = category_as_json(
                items, category, field_metadata[category]['name'], len(cdata),
                tooltip=tooltip
            )
            category_node_map[category] = node_id_map[last_category_node] = node = {'id':last_category_node, 'children':[]}
            root['children'].append(node)
            category_nodes.append(last_category_node)

    return root, node_id_map, category_nodes, recount_nodes

def build_first_letter_list(category_items):
    # Build a list of 'equal' first letters by noticing changes
    # in ICU's 'ordinal' for the first letter. In this case, the
    # first letter can actually be more than one letter long.
    cl_list = [None] * len(category_items)
    last_ordnum = 0
    last_c = ' '
    for idx, tag in enumerate(category_items):
        if not tag.sort:
            c = ' '
        else:
            c = icu_upper(tag.sort)
        ordnum, ordlen = collation_order(c)
        if last_ordnum != ordnum:
            last_c = c[0:ordlen]
            last_ordnum = ordnum
        cl_list[idx] = last_c
    return cl_list

categories_with_ratings = {'authors', 'series', 'publisher', 'tags'}

def get_name_components(name):
    components = filter(None, [t.strip() for t in name.split('.')])
    if not components or '.'.join(components) != name:
        components = [name]
    return components

def collapse_partition(collapse_nodes, items, category_node, idx, tag, opts, top_level_component,
    cat_len, category_is_hierarchical, category_items, eval_formatter, is_gst,
    last_idx, node_parent):
    # Only partition at the top level. This means that we must not do a break
    # until the outermost component changes.
    if idx >= last_idx + opts.collapse_at and not tag.original_name.startswith(top_level_component+'.'):
        last = idx + opts.collapse_at - 1 if cat_len > idx + opts.collapse_at else cat_len - 1
        if category_is_hierarchical:
            ct = copy(category_items[last])
            components = get_name_components(ct.original_name)
            ct.sort = ct.name = components[0]
            # Do the first node after the last node so that the components
            # array contains the right values to be used later
            ct2 = copy(tag)
            components = get_name_components(ct2.original_name)
            ct2.sort = ct2.name = components[0]
            format_data = {'last': ct, 'first':ct2}
        else:
            format_data = {'first': tag, 'last': category_items[last]}

        name = eval_formatter.safe_format(opts.template, format_data, '##TAG_VIEW##', None)
        if not name.startswith('##TAG_VIEW##'):
            # Formatter succeeded
            node_id = category_as_json(
                items, items[category_node['id']].category, name, 0,
                parent=category_node['id'], is_editable=False, is_gst=is_gst,
                is_hierarchical=category_is_hierarchical, is_searchable=False)
            node_parent = {'id':node_id, 'children':[]}
            collapse_nodes.append(node_parent)
            category_node['children'].append(node_parent)
        last_idx = idx  # remember where we last partitioned
    return last_idx, node_parent

def collapse_first_letter(collapse_nodes, items, category_node, cl_list, idx, is_gst, category_is_hierarchical, collapse_letter, node_parent):
    cl = cl_list[idx]
    if cl != collapse_letter:
        collapse_letter = cl
        node_id = category_as_json(
            items, items[category_node['id']]['category'], collapse_letter, 0,
            parent=category_node['id'], is_editable=False, is_gst=is_gst,
            is_hierarchical=category_is_hierarchical)
        node_parent = {'id':node_id, 'children':[]}
        category_node['children'].append(node_parent)
        collapse_nodes.append(node_parent)
    return collapse_letter, node_parent

def process_category_node(
        category_node, items, category_data, eval_formatter, field_metadata,
        opts, tag_map, hierarchical_tags, node_to_tag_map, collapse_nodes,
        intermediate_nodes):
    category = items[category_node['id']]['category']
    category_items = category_data[category]
    cat_len = len(category_items)
    if cat_len <= 0:
        return
    collapse_letter = None
    is_gst = items[category_node['id']].get('is_gst', False)
    collapse_model = 'disable' if category in opts.dont_collapse else opts.collapse_model
    fm = field_metadata[category]
    category_child_map = {}
    is_user_category = fm['kind'] == 'user' and not is_gst
    top_level_component = 'z' + category_items[0].original_name
    last_idx = -opts.collapse_at
    category_is_hierarchical = (
        category in opts.using_hierarchy and opts.sort_by == 'name' and
        category not in {'authors', 'publisher', 'news', 'formats', 'rating'}
    )
    clear_rating = category not in categories_with_ratings and not fm['is_custom'] and not fm['kind'] == 'user'
    collapsible = collapse_model != 'disable' and cat_len > opts.collapse_at
    partitioned = collapse_model == 'partition'
    cl_list = build_first_letter_list(category_items) if collapsible and collapse_model == 'first letter' else ()
    node_parent = category_node

    def create_tag_node(tag, parent):
        # User categories contain references to items in other categories, so
        # reflect that in the node structure as well.
        node_data = tag_map.get(id(tag), None)
        if node_data is None:
            node_id = 'n%d' % len(tag_map)
            node_data = items[node_id] = category_item_as_json(tag, clear_rating=clear_rating)
            tag_map[id(tag)] = (node_id, node_data)
            node_to_tag_map[node_id] = tag
        else:
            node_id, node_data = node_data
        node = {'id':node_id, 'children':[]}
        parent['children'].append(node)
        return node, node_data

    for idx, tag in enumerate(category_items):

        if collapsible:
            if partitioned:
                last_idx, node_parent = collapse_partition(
                collapse_nodes, items, category_node, idx, tag, opts, top_level_component,
                cat_len, category_is_hierarchical, category_items,
                eval_formatter, is_gst, last_idx, node_parent)
            else:  # by 'first letter'
                collapse_letter, node_parent = collapse_first_letter(
                    collapse_nodes, items, category_node, cl_list, idx, is_gst, category_is_hierarchical, collapse_letter, node_parent)
        else:
            node_parent = category_node

        tag_is_hierarchical = id(tag) in hierarchical_tags
        components = get_name_components(tag.original_name) if category_is_hierarchical or tag_is_hierarchical else (tag.original_name,)

        if not tag_is_hierarchical and (
                is_user_category or not category_is_hierarchical or len(components) == 1 or
                (fm['is_custom'] and fm['display'].get('is_names', False))
        ):  # A non-hierarchical leaf item in a non-hierarchical category
            node, item = create_tag_node(tag, node_parent)
            category_child_map[item['name'], item['category']] = node
            intermediate_nodes[tag.category, tag.original_name] = node
        else:
            orig_node_parent = node_parent
            for i, component in enumerate(components):
                if i == 0:
                    child_map = category_child_map
                else:
                    child_map = {}
                    for sibling in node_parent['children']:
                        item = items[sibling['id']]
                        if not item.get('is_category', False):
                            child_map[item['name'], item['category']] = sibling
                cm_key = component, tag.category
                if cm_key in child_map:
                    node_parent = child_map[cm_key]
                    items[node_parent['id']]['is_hierarchical'] = 3 if tag.category == 'search' else 5
                    hierarchical_tags.add(id(node_to_tag_map[node_parent['id']]))
                else:
                    if i < len(components) - 1:  # Non-leaf node
                        original_name = '.'.join(components[:i+1])
                        inode = intermediate_nodes.get((tag.category, original_name), None)
                        if inode is None:
                            t = copy(tag)
                            t.original_name, t.count = original_name, 0
                            t.is_editable, t.is_searchable = False, category == 'search'
                            node_parent, item = create_tag_node(t, node_parent)
                            hierarchical_tags.add(id(t))
                            intermediate_nodes[tag.category, original_name] = node_parent
                        else:
                            item = items[inode['id']]
                            ch = node_parent['children']
                            node_parent = {'id':inode['id'], 'children':[]}
                            ch.append(node_parent)
                    else:
                        node_parent, item = create_tag_node(tag, node_parent)
                        if not is_user_category:
                            item['original_name'] = tag.name
                        intermediate_nodes[tag.category, tag.original_name] = node_parent
                    item['name'] = component
                    item['is_hierarchical'] = 3 if tag.category == 'search' else 5
                    hierarchical_tags.add(id(tag))
                    child_map[cm_key] = node_parent
                items[node_parent['id']]['id_set'] |= tag.id_set
            node_parent = orig_node_parent

def iternode_descendants(node):
    for child in node['children']:
        yield child
        for x in iternode_descendants(child):
            yield x

def fillout_tree(root, items, node_id_map, category_nodes, category_data, field_metadata, opts):
    eval_formatter = EvalFormatter()
    tag_map, hierarchical_tags, node_to_tag_map = {}, set(), {}
    first, later, collapse_nodes, intermediate_nodes = [], [], [], {}
    # User categories have to be processed after normal categories as they can
    # reference hierarchical nodes that were created only during processing of
    # normal categories
    for category_node_id in category_nodes:
        cnode = items[category_node_id]
        coll = later if cnode.get('is_user_category', False) else first
        coll.append(node_id_map[category_node_id])

    for coll in (first, later):
        for cnode in coll:
            process_category_node(
                cnode, items, category_data, eval_formatter, field_metadata,
                opts, tag_map, hierarchical_tags, node_to_tag_map,
                collapse_nodes, intermediate_nodes)

    # Do not store id_set in the tag items as it is a lot of data, with not
    # much use. Instead only update the counts based on id_set
    for item_id, item in tag_map.itervalues():
        id_len = len(item.pop('id_set', ()))
        if id_len:
            item['count'] = id_len

    for node in collapse_nodes:
        item = items[node['id']]
        item['count'] = sum(1 for _ in iternode_descendants(node))

def render_categories(field_metadata, opts, category_data):
    items = {}
    root, node_id_map, category_nodes, recount_nodes = create_toplevel_tree(category_data, items, field_metadata, opts)
    fillout_tree(root, items, node_id_map, category_nodes, category_data, field_metadata, opts)
    for node in recount_nodes:
        item = items[node['id']]
        item['count'] = sum(1 for x in iternode_descendants(node) if not items[x['id']].get('is_user_category', False))
    if opts.hidden_categories:
        # We have to remove hidden categories after all processing is done as
        # items from a hidden category could be in a user category
        root['children'] = filter((lambda child:items[child['id']]['category'] not in opts.hidden_categories), root['children'])
    return {'root':root, 'item_map': items}

def categories_as_json(ctx, rd, db):
    opts = categories_settings(rd.query, db)
    category_data = ctx.get_categories(rd, db, sort=opts.sort_by, first_letter_sort=opts.collapse_model == 'first letter')
    render_categories(db.field_metadata, opts, category_data)

# Test tag browser {{{

def dump_categories_tree(data):
    root, items = data['root'], data['item_map']
    ans, indent = [], '  '
    def dump_node(node, level=0):
        item = items[node['id']]
        rating = item.get('avg_rating', None) or 0
        if rating:
            rating = ',rating=%.1f' % rating
        try:
            ans.append(indent*level + item['name'] + ' [count=%s%s]' % (item['count'], rating or ''))
        except KeyError:
            print(item)
            raise
        for child in node['children']:
            dump_node(child, level+1)
        if level == 0:
            ans.append('')
    [dump_node(c) for c in root['children']]
    return '\n'.join(ans)

def dump_tags_model(m):
    from PyQt5.Qt import QModelIndex, Qt
    ans, indent = [], '  '
    def dump_node(index, level=-1):
        if level > -1:
            ans.append(indent*level + index.data(Qt.UserRole).dump_data())
        for i in xrange(m.rowCount(index)):
            dump_node(m.index(i, 0, index), level + 1)
        if level == 0:
            ans.append('')
    dump_node(QModelIndex())
    return '\n'.join(ans)

def test_tag_browser(library_path=None):
    ' Compare output of server and GUI tag browsers '
    from calibre.library import db
    olddb = db(library_path)
    db = olddb.new_api
    opts = categories_settings({}, db)
    # opts = opts._replace(hidden_categories={'publisher'})
    category_data = db.get_categories(sort=opts.sort_by, first_letter_sort=opts.collapse_model == 'first letter')
    data = render_categories(db.field_metadata, opts, category_data)
    srv_data = dump_categories_tree(data)
    from calibre.gui2 import Application, gprefs
    from calibre.gui2.tag_browser.model import TagsModel
    prefs = {
        'tags_browser_category_icons':gprefs['tags_browser_category_icons'],
        'tags_browser_collapse_at':opts.collapse_at,
        'tags_browser_partition_method': opts.collapse_model,
        'tag_browser_dont_collapse': opts.dont_collapse,
    }
    app = Application([])
    m = TagsModel(None, prefs)
    m.set_database(olddb, opts.hidden_categories)
    m_data = dump_tags_model(m)
    from calibre.gui2.tweak_book.diff.main import Diff
    d = Diff(show_as_window=True)
    d.string_diff(m_data, srv_data, left_name='GUI', right_name='server')
    d.exec_()
    del app
# }}}

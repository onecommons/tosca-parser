#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import copy
import logging
import os
import threading
from toscaparser.common.exception import ExceptionCollector
from toscaparser.common.exception import ValidationError
from toscaparser.extensions.exttools import ExtTools
import toscaparser.utils.yamlparser

log = logging.getLogger('tosca')
globals = threading.local()
globals._types = None          # Dict[str, StatefulEntityType]
globals._parent_types = None  # Dict[str, List[StatefulEntityType]]

class Namespace(dict):
    def __init__(self, nested_custom_types, file_name, namespace_id=""):
        self.all_namespaces = nested_custom_types
        self.file_name = file_name
        self.namespace_id = namespace_id
        self.imports = {}  # map global specifiers to prefix
        # register this namespace:
        self.all_namespaces[file_name] = self
        self.global_namespace = False
        # base
        # root
        # repository
        # self.metadata = {}  # local_name => section?


    def get_local_name(self, global_name):
        local, sep, module_name = global_name.partition("@")
        if module_name == self.namespace_id:
            return local  # type is defined here
        prefix = self.imports.get(module_name)
        if prefix:
            return prefix + "." + local
        elif prefix is None:
            return None  # not imported
        else:
            return local # no prefix

    def add_with_prefix(self, local_custom_defs: "Namespace", prefix):
        self.imports[local_custom_defs.namespace_id] = prefix
        for k, v in local_custom_defs.items():
          if prefix:
              self[f"{prefix}.{k}"] = v
          else:
              self[k] = v
        for imported, iprefix in local_custom_defs.imports.items():
          if prefix:
              self.imports[imported] = f"{prefix}.{iprefix}"
          else:
              self.imports[imported] = iprefix

    def add_entitytype(self, entitytype):
        # cache the type object
        entitytype["_source"]["local_name"]

class EntityType(object):
    '''Base class for TOSCA elements.'''

    SECTIONS = (DERIVED_FROM, PROPERTIES, ATTRIBUTES, REQUIREMENTS,
                INTERFACES, CAPABILITIES, TYPE, ARTIFACTS) = \
               ('derived_from', 'properties', 'attributes', 'requirements',
                'interfaces', 'capabilities', 'type', 'artifacts')

    TOSCA_DEF_SECTIONS = ['node_types', 'data_types', 'artifact_types',
                          'group_types', 'relationship_types',
                          'capability_types', 'interface_types',
                          'policy_types', 'types']

    '''TOSCA definition file.'''
    TOSCA_DEF_FILE = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "TOSCA_definition_1_3.yaml")

    loader = toscaparser.utils.yamlparser.load_yaml

    TOSCA_DEF_LOAD_AS_IS = loader(TOSCA_DEF_FILE)

    # Map of definition with pre-loaded values of TOSCA_DEF_FILE_SECTIONS
    TOSCA_DEF = {}
    for section in TOSCA_DEF_SECTIONS:
        if section in TOSCA_DEF_LOAD_AS_IS.keys():
            value = TOSCA_DEF_LOAD_AS_IS[section]
            for key in value.keys():
                TOSCA_DEF[key] = value[key]

    RELATIONSHIP_TYPE = (DEPENDSON, HOSTEDON, CONNECTSTO, ATTACHESTO,
                         LINKSTO, BINDSTO) = \
                        ('tosca.relationships.DependsOn',
                         'tosca.relationships.HostedOn',
                         'tosca.relationships.ConnectsTo',
                         'tosca.relationships.AttachesTo',
                         'tosca.relationships.network.LinksTo',
                         'tosca.relationships.network.BindsTo')

    NODE_PREFIX = 'tosca.nodes.'
    RELATIONSHIP_PREFIX = 'tosca.relationships.'
    CAPABILITY_PREFIX = 'tosca.capabilities.'
    INTERFACE_PREFIX = 'tosca.interfaces.'
    ARTIFACT_PREFIX = 'tosca.artifacts.'
    POLICY_PREFIX = 'tosca.policies.'
    GROUP_PREFIX = 'tosca.groups.'
    # currently the data types are defined only for network
    # but may have changes in the future.
    DATATYPE_PREFIX = 'tosca.datatypes.'
    DATATYPE_NETWORK_PREFIX = DATATYPE_PREFIX + 'network.'
    TOSCA = 'tosca'
    _source = None

    @staticmethod
    def _parent_types():
        return None
        return globals._parent_types

    @staticmethod
    def find_type(name, custom_defs_guard = None):
        if globals._types:
            type_def = globals._types.get(name)
            if type_def:
                if (
                    custom_defs_guard is not None
                    and custom_defs_guard is not type_def.custom_def
                ):
                    return None
            return type_def
        else:
            return None

    @staticmethod
    def add_type(name, typedef, guard=False):
        if globals._types is not None:
            if guard and globals._types:
                if typedef.custom_def is not next(iter(globals._types.values())).custom_def:
                    return False
            globals._types[name] = typedef
            return True
        return False

    @staticmethod
    def reset_caches():
        globals._types = {}
        globals._parent_types = {}

    def derived_from(self, defs):
        '''Return a type this type is derived from.'''
        parent = self.entity_value(defs, 'derived_from')
        if isinstance(parent, list):  # multiple inheritance
            return parent[0]
        else:
            return parent

    def is_derived_from(self, type_str):
        '''Check if object inherits from the given type.

        Returns true if this object is derived from 'type_str'.
        False otherwise.
        '''
        if "@" in type_str:
            return self.global_name == type_str
        elif not self.type:
            return False
        elif self.type == type_str:
            return True
        else:
            for p in self.parent_types():
                if p.is_derived_from(type_str):
                    return True
            return False

    def entity_value(self, defs, key):
        if defs and key in defs:
            return defs[key]

    @property
    def parent_type(self):
        return None

    def parent_types(self):
        parent = self.parent_type
        if parent:
            yield parent

    def _ancestors(self, seen=None):
        if seen is None:
            seen = {self.type}
            yield self
        for p in self.parent_types():
            if p.type not in seen:
                seen.add(p.type)
                yield p
                for p in p._ancestors(seen):
                    yield p

    def get_value(self, ndtype, defs=None, parent=None, merge=False, add_namespace=False):
        '''
        If set, `defs` should be from the template otherwise uses defs from this type
        `parent` merges in defs from this type and ancestors
        '''
        value = None
        if defs is None:
            if not hasattr(self, 'defs'):
                return None
            defs = self.defs
        if defs and ndtype in defs:
            # copy the value to avoid that next operations add items in the
            # item definitions
            value = defs[ndtype]
        if parent:
            value = copy.copy(value)
            if not self:
                return value
            for p in self.ancestors():
                if p.defs and ndtype in p.defs:
                    # get the parent value
                    parent_value = p.defs[ndtype]
                    if value:
                        if isinstance(value, dict):
                            # add items if key is missing
                            assert isinstance(parent_value, dict), ndtype
                            for k, v in parent_value.items():
                                if add_namespace and "type" in v and p.custom_def:
                                    v["!namespace"] = p.custom_def
                                if k not in value:
                                    value[k] = v
                                elif merge and isinstance(v, dict) and isinstance(value[k], dict):
                                    # merge value with parent and merge "metadata" keys if present

                                    value_value = value[k]
                                    metadata = "metadata" in value_value
                                    cls = getattr(value_value, "mapCtor", value_value.__class__)
                                    value[k] = cls(v, **value_value)
                                    if metadata and "metadata" in v:
                                        value[k]["metadata"] = cls(v["metadata"], **value_value["metadata"])

                        elif merge and isinstance(value, list):
                            # append parent items if unique to list
                            assert isinstance(parent_value, list), ndtype
                            for p_value in parent_value:
                                if p_value not in value:
                                    if add_namespace and p.custom_def and isinstance(p_value, dict):
                                         _set_req_namespaces(p_value, p.custom_def)
                                    value.append(p_value)
                    else:
                        value = copy.copy(parent_value)
        return value

    def get_definition(self, ndtype):
        # retrieves property and attribute definitions
        # XXX validate that the derived type is compatible with the base type
        return self.get_value(ndtype, None, True, True)

def _set_req_namespaces(req, namespace):
    name, value = list(req.items())[0]
    if isinstance(value, dict):
        for key in ["node", "capability", "relationship"]:
            if key in value:
                # relationship might be a dict
                if not isinstance(value[key], dict) or "type" in value[key]:
                    value[f"!namespace-{key}"] = namespace


_last_version = None
def update_definitions(exttools, version, loader=toscaparser.utils.yamlparser.load_yaml):
    global _last_version
    if _last_version == version:
        return  # don't reload a version we already loaded
    extension_defs_file = exttools.get_defs_file(version)
    nfv_def_file = loader(extension_defs_file)
    if not nfv_def_file:  # loading failed
        return
    for section in EntityType.TOSCA_DEF_SECTIONS:
        if section in nfv_def_file.keys():
            value = nfv_def_file[section]
            for key in value.keys():
                if key in EntityType.TOSCA_DEF:
                    # replace sections
                    EntityType.TOSCA_DEF[key].update(value[key])
                else:
                    EntityType.TOSCA_DEF[key] = value[key]
    _last_version = version

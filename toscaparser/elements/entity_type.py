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

logger = logging.getLogger('tosca')
class _LocalState(threading.local):
    def __init__(self, **kw):
        self._types = None          # Dict[str, StatefulEntityType]
        self._parent_types = None  # Dict[str, List[StatefulEntityType]]
        self._annotate_namespaces = True  # disable for testing
globals = _LocalState()


class Namespace(dict):
    def __init__(
        self, nested_custom_types, source_info, namespace_id="", shared_namespace=False
    ):
        self.all_namespaces = nested_custom_types
        self.source_info = source_info
        self.namespace_id = namespace_id
        self.imports = {}  # map global specifiers to prefixed local name
        # register this namespace:
        self.all_namespaces[namespace_id] = self
        self.shared_namespace = shared_namespace
        # self.metadata = {}  # local_name => section?

    def get_local_name(self, global_name):
        local, sep, module_name = global_name.partition("@")
        if not module_name:
            return local # built-in type
        if module_name == self.namespace_id:
            return local  # type is defined here
        prefixed = self.imports.get(global_name)
        if prefixed:
            return prefixed
        elif local in self:
            return local  # no prefix
        else:
            return None

    def find_prefix(self, local_name):
        if "." in local_name:
            for global_name, prefixed in self.imports.items():
                if local_name == prefixed:
                    local, sep, module_name = global_name.partition("@")
                    return prefixed[0:-len(local)-1]
        return ""

    def get_global_name_and_prefix(self, local_name):
        if "." in local_name:  # might be prefixed
            for global_name, prefix in self.imports.items():
                if local_name == prefix:
                    return global_name, prefix
        return self.get_global_name(local_name), ""

    def get_global_name(self, local_name):
        if self.namespace_id and local_name in self:
            # this type could have been imported, try to get the original name
            _source = self[local_name].get("_source")
            if isinstance(_source, dict):
                name = _source.get("local_name")
                namespace_id = _source.get("namespace_id")
                if name and namespace_id:
                    return f"{name}@{namespace_id}"
            if "." in local_name:  # might be prefixed
                for global_name, prefix in self.imports.items():
                    if local_name == prefix:
                        return global_name
            return f"{local_name}@{self.namespace_id}"
        else:
            return local_name

    def add_with_prefix(self, local_custom_defs: "Namespace", prefix):
        if not prefix:
            self.imports.update(local_custom_defs.imports)
        for k, v in local_custom_defs.items():
            if prefix:
                prefixed = f"{prefix}.{k}"
                self[prefixed] = v
                self.imports[local_custom_defs.get_global_name(k)] = prefixed
            else:
                self[k] = v

    def find_namespace(self, namespace_id):
        if not namespace_id:
            return self
        return self.all_namespaces.get(namespace_id, self)

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
        if not self.type:
            return False
        elif self.type == type_str or self.global_name == type_str:
            return True
        elif self._implements(type_str):
            return True
        else:
            for p in self.parent_types():
                if p.is_derived_from(type_str):
                    return True
            return False

    def entity_value(self, defs, key):
        if defs and key in defs:
            return defs[key]

    def _implements(self, type_str):
        return False

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

    def get_value(self, ndtype, defs=None, parent=False, merge=False, add_namespace=False):
        '''
        If set, `defs` should be from the template otherwise uses defs from this type
        `parent` merges in defs from this type and ancestors
        '''
        add_namespace = add_namespace and globals._annotate_namespaces
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
            if hasattr(value, "mapCtor"):
                value = value.mapCtor(value)
            else:
                value = copy.copy(value)
            for p in self.ancestors():  # [self, parent, grandparent]
                check_namespace = add_namespace and isinstance(p.custom_def, Namespace) and p.custom_def.namespace_id and p._source
                if p.defs and ndtype in p.defs:
                    # get the parent value
                    parent_value = p.defs[ndtype]
                    if value:
                        if isinstance(value, dict):
                            # add items if key is missing
                            assert isinstance(parent_value, dict), ndtype
                            for k, v in parent_value.items():
                                if k not in value:
                                    value[k] = v
                                    if check_namespace and "type" in v:
                                        v["!namespace"] = p.custom_def.namespace_id
                                elif merge and isinstance(v, dict) and isinstance(value[k], dict):
                                    # merge value with parent and merge "metadata" keys if present
                                    value_value = value[k]
                                    metadata = "metadata" in value_value
                                    cls = getattr(value_value, "mapCtor", value_value.__class__)
                                    value[k] = cls(v, **value_value)
                                    if check_namespace and "type" in v and "type" not in value_value:
                                        value[k]["!namespace"] = p.custom_def.namespace_id
                                    if metadata and "metadata" in v:
                                        value[k]["metadata"] = cls(v["metadata"], **value_value["metadata"])

                        elif merge and isinstance(value, list):
                            # append parent items if unique to list
                            assert isinstance(parent_value, list), ndtype
                            for p_value in parent_value:
                                if p_value not in value:
                                    if check_namespace and isinstance(p_value, dict) and ndtype == "requirements":
                                        _set_req_namespaces(p_value, p.custom_def.namespace_id)
                                    value.append(p_value)
                    else:
                        # if missing so far then copy the parent
                        if hasattr(parent_value, "mapCtor"):
                            value = parent_value.mapCtor(parent_value)
                        else:
                            value = copy.copy(parent_value)

                        if check_namespace:
                            if isinstance(parent_value, dict):
                                for k, v in parent_value.items():
                                    if isinstance(v, dict) and "type" in v:
                                        v["!namespace"] = p.custom_def.namespace_id
                            elif isinstance(value, list) and ndtype == "requirements":
                                for p_value in value:
                                    if isinstance(p_value, dict):
                                        _set_req_namespaces(p_value, p.custom_def.namespace_id)
        return value

    def get_definition(self, ndtype):
        # retrieves property and attribute definitions
        # XXX validate that the derived type is compatible with the base type
        return self.get_value(ndtype, None, True, True, True)

def _set_req_namespaces(req, namespace):
    if not globals._annotate_namespaces:
        return
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

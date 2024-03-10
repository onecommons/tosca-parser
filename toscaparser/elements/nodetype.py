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

import logging
from toscaparser.common.exception import ExceptionCollector
from toscaparser.common.exception import UnknownFieldError
from toscaparser.elements.capabilitytype import CapabilityType
from toscaparser.elements.entity_type import Namespace, _set_req_namespaces
import toscaparser.elements.interfaces as ifaces
from toscaparser.elements.relationshiptype import RelationshipType
from toscaparser.elements.statefulentitytype import StatefulEntityType
from toscaparser.common.exception import InvalidTypeError, InvalidTypeDefinition


def _find_key_in_list(seq, key):
    for i, item in enumerate(seq):
        if isinstance(item, dict) and len(item) == 1 and key in item:
            return i
    return -1


def _merge_dict_lists(base, current, mergefn=None):
    merged = current[:]
    for item in base:
        key = next(iter(item))
        # add base item if not present in current
        index = _find_key_in_list(current, key)
        if index == -1:
            merged.append(item)
        elif mergefn:
            merged[index] = {key: mergefn(item[key], current[index][key])}
    return merged


class NodeType(StatefulEntityType):
    '''TOSCA built-in node type.'''
    SECTIONS = (DERIVED_FROM, METADATA, PROPERTIES, VERSION, DESCRIPTION, ATTRIBUTES,
                REQUIREMENTS, CAPABILITIES, INTERFACES, ARTIFACTS, INSTANCE_KEYS, _SOURCE) = \
               ('derived_from', 'metadata', 'properties', 'version',
                'description', 'attributes', 'requirements', 'capabilities',
                'interfaces', 'artifacts', 'instance_keys', '_source')

    REQUIREMENTS_SECTION = (NODE, CAPABILITY, RELATIONSHIP, OCCURRENCES,
                            NODE_FILTER, DESCRIPTION, METADATA, TITLE) = \
                           ('node', 'capability', 'relationship',
                            'occurrences', 'node_filter', 'description', 'metadata', 'title')

    def __init__(self, ntype, custom_def=None):
        super(NodeType, self).__init__(ntype, self.NODE_PREFIX, custom_def)
        self.ntype = ntype
        self._requirement_definitions = None
        self._validate_keys()

    @property
    def parent_type(self):
        '''Return a node this node is derived from.'''
        if not hasattr(self, 'defs'):
            return None
        pnode = self.derived_from(self.defs)
        if pnode:
            if pnode == self.type:
                # circular reference
                ExceptionCollector.appendException(
                    InvalidTypeError(what=self.type))
                return None
            return NodeType(pnode, self.custom_def)
        elif self.type != "tosca.nodes.Root":
            # if derived_from is missing, default to root type for nodes
            return NodeType("tosca.nodes.Root", self.custom_def)

    @property
    def relationship(self):
        '''Return a dictionary of relationships to other node types.

        This method returns a dictionary of named relationships that nodes
        of the current node type (self) can have to other nodes (of specific
        types) in a TOSCA template.

        '''
        relationship = {}
        requires = self.get_all_requirements()
        if requires:
            keyword = None
            node_type = None
            for require in requires:
                for key, req in require.items():
                    if 'relationship' in req:
                        relation = req.get('relationship')
                        if 'type' in relation:
                            relation = relation.get('type')
                        node_type = req.get('node')
                        value = req
                        if node_type:
                            keyword = 'node'
                        else:
                            # If value is a dict and has a type key
                            # we need to lookup the node type using
                            # the capability type
                            value = req
                            if isinstance(value, dict):
                                captype = value['capability']
                                value = (self.
                                         _get_node_type_by_cap(captype))
                            keyword = key
                            node_type = value
                        rtype = RelationshipType(relation, keyword,
                                                 self.custom_def)
                        relatednode = NodeType(node_type, self.custom_def)
                        relationship[rtype] = relatednode
        return relationship

    def _get_node_type_by_cap(self, cap):
        '''Find the node type that has the provided capability

        This method will lookup all node types if they have the
        provided capability.
        '''

        # Filter the node types
        node_types = [node_type for node_type in self.TOSCA_DEF.keys()
                      if node_type.startswith(self.NODE_PREFIX) and
                      node_type != 'tosca.nodes.Root']
        custom_node_types = [node_type for node_type in self.custom_def.keys()
                             if node_type.startswith(self.NODE_PREFIX) and
                             node_type != 'tosca.nodes.Root']

        for node_type in node_types + custom_node_types:
            if node_type in self.TOSCA_DEF:
                node_def = self.TOSCA_DEF[node_type]
            else:
                node_def = self.custom_def[node_type]
            if isinstance(node_def, dict) and 'capabilities' in node_def:
                node_caps = node_def['capabilities']
                for value in node_caps.values():
                    if isinstance(value, dict) and \
                            'type' in value and value['type'] == cap:
                        return node_type

    def get_capability_typedefs(self):
        '''Return a list of capability type objects.'''
        typecapabilities = []
        caps = self.get_definition(self.CAPABILITIES)
        if caps:
            # 'name' is symbolic name of the capability
            # 'value' is a dict { 'type': <capability type name> }
            for name, value in caps.items():
                ctype = value.get('type')
                namespace_id = value.get("!namespace", None)
                custom_def = self.custom_def
                if namespace_id and isinstance(self.custom_def, Namespace):
                    custom_def = self.custom_def.find_namespace(namespace_id)
                cap = CapabilityType(name, ctype, self.type, custom_def)
                typecapabilities.append(cap)
        return typecapabilities

    def get_capabilities_def(self):
        '''Return a dictionary of capability name-objects pairs.'''
        return {cap.name: cap
                for cap in self.get_capability_typedefs()}

    @property
    def requirements(self):
        return self.get_definition(self.REQUIREMENTS)

    @staticmethod
    def merge_requirement_definition(base, current):
        if isinstance(base, str):
            return dict(node=base, **current)
        else:
            tpl = dict(base, **current)
        if base.get('node_filter') and current.get('node_filter'):
            tpl["node_filter"] = {}
            bfilters = base["node_filter"]
            cfilters = current["node_filter"]
            for key in ["requirements", "properties", "match"]:
                if bfilters.get(key):
                    mergefn = NodeType.merge_requirement_definition if key == "requirements" else None
                    tpl["node_filter"][key] = _merge_dict_lists(bfilters[key], cfilters.get(key, []), mergefn)
                elif key in cfilters:
                    tpl["node_filter"][key] = cfilters[key]
        if base.get('metadata') and current.get('metadata'):
            # merge metadata
            tpl['metadata'] = dict(base['metadata'], **current['metadata'])
        return tpl

    def get_all_requirements(self):
        # return list of requirements with any shorthand syntax normalized
        if self._source and isinstance(self.custom_def, Namespace) and self.custom_def.namespace_id:
            local_reqs = self.get_value(self.REQUIREMENTS)
            if isinstance(local_reqs, list):
                for req in local_reqs:
                    if req and isinstance(req, dict):
                        # add so these now so we don't merge in a parent type's namespace_id below
                        _set_req_namespaces(req, self.custom_def.namespace_id)
        reqs_tpl = self.requirements
        # avoid crashing:
        if reqs_tpl is None or self._requirement_definitions and "__invalid" in self._requirement_definitions:
            return []
        requirements = {}
        # merge requirements with the same name
        for tpl in reqs_tpl:
            name, value = list(tpl.items())[0]
            # note that first match returned by get_value() will be the most derived one
            if name in requirements:
                # update value with current (more derived) value
                current = requirements[name][name]
                if isinstance(current, str):
                    # diverges from 3.7.3.2.1 Simple grammar (Capability Type only)
                    tpl = {name: dict(value, node = current)}
                else:
                    tpl = {name: self.merge_requirement_definition(value, current)}
            elif isinstance(value, str):
                # diverges from 3.7.3.2.1 Simple grammar (Capability Type only)
                tpl = {name : dict(node = value)}
            requirements[name] = tpl
        return list(requirements.values())

    @property
    def lifecycle_inputs(self):
        '''Return inputs to life cycle operations if found.'''
        inputs = []
        interfaces = self.interfaces
        if interfaces:
            for name, value in interfaces.items():
                if name == ifaces.LIFECYCLE:
                    for x, y in value.items():
                        if x == 'inputs':
                            for i in y.iterkeys():
                                inputs.append(i)
        return inputs

    def get_capability(self, name):
        caps = self.get_capabilities_def()
        if caps and name in caps:
            return caps[name].value

    def get_capability_type(self, name):
        captype = self.get_capability(name)
        if captype and name in captype:
            return captype[name].value

    def _validate_keys(self):
        if self.defs:
            for key in self.defs:
                if key not in self.SECTIONS:
                    ExceptionCollector.appendException(
                        UnknownFieldError(what='Nodetype"%s"' % self.ntype,
                                          field=key))
                if key == self.REQUIREMENTS:
                    reqs = self.defs[self.REQUIREMENTS]
                    if not isinstance(reqs, list):
                        ExceptionCollector.appendException(
                            InvalidTypeDefinition(type='Nodetype %s' % self.ntype,
                                              what='"requirements" field value must be a list'))
                        self._requirement_definitions = dict(__invalid={})
                        continue
                    for req in reqs:
                        if not isinstance(req, dict) or not req:
                            ExceptionCollector.appendException(
                                InvalidTypeDefinition(type='Nodetype %s' % self.ntype,
                                                  what='bad value for requirement list item: "%s"' % (req) ))
                        reqvalue = list(req.values())[0]
                        if not isinstance(reqvalue, (str, dict)) or len(req) != 1:
                            what = 'invalid requirement "%s"' % req
                            ExceptionCollector.appendException(
                                InvalidTypeDefinition(type='Nodetype %s' % self.ntype, what=what))
                            # set this to avoid future exceptions during parsing
                            self._requirement_definitions = dict(__invalid={})
                        elif isinstance(reqvalue, dict):
                            self._validate_requirements_keys(reqvalue, 'Nodetype "%s"' % self.ntype)

    def _validate_requirements_keys(self, requirement, where):
        for key in requirement.keys():
            if key not in self.REQUIREMENTS_SECTION and not key.startswith("!namespace"):
                ExceptionCollector.appendException(
                    UnknownFieldError(
                        what='"requirements" of %s' % where,
                        field=key))

    @property
    def requirement_definitions(self):
        """
        Returns a dictionary of requirements with any shorthand syntax normalized and the relationship type added.
        """
        if self._requirement_definitions is None:
            self._requirement_definitions = {}
            reqs = self.get_all_requirements()
            if not reqs:
                return self._requirement_definitions
            for req_dict in reqs:
                name, reqDef = list(req_dict.items())[0]
                # get_all_requirements() will have normalized with into a dictionary already
                # normalize 'relationship' key:
                # 3.7.3 Requirement definition p.122
                # if "relationship" is present, this will be either the name of the relationship type
                # or a dictionary containing "type"
                relDef = reqDef.get('relationship')
                if not relDef:
                    relDef = dict(type = "tosca.relationships.Root")
                elif isinstance(relDef, dict):
                    relDef = relDef.copy()
                else:
                    relDef = dict(type = relDef)
                reqDef = reqDef.copy()
                reqDef['relationship'] = relDef
                self._requirement_definitions[name] = reqDef

        return self._requirement_definitions

    def get_requirement_definition(self, requirementName):
        # return a normalized requirements definition that always include a relationship
        defaultDef = dict(relationship=dict(type = "tosca.relationships.Root"))
        return self.requirement_definitions.get(requirementName, defaultDef)

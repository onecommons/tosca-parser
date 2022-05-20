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

from toscaparser.common.exception import ExceptionCollector
from toscaparser.common.exception import MissingTypeError
from toscaparser.elements.entity_type import EntityType
from toscaparser.elements.property_definition import PropertyDef
from toscaparser.unsupportedtype import UnsupportedType


class StatefulEntityType(EntityType):
    '''Class representing TOSCA states.'''

    interfaces_node_lifecycle_operations = ['create',
                                            'configure', 'start',
                                            'stop', 'delete']

    interfaces_relationship_configure_operations = ['pre_configure_source',
                                                    'pre_configure_target',
                                                    'post_configure_source',
                                                    'post_configure_target',
                                                    'add_target',
                                                    'remove_target',
                                                    'add_source',
                                                    'remove_source',
                                                    'target_changed']

    def __init__(self, entitytype, prefix, custom_def=None):
        entire_entitytype = entitytype
        if UnsupportedType.validate_type(entire_entitytype):
            self.defs = None
        else:
            if entitytype.startswith(self.TOSCA + ":"):
                entitytype = entitytype[(len(self.TOSCA) + 1):]
                entire_entitytype = prefix + entitytype
            if not entitytype.startswith(self.TOSCA):
                entire_entitytype = prefix + entitytype
            if custom_def and entitytype in custom_def:
                self.defs = custom_def[entitytype]
            elif entire_entitytype in self.TOSCA_DEF:
                self.defs = self.TOSCA_DEF[entire_entitytype]
                entitytype = entire_entitytype
            elif entitytype in self.TOSCA_DEF:
                self.defs = self.TOSCA_DEF[entitytype]
            else:
                self.defs = None
                ExceptionCollector.appendException(
                    MissingTypeError(what=entitytype))
        self.type = entitytype
        self.custom_def = custom_def
        self._source = self.defs and self.defs.get("_source") or None

    @property
    def parent_type(self):
        """Return a relationship this reletionship is derived from."""
        prel = self.derived_from(self.defs)
        if prel:
            # prefix is only used to expand "tosca:Type"
            return StatefulEntityType(prel, self.NODE_PREFIX, custom_def=self.custom_def)

    def get_properties_def_objects(self):
        '''Return a list of property definition objects.'''
        properties = []
        props = self.get_definition(self.PROPERTIES)
        if props:
            for prop, schema in props.items():
                properties.append(PropertyDef(prop, None, schema))
        return properties

    def get_properties_def(self):
        '''Return a dictionary of property definition name-object pairs.'''
        return {prop.name: prop
                for prop in self.get_properties_def_objects()}

    def get_property_def_value(self, name):
        '''Return the property definition associated with a given name.'''
        props_def = self.get_properties_def()
        if props_def and name in props_def.keys():
            return props_def[name].value

    def get_attributes_def_objects(self):
        '''Return a list of attribute definition objects.'''
        attrs = self.get_value(self.ATTRIBUTES, parent=True)
        if attrs:
            return [PropertyDef(attr, None, schema)
                    for attr, schema in attrs.items()]
        return []

    def get_attributes_def(self):
        '''Return a dictionary of attribute definition name-object pairs.'''
        return {attr.name: attr
                for attr in self.get_attributes_def_objects()}

    def get_attribute_def_value(self, name):
        '''Return the attribute definition associated with a given name.'''
        attrs_def = self.get_attributes_def()
        if attrs_def and name in attrs_def.keys():
            return attrs_def[name].value

    @property
    def interfaces(self):
        cls = getattr(self.defs, "mapCtor", self.defs.__class__)
        interfaces = cls()
        # reversed so most derived is last
        for p in reversed(list(self.ancestors())):
            p_interfaces = p.defs and p.defs.get(self.INTERFACES)
            if p_interfaces:
                for iname, idef in p_interfaces.items():
                    if iname not in interfaces:
                        cls = getattr(idef, "mapCtor", idef.__class__)
                        interfaces[iname] = cls(idef)
                    elif idef:
                        merged = interfaces[iname]
                        for k, v in idef.items():
                            merged[k] = v
        return interfaces

    def get_interface_requirements(self, entity_tpl=None):
        tpl_interfaces = self.get_value(self.INTERFACES, entity_tpl, True)
        relationships = []
        if tpl_interfaces:
            for i in tpl_interfaces.values():
                req = i.get('requirements')
                if req:
                    assert isinstance(req, list)
                    for rel in req:
                        if rel not in relationships:
                            relationships.append(rel)
        return relationships

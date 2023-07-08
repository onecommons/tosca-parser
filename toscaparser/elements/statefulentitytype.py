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
from toscaparser.common.exception import TypeMismatchError
from toscaparser.common.exception import UnknownFieldError, ValidationError
from toscaparser.elements.entity_type import EntityType
from toscaparser.elements.property_definition import PropertyDef
from toscaparser.unsupportedtype import UnsupportedType
from toscaparser.elements.interfaces import INTERFACE_DEF_RESERVED_WORDS
from toscaparser.elements.interfaces import CONFIGURE, CONFIGURE_SHORTNAME
from toscaparser.elements.interfaces import LIFECYCLE,  LIFECYCLE_SHORTNAME
from toscaparser.elements.interfaces import INSTALL,  INSTALL_SHORTNAME
from toscaparser.elements.interfaces import merge_interfacedefs


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
        if not isinstance(entitytype, str):
            ExceptionCollector.appendException(TypeMismatchError(
                                               what=entitytype,
                                               type="string"))
            self.defs = None
            self.type = str(entitytype)
            return
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
        source = self.defs and self.defs.get("_source") or None
        if isinstance(source, dict):
            source = source.get("path")
        self._source = source
        self.__ancestors = None
        self._interfaces = None
        self._property_defs = None
        self._attribute_defs = None
        self._validate_interfaces()

    def ancestors(self):
        if self.__ancestors is None:
            self.__ancestors = list(self._ancestors())
        return self.__ancestors

    def parent_types(self):
        _parent_types = self._parent_types()
        if _parent_types is None or self.__class__ is StatefulEntityType:
            return list(self._find_parent_types())
        if self.type not in _parent_types:
            parents = list(self._find_parent_types())
            _parent_types[self.type] = parents
        return _parent_types[self.type]

    def _find_parent_types(self):
        if not self.defs:
            return
        parents = self.entity_value(self.defs, 'derived_from')
        if isinstance(parents, (list, tuple)):  # multiple inheritance
            for pnode in parents:
                if self.__class__ is StatefulEntityType:
                    #  prefix is only used to expand "tosca:Type"
                    yield self.__class__(pnode, self.NODE_PREFIX, self.custom_def)
                else:
                    yield self.__class__(pnode, self.custom_def)
        else:
            parent = self.parent_type
            if parent:
                yield parent

    @property
    def parent_type(self):
        """Return a relationship this reletionship is derived from."""
        prel = self.derived_from(self.defs)
        if prel:
            # prefix is only used to expand "tosca:Type"
            return StatefulEntityType(prel, self.NODE_PREFIX, custom_def=self.custom_def)

    def get_properties_def_objects(self):
        '''Return a list of property definition objects.'''
        if self._property_defs is None:
            properties = []
            props = self.get_definition(self.PROPERTIES)
            if props:
                for prop, schema in props.items():
                    properties.append(PropertyDef(prop, None, schema))
            self._property_defs = properties
        return self._property_defs

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
        if self._attribute_defs is None:
            _attribute_defs = []
            attrs = self.get_definition(self.ATTRIBUTES)
            if attrs:
                _attribute_defs = [PropertyDef(attr, None, schema)
                                   for attr, schema in attrs.items()]
            self._attribute_defs = _attribute_defs
        return self._attribute_defs

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
        if self.defs is None:
            return {}
        if self._interfaces is None:
            cls = getattr(self.defs, "mapCtor", self.defs.__class__)
            interfaces = cls()
            # reversed so most derived is last
            for p in reversed(list(self.ancestors())):
                p_interfaces = p.defs and p.defs.get(self.INTERFACES)
                if p_interfaces:
                    interfaces = merge_interfacedefs(interfaces, p_interfaces, p._source)
            self._interfaces = interfaces
        return self._interfaces

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

    def _validate_interfaces(self, entity_template=None):
        if entity_template:
            error_source = entity_template
            ifaces = self.get_value(self.INTERFACES, entity_template.entity_tpl)
        else:
            error_source = self
            ifaces = self.get_value(self.INTERFACES)

        if ifaces:
            for name, value in ifaces.items():
                operation_names = None
                if not isinstance(value, dict):
                    ExceptionCollector.appendException(TypeMismatchError(
                                                       what=f"interface {name}",
                                                       type="dict"))
                    continue
                if name == 'Mock':
                    error_source._common_validate_field(
                        value, INTERFACE_DEF_RESERVED_WORDS,
                        'interfaces')
                elif name == 'defaults':
                    error_source._common_validate_field(
                        value,
                        ['implementation', 'inputs', 'outputs'],
                        'interfaces')
                elif name in (LIFECYCLE, LIFECYCLE_SHORTNAME):
                    operation_names = self.interfaces_node_lifecycle_operations
                    error_source._common_validate_field(
                        value, INTERFACE_DEF_RESERVED_WORDS + operation_names,
                        'interfaces')
                elif name in (CONFIGURE, CONFIGURE_SHORTNAME):
                    operation_names = self.interfaces_relationship_configure_operations
                    error_source._common_validate_field(
                        value, INTERFACE_DEF_RESERVED_WORDS + operation_names,
                        'interfaces')
                elif name == INSTALL_SHORTNAME and "type" not in value:
                    operation_names = list(self.TOSCA_DEF[INSTALL]["operations"])
                    error_source._common_validate_field(
                        value, INTERFACE_DEF_RESERVED_WORDS + operation_names,
                        'interfaces')
                elif (name in self.interfaces
                      or name in self.TOSCA_DEF):
                    # interface name or interface type name
                    operation_names = self._collect_custom_iface_operations(name)
                    error_source._common_validate_field(
                        value, INTERFACE_DEF_RESERVED_WORDS + operation_names,
                        'interfaces')
                else:
                    if entity_template:
                        msg = '"interfaces" of template "%s"' % entity_template.name
                    else:
                        msg = '"interfaces" of type "%s"' % self.type
                    ExceptionCollector.appendException(
                        UnknownFieldError(
                            what=msg, field=name))

                if operation_names and "operations" in value:
                    error_source._common_validate_field(value["operations"], operation_names, 'interfaces')

    def _collect_custom_iface_operations(self, name):
        allowed_operations = []
        nodetype_iface_def = self.interfaces.get(name, self.TOSCA_DEF.get(name))
        if "operations" in nodetype_iface_def:
            allowed_operations.extend(nodetype_iface_def["operations"].keys())
        else:
            allowed_operations.extend(nodetype_iface_def.keys())
        if 'type' in nodetype_iface_def:
            iface_type = nodetype_iface_def['type']
            if iface_type in self.custom_def:
                iface_type_def = self.custom_def[iface_type]
            else:
                iface_type_def = self.TOSCA_DEF[iface_type]
            if "operations" in iface_type_def:
                allowed_operations.extend(iface_type_def["operations"].keys())
            else:
                allowed_operations.extend(iface_type_def.keys())

        allowed_operations = [op for op in allowed_operations if
                              op not in INTERFACE_DEF_RESERVED_WORDS]
        return allowed_operations

    def _common_validate_field(self, schema, allowedlist, section):
        if schema is None:
            ExceptionCollector.appendException(
                ValidationError(
                    message=('Missing value for "%s". Must contain one of: "%s"'
                             % (section, ", ".join(allowedlist)))))
        else:
            for name in schema:
                if name not in allowedlist:
                    ExceptionCollector.appendException(
                        UnknownFieldError(
                            what=('"%(section)s" of type "%(nodename)s"'
                                  % {'section': section, 'nodename': self.type}),
                            field=name))

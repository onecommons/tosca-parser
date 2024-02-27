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

from toscaparser.capabilities import Capability
from toscaparser.common.exception import ExceptionCollector
from toscaparser.common.exception import MissingRequiredFieldError
from toscaparser.common.exception import UnknownFieldError
from toscaparser.common.exception import ValidationError
from toscaparser.common.exception import TypeMismatchError
from toscaparser.elements.grouptype import GroupType
from toscaparser.elements.interfaces import create_interfaces
from toscaparser.elements.nodetype import NodeType
from toscaparser.elements.policytype import PolicyType
from toscaparser.elements.relationshiptype import RelationshipType
from toscaparser.properties import Property
from toscaparser.unsupportedtype import UnsupportedType
from toscaparser.utils.gettextutils import _
from toscaparser.elements.capabilitytype import CapabilityType
from toscaparser.elements.artifacttype import ArtifactTypeDef

class EntityTemplate(object):
    '''Base class for TOSCA templates.'''

    SECTIONS = (DERIVED_FROM, PROPERTIES, REQUIREMENTS,
                INTERFACES, CAPABILITIES, TYPE, DESCRIPTION, DIRECTIVES, INSTANCE_KEYS,
                ATTRIBUTES, ARTIFACTS, NODE_FILTER, COPY, DEPENDENCIES, IMPORTED) = \
               ('derived_from', 'properties', 'requirements', 'interfaces',
                'capabilities', 'type', 'description', 'directives', "instance_keys",
                'attributes', 'artifacts', 'node_filter', 'copy',  'dependencies', 'imported')
    REQUIREMENTS_SECTION = NodeType.REQUIREMENTS_SECTION

    # Special key names, not overridden by subclasses
    SPECIAL_SECTIONS = (METADATA, NAME, TITLE, DESCRIPTION) = ('metadata', 'name', 'title', 'description')

    additionalProperties = False
    _source = None
    _properties_tpl = None

    def __init__(self, name, template, entity_name, custom_def=None):
        self.name = name
        self.entity_tpl = template
        self.custom_def = custom_def
        self._validate_field(self.entity_tpl)
        type = self.entity_tpl.get('type')
        UnsupportedType.validate_type(type)
        if '__typename' not in template and "_original_properties" not in template:
            self._validate_fields(template)
        if entity_name == 'node_type':
            self.type_definition = NodeType(type, custom_def) \
                if type is not None else None
            self._validate_directives(self.entity_tpl)
        if entity_name == 'relationship_type':
            self.type_definition = RelationshipType(type, custom_def)
        if entity_name == 'policy_type':
            if not type:
                msg = (_('Policy definition of "%(pname)s" must have'
                       ' a "type" ''attribute.') % dict(pname=name))
                ExceptionCollector.appendException(
                    ValidationError(message=msg))
            self.type_definition = PolicyType(type, custom_def)
        if entity_name == 'group_type':
            self.type_definition = GroupType(type, custom_def) \
                if type is not None else None
        if entity_name == 'artifact_type':
            self.type_definition = ArtifactTypeDef(type, custom_def) \
                if type is not None else None

        self._properties = None
        self._interfaces = None
        self._requirements = None
        self._capabilities = None
        if not self.type_definition:
            msg = "no type found %s for %s"  % (entity_name, template)
            ExceptionCollector.appendException(ValidationError(message=msg))
            return

        metadata = self.entity_tpl.get('metadata')
        if metadata and 'additionalProperties' in metadata:
            self.additionalProperties = metadata['additionalProperties']
        else:
            metadata = self.type_definition.get_value('metadata', parent=True)
            if metadata and 'additionalProperties' in metadata:
                self.additionalProperties = metadata['additionalProperties']

        self._properties_tpl = self._validate_properties()
        for prop in self.get_properties_objects():
            prop.validate()
        self.type_definition._validate_interfaces(self)

    @property
    def type(self):
        if self.type_definition:
            return self.type_definition.type

    @property
    def parent_type(self):
        if self.type_definition:
            return self.type_definition.parent_type

    @property
    def types(self):
        if not self.type_definition:
            return []
        types = {self.type_definition.type : self.type_definition}
        for p in self.type_definition.parent_types():
            if p.type not in types:
                types[p.type] = p
        return list(types.values())

    @property
    def directives(self):
        return self.entity_tpl.get('directives', [])

    @property
    def requirements(self):
        if self._requirements is None:
            # alternative syntax for requirements, take precedence
            dependencies = self.entity_tpl.get(self.DEPENDENCIES)
            if dependencies:
                self._requirements = [
                  { dep['name'] : dict(node = dep.get('match'), metadata = dep) } for dep in dependencies
                ]
            else:
                self._requirements = self.entity_tpl.get(self.REQUIREMENTS) or []
        return self._requirements

    def get_properties_objects(self):
        '''Return properties objects for this template.'''
        if self._properties is None:
            self._properties = self._create_properties()
        return self._properties

    def get_properties(self):
        '''Return a dictionary of property name-object pairs.'''
        return {prop.name: prop
                for prop in self.get_properties_objects()}

    def get_property_value(self, name):
        '''Return the value of a given property name.'''
        props = self.get_properties()
        if props and name in props.keys():
            return props[name].value

    @property
    def interfaces(self):
        if self._interfaces is None:
            self._interfaces = self._create_interfaces(self.type_definition, self)
        return self._interfaces

    def get_capabilities_objects(self):
        '''Return capabilities objects for this template.'''
        if self._capabilities is None:
            self._capabilities = self._create_capabilities()
        return self._capabilities

    def get_capabilities(self):
        '''Return a dictionary of capability name-object pairs.'''
        return {cap.name: cap
                for cap in self.get_capabilities_objects()}

    def is_derived_from(self, type_str):
        '''Check if object inherits from the given type.

        Returns true if this object is derived from 'type_str'.
        False otherwise.
        '''
        if not self.type:
            return False
        elif self.type == type_str:
            return True
        return self.type_definition.is_derived_from(type_str)

    def instance_of(self, type_definition):
        return self.is_derived_from(type_definition.global_name)
  
    def _create_capability(self, capabilitydefs, name, ctype, props):
        c = capabilitydefs.get(name)
        if ctype and (not c or ctype != c.type):
            c = CapabilityType(name, ctype, self.type_definition.type,
                                    self.type_definition.custom_def)
        properties = {}
        # first use the definition default value
        for prop_def in c.get_properties_def_objects():
            if 'default' in prop_def.schema:
                properties[prop_def.name] = prop_def.schema['default']
        # then update (if available) with the node properties
        if props:
            properties.update(props)

        return Capability(name, properties, c, self.custom_def)

    def _create_capabilities_from_properties(self, capabilities):
        capabilitydefs = self.type_definition.get_capabilities_def()
        for name, capdef in capabilitydefs.items():
            if name in self._properties_tpl:
                cap = self._create_capability(capabilitydefs, name,
                      capdef.ctype, self._properties_tpl[name])
                capabilities.append(cap)

    def _create_capabilities(self):
        capabilities = []
        if not self.type_definition:
            return capabilities
        caps = self.type_definition.get_value(self.CAPABILITIES,
                                              self.entity_tpl, parent=True)
        if caps:
            for name, props in caps.items():
                if props is None:
                    continue
                capabilitydefs = self.type_definition.get_capabilities_def()
                if name in capabilitydefs:
                    cap = self._create_capability(capabilitydefs, name,
                              props.get('type'), props.get('properties'))
                    capabilities.append(cap)
        self._create_capabilities_from_properties(capabilities)
        return capabilities

    def _validate_directives(self, template):
        msg = (_('directives of "%s" must be a list of strings') % self.name)
        keys = template.get("directives", [])
        if not isinstance(keys, list):
            ExceptionCollector.appendException(
                ValidationError(message=msg))
            return
        for key in keys:
            if not isinstance(key, str):
                ExceptionCollector.appendException(
                    ValidationError(message=msg))

    def _validate_properties(self):
        properties = self.type_definition.get_value(self.PROPERTIES, self.entity_tpl)
        if isinstance(properties, list):
            src = self.entity_tpl
            src['_original_properties'] = properties
            cls = getattr(src, "mapCtor", src.__class__)
            properties = cls( (p["name"], p.get('value')) for p in properties )
            src['properties'] = properties
        if not properties:
            properties = {}
        if not isinstance(properties, dict):
            ExceptionCollector.appendException(
              TypeMismatchError(
                  what='"properties" of template "%s"' % self.name,
                  type='dict'))
            return {}
        if self._should_validate_properties():
            # this is just a placeholder template for the imported one so it might not have properties
            self._common_validate_properties(self.type_definition, properties, self.additionalProperties)
        return properties

    def _should_validate_properties(self):
        return not self.entity_tpl.get(self.IMPORTED)

    def revalidate_properties(self):
        self._common_validate_properties(self.type_definition, self.get_properties(), self.additionalProperties)

    def _validate_capabilities(self):
        type_capabilities = self.type_definition.get_capabilities_def()
        allowed_caps = \
            type_capabilities.keys() if type_capabilities else []
        capabilities = self.type_definition.get_value(self.CAPABILITIES,
                                                      self.entity_tpl)
        if capabilities:
            self._common_validate_field(capabilities, allowed_caps,
                                        'capabilities')
            self._validate_capabilities_properties(capabilities)

    def _validate_capabilities_properties(self, capabilities):
        for cap, props in capabilities.items():
            capability = self.get_capability(cap)
            if not capability:
                continue
            capabilitydef = capability.type_definition
            self._common_validate_properties(capabilitydef,
                                             props.get(self.PROPERTIES) or {})

            # validating capability properties values
            for prop in self.get_capability(cap).get_properties_objects():
                prop.validate()

                # TODO(srinivas_tadepalli): temporary work around to validate
                # default_instances until standardized in specification
                if cap == "scalable" and prop.name == "default_instances":
                    prop_dict = props[self.PROPERTIES]
                    min_instances = prop_dict.get("min_instances")
                    max_instances = prop_dict.get("max_instances")
                    default_instances = prop_dict.get("default_instances")
                    if not (min_instances <= default_instances
                            <= max_instances):
                        err_msg = ('"properties" of template "%s": '
                                   '"default_instances" value is not between '
                                   '"min_instances" and "max_instances".' %
                                   self.name)
                        ExceptionCollector.appendException(
                            ValidationError(message=err_msg))

    def _common_validate_properties(self, entitytype, properties, allowUndefined=False):
        allowed_props = []
        required_props = []
        for p in entitytype.get_properties_def_objects():
            allowed_props.append(p.name)
            # If property is 'required' and no default was declared
            if p.required and "default" not in p.schema:
                required_props.append(p.name)
        # validate all required properties have values
        if properties:
            req_props_no_value_or_default = []
            if not allowUndefined:
              self._common_validate_field(properties, allowed_props,
                                          'properties')
            # make sure it's not missing any property required by a tosca type
            for r in required_props:
                if r not in properties.keys():
                    req_props_no_value_or_default.append(r)
            # Required properties found without value or a default value
            if req_props_no_value_or_default:
                ExceptionCollector.appendException(
                    MissingRequiredFieldError(
                        what='"properties" of template "%s"' % self.name,
                        required=req_props_no_value_or_default))
        else:
            # Required properties in schema, but not in template
            if required_props:
                ExceptionCollector.appendException(
                    MissingRequiredFieldError(
                        what='"properties" of template "%s"' % self.name,
                        required=required_props))

    def _validate_field(self, template):
        if not isinstance(template, dict):
            ExceptionCollector.appendException(
                MissingRequiredFieldError(
                    what='Template "%s"' % self.name, required=self.TYPE))
        try:
            template[self.TYPE]
        except KeyError:
            ExceptionCollector.appendException(
                MissingRequiredFieldError(
                    what='Template "%s"' % self.name, required=self.TYPE))

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
                            what=('"%(section)s" of template "%(nodename)s"'
                                  % {'section': section, 'nodename': self.name}),
                            field=name))

    def _validate_fields(self, template):
        for name in template.keys():
            if name not in self.SECTIONS and name not in self.SPECIAL_SECTIONS:
                ExceptionCollector.appendException(
                    UnknownFieldError(what='template "%s"' % self.name,
                                      field=name))

    def _create_properties(self):
        props = []
        properties = self._properties_tpl or {}
        props_def = self.type_definition.get_properties_def()
        if isinstance(self.type_definition, NodeType):
            capabilitydefs = self.type_definition.get_capabilities_def()
        else:
            capabilitydefs = {}
        custom_def = self.type_definition.custom_def if self.type_definition else self.custom_def
        for name, value in properties.items():
            if name in capabilitydefs:
                continue
            if props_def and name in props_def:
                prop = Property(name, value,
                                props_def[name].schema, custom_def)
                props.append(prop)
            elif self.additionalProperties:
                prop = Property(name, value,
                                dict(type='any', required=False), custom_def)
                props.append(prop)
        for p in props_def.values():
            if "default" in p.schema and p.name not in properties:
                prop = Property(p.name, p.default, p.schema, custom_def)
                props.append(prop)
        return props

    @staticmethod
    def _create_interfaces(type_definition, template):
        return create_interfaces(type_definition, template)

    def get_interface_requirements(self):
        return self.type_definition.get_interface_requirements(self.entity_tpl)

    def get_capability(self, name):
        """Provide named capability

        :param name: name of capability
        :return: capability object if found, None otherwise
        """
        return self.get_capabilities().get(name)

    def __repr__(self):
        return f"{self.__class__}({self.name})"

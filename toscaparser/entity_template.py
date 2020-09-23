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
from toscaparser.elements.grouptype import GroupType
from toscaparser.elements.interfaces import InterfacesDef, INTERFACE_DEF_RESERVED_WORDS
from toscaparser.elements.interfaces import CONFIGURE, CONFIGURE_SHORTNAME
from toscaparser.elements.interfaces import LIFECYCLE,  LIFECYCLE_SHORTNAME
from toscaparser.elements.nodetype import NodeType
from toscaparser.elements.policytype import PolicyType
from toscaparser.elements.relationshiptype import RelationshipType
from toscaparser.properties import Property
from toscaparser.unsupportedtype import UnsupportedType
from toscaparser.utils.gettextutils import _
from toscaparser.elements.capabilitytype import CapabilityTypeDef
from toscaparser.elements.artifacttype import ArtifactTypeDef

class EntityTemplate(object):
    '''Base class for TOSCA templates.'''

    SECTIONS = (DERIVED_FROM, PROPERTIES, REQUIREMENTS,
                INTERFACES, CAPABILITIES, TYPE, DESCRIPTION, DIRECTIVES, INSTANCE_KEYS,
                ATTRIBUTES, ARTIFACTS, NODE_FILTER, COPY) = \
               ('derived_from', 'properties', 'requirements', 'interfaces',
                'capabilities', 'type', 'description', 'directives', "instance_keys",
                'attributes', 'artifacts', 'node_filter', 'copy')
    REQUIREMENTS_SECTION = (NODE, CAPABILITY, RELATIONSHIP, OCCURRENCES, NODE_FILTER) = \
                           ('node', 'capability', 'relationship',
                            'occurrences', 'node_filter')
    # Special key names
    SPECIAL_SECTIONS = (METADATA) = ('metadata')

    additionalProperties = True
    _source = None

    def __init__(self, name, template, entity_name, custom_def=None):
        self.name = name
        self.entity_tpl = template
        self.custom_def = custom_def
        self._validate_field(self.entity_tpl)
        type = self.entity_tpl.get('type')
        UnsupportedType.validate_type(type)
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
        metadata = self.type_definition.get_definition('metadata')
        if metadata and 'additionalProperties' in metadata:
            self.additionalProperties = metadata['additionalProperties']

        self._validate_properties()
        for prop in self.get_properties_objects():
            prop.validate()
        self._validate_interfaces()

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
        types = []
        p = self.type_definition
        while p:
            types.append(p)
            p = p.parent_type
        return types

    @property
    def directives(self):
        return self.entity_tpl.get('directives', [])

    @property
    def requirements(self):
        if self._requirements is None:
            self._requirements = self.type_definition.get_value(
                self.REQUIREMENTS,
                self.entity_tpl) or []
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
            self._interfaces = self._create_interfaces()
        return self._interfaces

    def get_capabilities_objects(self):
        '''Return capabilities objects for this template.'''
        if not self._capabilities:
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
        elif self.parent_type:
            return self.parent_type.is_derived_from(type_str)
        else:
            return False

    def _create_capabilities(self):
        capability = []
        caps = self.type_definition.get_value(self.CAPABILITIES,
                                              self.entity_tpl, parent=True)
        if caps:
            for name, props in caps.items():
                ctype = props.get('type')
                capabilities = self.type_definition.get_capabilities()
                if name in capabilities.keys():
                    c = capabilities[name]
                    ctype = props.get('type')
                    if ctype and ctype != c.type:
                        c = CapabilityTypeDef(name, ctype, self.type_definition.type,
                                                self.type_definition.custom_def)
                    properties = {}
                    # first use the definition default value
                    if c.properties:
                        for property_name in c.properties.keys():
                            prop_def = c.properties[property_name]
                            if 'default' in prop_def:
                                properties[property_name] = prop_def['default']
                    # then update (if available) with the node properties
                    if 'properties' in props and props['properties']:
                        properties.update(props['properties'])

                    cap = Capability(name, properties, c, self.custom_def)
                    capability.append(cap)
        return capability

    def _validate_directives(self, template):
        msg = (_('directives of "%s" must be a list of strings') % self.name)
        keys = template.get("directives", [])
        if not isinstance(keys, list):
            ExceptionCollector.appendException(
                ValidationError(message=msg))
        for key in keys:
            if not isinstance(key, str):
                ExceptionCollector.appendException(
                    ValidationError(message=msg))

    def _validate_properties(self):
        properties = self.type_definition.get_value(self.PROPERTIES, self.entity_tpl)
        self._common_validate_properties(self.type_definition, properties, self.additionalProperties)

    def _validate_capabilities(self):
        type_capabilities = self.type_definition.get_capabilities()
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
            # If property is 'required' and has no 'default' value then record
            if p.required and p.default is None:
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
        properties = self.type_definition.get_value(self.PROPERTIES,
                                                    self.entity_tpl) or {}
        props_def = self.type_definition.get_properties_def()
        for name, value in properties.items():
            if props_def and name in props_def:
                prop = Property(name, value,
                                props_def[name].schema, self.custom_def)
                props.append(prop)
            elif self.additionalProperties:
                prop = Property(name, value,
                          dict(type='any'), self.custom_def)
                props.append(prop)
        for p in props_def.values():
            if p.default is not None and p.name not in properties:
                prop = Property(p.name, p.default, p.schema, self.custom_def)
                props.append(prop)
        return props

    def _create_interfaces(self):
        interfaces = []
        tpl_interfaces = self.type_definition.get_value(self.INTERFACES,
                                                         self.entity_tpl)

        if self.type_definition.interfaces:
            interfacesDefs = self.type_definition.interfaces.copy()
            if tpl_interfaces:
                # merge the interfaces defined on the type with the template's interface definitions
                for iName, defs in tpl_interfaces.items():
                    # for each interface, see if base defines it too
                    defs = defs.copy()
                    inputs = defs.get('inputs', {})
                    if 'operations' in defs:
                        defs = defs.get('operations', {})
                    baseDefs = interfacesDefs.get(iName)
                    if baseDefs:
                        # add in base's ops and merge interface-level inputs
                        baseInputs = baseDefs.get('inputs')
                        if baseInputs: # merge shared inputs
                            inputs = dict(baseInputs, **inputs)
                            defs['inputs'] = inputs

                        implementation = baseDefs.get('implementation')
                        # set shared implementation
                        if implementation and 'implementation' not in defs:
                            defs['implementation'] = implementation
                            if isinstance(implementation, dict) and self.type_definition._source:
                                # if implementation might be an inline artifact, save the baseDir of the source
                                implementation['_source'] = self.type_definition._source

                        if 'operations' in baseDefs:
                            baseDefs = baseDefs.get('operations') or {}

                        for op, baseDef in baseDefs.items():
                            if op in ['inputs', 'notifications', '_source']:
                                continue
                            if op in defs:
                                # op in both, merge
                                currentiDef = defs[op]
                                if isinstance(baseDef, dict):
                                    if not isinstance(currentiDef, dict):
                                        currentiDef = dict(implementation = currentiDef)
                                    if isinstance(baseDef.get('implementation'), dict) and self.type_definition._source:
                                        # if implementation might be an inline artifact, save the baseDir of the source
                                        baseDef['implementation']['_source'] = self.type_definition._source
                                    defs[op] = dict(baseDef, **currentiDef)
                                    if 'inputs' in baseDef and 'inputs' in currentiDef:
                                        # merge inputs
                                        defs[op]['inputs'] = dict(baseDef['inputs'], **currentiDef['inputs'])
                            else:
                                defs[op] = baseDef

                    # add or replace:
                    interfacesDefs[iName] = defs
        else:
            interfacesDefs = tpl_interfaces
            if not interfacesDefs:
              return []

        defaults = interfacesDefs.pop('defaults', {})
        for interface_type, value in interfacesDefs.items():
            # shared inputs
            inputs = value.get('inputs')
            defaultInputs = defaults.get('inputs')
            if inputs and defaultInputs: # merge shared inputs
                inputs = dict(defaultInputs, **inputs)
            else:
                inputs = inputs or defaultInputs

            # shared outputs
            outputs = value.get('outputs')
            defaultOutputs = defaults.get('outputs')
            if outputs and defaultOutputs: # merge shared inputs
                outputs = dict(defaultOutputs, **outputs)
            else:
                outputs = outputs or defaultOutputs

            # shared implementation
            implementation = value.get('implementation') or defaults.get('implementation')
            _source = value.pop('_source', None)
            if 'operations' in value:
                defs = value.get('operations') or {}
            else:
                defs = value

            for op, op_def in defs.items():
                if op in INTERFACE_DEF_RESERVED_WORDS:
                    continue
                if not isinstance(op_def, dict):
                    op_def = dict(implementation = op_def or implementation)
                elif implementation and not op_def.get('implementation'):
                    op_def['implementation'] = implementation
                if _source:
                    op_def['_source'] = _source
                iface = InterfacesDef(self.type_definition,
                                      interfacetype=interface_type,
                                      node_template=self,
                                      name=op,
                                      value=op_def,
                                      inputs=inputs.copy() if inputs else None,
                                      outputs=outputs.copy() if outputs else None)
                interfaces.append(iface)

            # add a "default" operation that has the shared inputs and implementation
            iface = InterfacesDef(self.type_definition,
                                  interfacetype=interface_type,
                                  node_template=self,
                                  name='default',
                                  value=dict(implementation=implementation,
                                              _source=_source),
                                  inputs=inputs, outputs=outputs)
            interfaces.append(iface)
        return interfaces

    def _validate_interfaces(self):
        ifaces = self.type_definition.get_value(self.INTERFACES,
                                                self.entity_tpl)
        if ifaces:
            for name, value in ifaces.items():
                if name == 'defaults':
                  self._common_validate_field(
                      value,
                      ['implementation', 'inputs', 'outputs'],
                      'interfaces')
                elif name in (LIFECYCLE, LIFECYCLE_SHORTNAME):
                    self._common_validate_field(
                        value, INTERFACE_DEF_RESERVED_WORDS + InterfacesDef.
                        interfaces_node_lifecycle_operations,
                        'interfaces')
                elif name in (CONFIGURE, CONFIGURE_SHORTNAME):
                    self._common_validate_field(
                        value, INTERFACE_DEF_RESERVED_WORDS + InterfacesDef.
                        interfaces_relationship_configure_operations,
                        'interfaces')
                elif (name in self.type_definition.interfaces
                      or name in self.type_definition.TOSCA_DEF):
                      self._common_validate_field(
                          value,
                          INTERFACE_DEF_RESERVED_WORDS + self._collect_custom_iface_operations(name),
                          'interfaces')
                else:
                    ExceptionCollector.appendException(
                        UnknownFieldError(
                            what='"interfaces" of template "%s"' %
                            self.name, field=name))

    def _collect_custom_iface_operations(self, name):
        allowed_operations = []
        nodetype_iface_def = self.type_definition.interfaces.get(
                              name, self.type_definition.TOSCA_DEF.get(name))
        allowed_operations.extend(nodetype_iface_def.keys())
        if 'type' in nodetype_iface_def:
            iface_type = nodetype_iface_def['type']
            if iface_type in self.type_definition.custom_def:
                iface_type_def = self.type_definition.custom_def[iface_type]
            else:
                iface_type_def = self.type_definition.TOSCA_DEF[iface_type]
            allowed_operations.extend(iface_type_def.keys())
        allowed_operations = [op for op in allowed_operations if
                              op not in INTERFACE_DEF_RESERVED_WORDS]
        return allowed_operations

    def get_capability(self, name):
        """Provide named capability

        :param name: name of capability
        :return: capability object if found, None otherwise
        """
        caps = self.get_capabilities()
        if caps and name in caps.keys():
            return caps[name]

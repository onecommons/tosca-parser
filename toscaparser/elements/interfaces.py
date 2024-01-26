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

import os
from toscaparser.common.exception import ExceptionCollector
from toscaparser.common.exception import UnknownFieldError
from toscaparser.common.exception import MissingRequiredFieldError
from toscaparser.common.exception import ValidationError
from toscaparser.elements.entity_type import EntityType

SECTIONS = (
    LIFECYCLE,
    CONFIGURE,
    INSTALL,
    LIFECYCLE_SHORTNAME,
    CONFIGURE_SHORTNAME,
    INSTALL_SHORTNAME,
    MOCK,
) = (
    "tosca.interfaces.node.lifecycle.Standard",
    "tosca.interfaces.relationship.Configure",
    "unfurl.interfaces.Install",
    "Standard",
    "Configure",
    "Install",
    "Mock",
)

OPERATION_DEF_RESERVED_WORDS = (
    DESCRIPTION,
    IMPLEMENTATION,
    INPUTS,
    OUTPUTS,
    ENTRY_STATE,
    EXIT_STATE,
) = (
    "description",
    "implementation",
    "inputs",
    "outputs",
    "entry_state",
    "exit_state",
)

INTERFACE_DEF_RESERVED_WORDS = [
    "type",
    "inputs",
    "operations",
    "notifications",
    "description",
    "implementation",
    "requirements",
    "derived_from",
    "metadata",
]

IMPLEMENTATION_DEF_RESERVED_WORDS = (
    PRIMARY,
    DEPENDENCIES,
    TIMEOUT,
    CLASSNAME,
    OPERATION_HOST,
    ENVIRONMENT,
    PRECONDITIONS,
    _SOURCE,
    INVOKE,
) = (
    "primary",
    "dependencies",
    "timeout",
    "className",
    "operation_host",
    "environment",
    "preConditions",
    "_source",
    "invoke",
)

INLINE_ARTIFACT_DEF_RESERVED_WORDS = ("description", "file", "repository", "_source")


class OperationDef:
    """TOSCA built-in interfaces type."""

    def __init__(
        self,
        type_definition,
        interfacename,
        node_template=None,
        name=None,
        value=None,
        inputs=None,
        outputs=None,
    ):
        self.ntype = type_definition
        self.node_template = node_template
        self.interfacename = interfacename
        self.name = name
        self.value = value
        self.implementation = None
        self.invoke = None
        if inputs:
            cls = getattr(inputs, "mapCtor", inputs.__class__)
            inputs = cls(inputs)
        self.inputs = inputs
        self._source = None
        if outputs:
            cls = getattr(outputs, "mapCtor", outputs.__class__)
            outputs = cls(outputs)
        self.outputs = outputs
        self.entry_state = None
        interfaces = getattr(self.ntype, "interfaces", None)
        self.interfacetype = None
        if interfaces and "type" in interfaces.get(interfacename, {}):
            self.interfacetype = interfaces[interfacename]["type"]
        elif interfacename == LIFECYCLE_SHORTNAME:
            self.interfacetype = LIFECYCLE
        elif interfacename == CONFIGURE_SHORTNAME:
            self.interfacetype = CONFIGURE
        elif interfacename == INSTALL_SHORTNAME:
            self.interfacetype = INSTALL
        elif interfacename == MOCK:
            self.interfacetype = MOCK
        if not self.interfacetype:
            if interfaces:
                ExceptionCollector.appendException(
                    TypeError(
                        'Interface type for interface "{0}" not found'.format(
                            self.interfacename
                        )
                    )
                )
            else:
                # not calling for a type with an "interfaces" definition -- assume its name is the type
                self.interfacetype = interfacename
        self.type = self.interfacetype
        if value:
            if isinstance(self.value, dict):
                for i, j in self.value.items():
                    if i == "_source":
                        self._source = j
                    elif i == IMPLEMENTATION:
                        self.implementation = j
                    elif i == ENTRY_STATE:
                        self.entry_state = j
                    elif i == INPUTS:
                        if self.inputs:
                            self.inputs.update(j)
                        else:
                            self.inputs = j
                    elif i == OUTPUTS:
                        if self.outputs:
                            self.outputs.update(j)
                        else:
                            self.outputs = j
                    elif i == INVOKE:
                        self.invoke = j
                    elif i not in OPERATION_DEF_RESERVED_WORDS:
                        ExceptionCollector.appendException(
                            UnknownFieldError(what=self._msg, field=i)
                        )
            else:
                self.implementation = value
            self.validate_implementation()
        if not self._source and self.ntype:
            _source = self.ntype.defs.get("_source")
            if isinstance(_source, dict):
                self._source = os.path.dirname(_source.get("path", ""))
            else:
                self._source = _source

    @property
    def _msg(self):
        if self.node_template:
            return 'operation "%s:%s" on template "%s"' % (
                self.interfacename,
                self.name,
                self.node_template.name,
            )
        else:
            return 'operation "%s:%s" on type "%s"' % (
                self.interfacename,
                self.name,
                self.ntype.type,
            )

    def validate_implementation(self):
        if isinstance(self.implementation, dict):
            for key, value in self.implementation.items():
                if key == PRIMARY:
                    self.validate_inline_artifact(value)
                elif key == DEPENDENCIES:
                    if not isinstance(value, list):
                        ExceptionCollector.appendException(
                            ValidationError(message=self._msg + ": 'dependencies' must be a list")
                        )
                    else:
                        for artifact in value:
                            self.validate_inline_artifact(artifact)
                elif key not in IMPLEMENTATION_DEF_RESERVED_WORDS:
                    ExceptionCollector.appendException(
                        UnknownFieldError(
                            what="implementation in " + self._msg, field=key
                        )
                    )

    def validate_inline_artifact(self, inline_artifact):
        if isinstance(inline_artifact, dict):
            if "file" not in inline_artifact:
                ExceptionCollector.appendException(
                    MissingRequiredFieldError(
                        what="inline artifact in " + self._msg, required="file"
                    )
                )
            for key in inline_artifact:
                if key not in INLINE_ARTIFACT_DEF_RESERVED_WORDS:
                    what = (
                        "inline artifact in "
                        + self._msg
                        + " contains invalid field "
                        + key
                    )
                    ExceptionCollector.appendException(ValidationError(message=what))


def create_interfaces(type_definition, template):
    entity_tpl = template.entity_tpl if template else None
    interfacesDefs = _create_interfacedefs(type_definition, entity_tpl)
    if not interfacesDefs:
        return []
    return _create_operations(interfacesDefs, type_definition, template)


def _create_interfacedefs(type_definition, entity_tpl=None):
    # get a copy of the interfaces directy defined on the entity template
    tpl_interfaces = type_definition.get_value("interfaces", entity_tpl)
    if type_definition.interfaces:
        interfacesDefs = type_definition.interfaces
        if tpl_interfaces:
            return merge_interfacedefs(interfacesDefs, tpl_interfaces, type_definition._source)
        return interfacesDefs
    else:
        return tpl_interfaces


def _merge_operations(baseDefs, operations, _source, cls):
    if 'operations' in baseDefs:
        baseOps = baseDefs['operations'] or cls()
    else:
        baseOps = cls({k: v for k, v in baseDefs.items() if k not in INTERFACE_DEF_RESERVED_WORDS})

    for op, baseDef in baseOps.items():
        if op in operations:
            # op in both, merge operations
            currentiDef = operations[op]
            if isinstance(baseDef, dict):
                if not isinstance(currentiDef, dict):
                    currentiDef = cls(implementation=currentiDef)
                if isinstance(baseDef.get('implementation'), dict) and _source:
                    # if implementation might be an inline artifact, save the baseDir of the source
                    baseDef['implementation']['_source'] = _source
                cls2 = getattr(currentiDef, "mapCtor", currentiDef.__class__)
                operations[op] = cls2(baseDef, **currentiDef)
                if 'inputs' in baseDef and 'inputs' in currentiDef:
                    # merge inputs
                    operations[op]['inputs'] = cls2(baseDef['inputs'], **currentiDef['inputs'])
        else:
            operations[op] = baseDef


def merge_interfacedefs(base, derived, _source):
    # merge the interfaces defined on the type with the template's interface definitions
    for iName, defs in derived.items():
        if not isinstance(defs, dict):
            continue
        # for each interface, see if base defines it too
        cls = getattr(defs, "mapCtor", defs.__class__)
        defs = cls(defs)
        inputs = defs.get('inputs') or cls()
        if 'operations' in defs:
            operations = defs['operations'] or cls()
        else:
            operations = defs

        baseDefs = base.get(iName)
        if baseDefs:
            # add in base's ops and merge interface-level inputs
            baseInputs = baseDefs.get('inputs')
            if baseInputs:  # merge shared inputs
                inputs = cls(baseInputs, **inputs)
                defs['inputs'] = inputs

            # set shared implementation
            implementation = baseDefs.get('implementation')
            if implementation and 'implementation' not in defs:
                defs['implementation'] = implementation
                if isinstance(implementation, dict) and _source:
                    # if implementation might be an inline artifact, save the baseDir of the source
                    implementation['_source'] = _source

            _merge_operations(baseDefs, operations, _source, cls)

            for key in ["type", "requirements", "description"]:
                if key in baseDefs and key not in defs:
                    defs[key] = baseDefs[key]

        # add or replace the interface with derived
        base[iName] = defs

    return base


def _create_operations(interfacesDefs, type_definition, template):
    interfaces = []
    cls = getattr(interfacesDefs, "mapCtor", interfacesDefs.__class__)
    defaults = interfacesDefs.pop('defaults', cls())
    for interface_name, value in interfacesDefs.items():
        cls = getattr(value, "mapCtor", value.__class__)
        # merge in shared:
        # shared inputs
        inputs = value.get('inputs')
        defaultInputs = defaults.get('inputs')
        if inputs and defaultInputs:  # merge shared inputs
            inputs = cls(defaultInputs, **inputs)
        else:
            inputs = inputs or defaultInputs

        # shared outputs
        outputs = value.get('outputs')
        defaultOutputs = defaults.get('outputs')
        if outputs and defaultOutputs: # merge shared inputs
            outputs = cls(defaultOutputs, **outputs)
        else:
            outputs = outputs or defaultOutputs

        # shared implementation
        implementation = value.get('implementation') or defaults.get('implementation')

        # create an OperationDef for each operation
        _source = value.pop('_source', None)
        if 'operations' in value:
            defs = value.get('operations') or cls()
        else:
            defs = value

        for op in list(defs):
            if op in INTERFACE_DEF_RESERVED_WORDS:
                continue
            op_def = defs[op]
            if not isinstance(op_def, dict):
                if op_def == "not_implemented":
                    continue
                # if empty, copy the shared implementation
                op_def = cls(implementation=op_def or implementation)
            elif implementation and not op_def.get('implementation'):
                op_def['implementation'] = implementation
            if _source:
                op_def['_source'] = _source
            iface = OperationDef(type_definition,
                                 interface_name,
                                 node_template=template,
                                 name=op,
                                 value=op_def,
                                 inputs=inputs,
                                 outputs=outputs)
            interfaces.append(iface)

        # add a "default" operation that has the shared inputs and implementation
        if inputs or implementation:
            iface = OperationDef(type_definition,
                                 interface_name,
                                 node_template=template,
                                 name='default',
                                 value=cls(implementation=implementation,
                                            _source=_source),
                                 inputs=inputs, outputs=outputs)
            interfaces.append(iface)
    return interfaces

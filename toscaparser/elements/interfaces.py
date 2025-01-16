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
    METADATA,
) = (
    "description",
    "implementation",
    "inputs",
    "outputs",
    "entry_state",
    "exit_state",
    "metadata",
)

INTERFACE_DEF_RESERVED_WORDS = [
    "type",
    "inputs",
    "outputs",
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


def _split_inputs(inputs, msg):
    if not isinstance(inputs, dict):
        ExceptionCollector.appendException(
            ValidationError(message=msg + ": inputs must be a map")
        )
        return {}, {}
    else:
        cls = getattr(inputs, "mapCtor", inputs.__class__)
        vals = cls()
        defs = cls()
        _set_vals(inputs, vals, defs)
        return vals, defs


def _set_vals(inputs, vals, defs):
    for name, val in inputs.items():
        if isinstance(val, dict) and "type" in val:
            defs[name] = val
            if "default" in val:
                vals[name] = val["default"]
            if "mapping" in val:
                vals[name] = val["mapping"]
        else:
            vals[name] = val


def _merge_outputs(old, new):
    merged = old.copy()
    if not new:
        return merged
    for key, value in new.items():
        if key in merged:
            old_value = merged[key]
            if isinstance(old_value, dict) and not isinstance(value, dict):
                merged[key] = dict(old_value, mapping=value)
            elif not isinstance(old_value, dict) and isinstance(value, dict):
                merged[key] = dict(value, mapping=old_value)
            else:
                merged[key] = value
        else:
            merged[key] = value
    return merged


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
        input_defs=None,
        metadata=None,
    ):
        self.ntype = type_definition
        self.node_template = node_template
        if node_template and node_template.custom_def:
            self.custom_def = node_template.custom_def
        else:
            self.custom_def = self.ntype.custom_def
        self.interfacename = interfacename
        self.name = name
        self.value = value
        self.metadata = metadata
        self.implementation = None
        self.invoke = None
        self.input_defs = input_defs
        self._input_props = None
        self._output_props = None
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
                            self.outputs = _merge_outputs(self.outputs, j)
                        else:
                            self.outputs = j
                    elif i == INVOKE:
                        self.invoke = j
                    elif i == "_input_defs":
                        if self.input_defs:
                            self.input_defs.update(j)
                        else:
                            self.input_defs = j
                    elif i == METADATA:
                        if self.metadata:
                            self.metadata.update(j)
                        else:
                            self.metadata = j
                    elif i not in OPERATION_DEF_RESERVED_WORDS:
                        ExceptionCollector.appendException(
                            UnknownFieldError(what=self._msg, field=i)
                        )
            else:
                self.implementation = value
            self.primary = self.validate_implementation()
        else:
            self.primary = None
        if not self._source and self.ntype:
            _source = self.ntype.defs.get("_source")
            if isinstance(_source, dict):
                self._source = os.path.dirname(_source.get("path", ""))
            else:
                self._source = _source

    def get_declared_inputs(self):
        from toscaparser.properties import Property

        if self._input_props is None:
            if not self.input_defs:
                self._input_props = {}
            else:
                inputs = self.inputs or {}
                self._input_props = {
                    name: Property(name, inputs.get(name), schema, self.custom_def)
                    for name, schema in self.input_defs.items()
                }
        return self._input_props

    def get_declared_outputs(self):
        from toscaparser.properties import Property

        if self._output_props is None:
            if not self.outputs:
                self._output_props = {}
            else:
                self._output_props = {}
                for name, schema in self.outputs.items():
                    if isinstance(schema, dict):  # skip if output is just a mapping
                        self._output_props[name] = Property(
                            name, None, schema, self.custom_def
                        )
        return self._output_props

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
        primary = None
        if isinstance(self.implementation, dict):
            for key, value in self.implementation.items():
                if key == PRIMARY:
                    primary = self.validate_inline_artifact(value)
                elif key == DEPENDENCIES:
                    if not isinstance(value, list):
                        ExceptionCollector.appendException(
                            ValidationError(
                                message=self._msg + ": 'dependencies' must be a list"
                            )
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
        return primary

    def validate_inline_artifact(self, inline_artifact):
        from toscaparser.artifacts import Artifact

        if isinstance(inline_artifact, dict):
            if "file" not in inline_artifact:
                ExceptionCollector.appendException(
                    MissingRequiredFieldError(
                        what="inline artifact in " + self._msg, required="file"
                    )
                )
            if "type" in inline_artifact:
                # only create an artifact object if a type was declared
                # generate name from operation name
                name = f"__primary_{self.interfacename}_{self.name}"
                return Artifact(name, inline_artifact, self.custom_def)
            for key in inline_artifact:
                if key not in INLINE_ARTIFACT_DEF_RESERVED_WORDS:
                    what = (
                        "inline artifact in "
                        + self._msg
                        + " contains invalid field "
                        + key
                    )
                    ExceptionCollector.appendException(ValidationError(message=what))
        return None


def create_interfaces(type_definition, template):
    if template:
        on = f" on {template.name}"
    elif type_definition:
        on = f" on {type_definition.type}"
    else:
        on = ""
    entity_tpl = template.entity_tpl if template else None
    interfacesDefs = _create_interfacedefs(type_definition, entity_tpl, on)
    if not interfacesDefs:
        return []
    # inputs will only be assignments, input definitions on types will have been moved to _input_defs
    return _create_operations(interfacesDefs, type_definition, template)


def _create_interfacedefs(type_definition, entity_tpl, msg):
    # get a copy of the interfaces directy defined on the entity template
    tpl_interfaces = type_definition.get_value("interfaces", entity_tpl)
    if type_definition.interfaces:
        interfacesDefs = type_definition.interfaces
        if tpl_interfaces:
            return merge_interfacedefs(
                interfacesDefs, tpl_interfaces, type_definition._source, msg
            )
        return interfacesDefs
    else:
        return tpl_interfaces


def _merge_operations(baseDefs, operations, _source, cls, msg):
    if "operations" in baseDefs:
        baseOps = baseDefs["operations"] or cls()
    else:
        baseOps = cls({
            k: v for k, v in baseDefs.items() if k not in INTERFACE_DEF_RESERVED_WORDS
        })

    for op, op_def in operations.items():
        if op not in baseOps and isinstance(op_def, dict):
            inputs = op_def.get("inputs")
            if inputs:
                op_def["inputs"], i_defs = _split_inputs(op_def["inputs"], msg)
                if i_defs:
                    op_def["_input_defs"] = i_defs

    for op, baseDef in baseOps.items():
        if op in operations:
            # op in both, merge baseDefs into operations
            currentiDef = operations[op]
            if isinstance(baseDef, dict):
                if not isinstance(currentiDef, dict):
                    currentiDef = cls(implementation=currentiDef)
                if isinstance(baseDef.get("implementation"), dict) and _source:
                    # if implementation might be an inline artifact, save the baseDir of the source
                    baseDef["implementation"]["_source"] = _source

                if "inputs" in currentiDef:
                    currentiDef["inputs"], i_defs = _split_inputs(
                        currentiDef["inputs"], msg
                    )
                    if i_defs:
                        currentiDef["_input_defs"] = i_defs

                c_cls = getattr(currentiDef, "mapCtor", currentiDef.__class__)
                operations[op] = c_cls(baseDef, **currentiDef)

                _merge_input_defs(operations, op, baseDef, currentiDef, c_cls)
                if "outputs" in baseDef and "outputs" in currentiDef:
                    operations[op]["outputs"] = _merge_outputs(
                        baseDef["outputs"], currentiDef["outputs"]
                    )
                elif "outputs" in baseDef:
                    operations[op]["outputs"] = baseDef["outputs"]
        else:
            operations[op] = baseDef


def _merge_input_defs(operations, op, baseDef, currentiDef, cls2):
    key = "inputs"
    if key in baseDef and key in currentiDef:
        # merge inputs
        operations[op][key] = cls2(baseDef[key], **currentiDef[key])
    key_defs = "_input_defs"
    if key_defs in baseDef and key_defs in currentiDef:
        # merge input defs
        operations[op][key_defs] = cls2(baseDef[key_defs], **currentiDef[key_defs])


def merge_interfacedefs(base, derived, _source, msg, has_defs=True):
    # merge the interfaces defined on the type with the template's interface definitions
    for iName, defs in derived.items():
        if not isinstance(defs, dict):
            continue
        # for each interface, see if base defines it too
        cls = getattr(defs, "mapCtor", defs.__class__)
        defs = cls(defs)
        inputs, i_defs = _split_defs(msg, has_defs, defs, cls)
        outputs = defs.get("outputs")
        if "operations" in defs:
            operations = defs["operations"] or cls()
        else:
            operations = defs

        baseDefs = base.get(iName)
        if baseDefs:
            # add in base's ops and merge interface-level inputs
            _merge_shared_inputs(defs, cls, inputs, i_defs, baseDefs)
            baseOutputs = baseDefs.get("outputs")
            if baseOutputs:  # merge shared outputs
                defs["outputs"] = _merge_outputs(baseOutputs, outputs or {})

            # set shared implementation
            implementation = baseDefs.get("implementation")
            if implementation and "implementation" not in defs:
                defs["implementation"] = implementation
                if isinstance(implementation, dict) and _source:
                    # if implementation might be an inline artifact, save the baseDir of the source
                    implementation["_source"] = _source

            _merge_operations(baseDefs, operations, _source, cls, msg)

            for key in ["type", "requirements", "description"]:
                if key in baseDefs and key not in defs:
                    defs[key] = baseDefs[key]

            metadata = baseDefs.get("metadata")
            if metadata:
                derived_metadata = defs.get("metadata") or {}
                defs["metadata"] = cls(metadata, **derived_metadata)

        # add or replace the interface with derived
        base[iName] = defs

    return base


def _merge_shared_inputs(defs, cls, inputs, i_defs, baseDefs):
    key = "inputs"
    baseInputs = baseDefs.get(key)
    if baseInputs:  # merge shared inputs
        defs[key] = cls(baseInputs, **inputs)
    elif inputs:
        defs[key] = inputs

    key_defs = "_input_defs"
    base_input_defs = baseDefs.get(key_defs)
    if base_input_defs:  # merge shared input defs
        defs[key_defs] = cls(base_input_defs, **i_defs)


def _split_defs(msg, has_defs, defs, cls):
    inputs = defs.get("inputs") or cls()
    if inputs and has_defs:
        inputs, i_defs = _split_inputs(inputs, msg)
        defs["inputs"] = inputs
        if i_defs:
            defs["_input_defs"] = i_defs
    else:
        i_defs = {}
    return inputs, i_defs


def create_operations(interfacesDefs, type_definition, template):
    return _create_operations(interfacesDefs, type_definition, template, True)


def _create_operations(interfacesDefs, type_definition, template, split_inputs=False):
    interfaces = []
    cls = getattr(interfacesDefs, "mapCtor", interfacesDefs.__class__)
    defaults = interfacesDefs.pop("defaults", cls())
    if split_inputs and defaults.get("inputs"):
        defaultInputs, defaultInputsDefs = _split_inputs(defaults["inputs"], "")
    else:
        defaultInputs = defaults.get("inputs")
        defaultInputsDefs = defaults.get("_input_defs")
    defaultOutputs = defaults.get("outputs")
    for interface_name, value in interfacesDefs.items():
        cls = getattr(value, "mapCtor", value.__class__)
        # merge in shared:
        # shared inputs
        inputs = value.get("inputs")
        if inputs and defaultInputs:  # merge shared inputs
            inputs = cls(defaultInputs, **inputs)
        else:
            inputs = inputs or defaultInputs

        if split_inputs and inputs:
            inputs, input_defs = _split_inputs(inputs, "")
        else:
            input_defs = value.pop("_input_defs", None)
        if input_defs and defaultInputsDefs:  # merge shared inputs
            input_defs = cls(defaultInputsDefs, **inputs)
        else:
            input_defs = input_defs or defaultInputsDefs

        # shared outputs
        outputs = value.get("outputs")
        if outputs and defaultOutputs:  # merge shared outputs
            outputs = _merge_outputs(defaultOutputs, outputs)
        else:
            outputs = outputs or defaultOutputs

        # shared implementation
        implementation = value.get("implementation") or defaults.get("implementation")
        metadata = value.get("metadata")

        # create an OperationDef for each operation
        _source = value.pop("_source", None)
        if "operations" in value:
            defs = value.get("operations") or cls()
        else:
            defs = value

        for op in list(defs):
            if op in INTERFACE_DEF_RESERVED_WORDS:
                continue
            op_def = defs[op]
            if not isinstance(op_def, dict):
                if op_def == "not_implemented":
                    continue  # don't create this operation
                # if empty, copy the shared implementation
                op_def = cls(implementation=op_def or implementation)
            elif implementation and not op_def.get("implementation"):
                op_def["implementation"] = implementation
            if _source:
                op_def["_source"] = _source
            if split_inputs and op_def.get("inputs"):
                op_def["inputs"], i_defs = _split_inputs(op_def["inputs"], "")
                if i_defs:
                    op_def["_input_defs"] = i_defs
            iface = OperationDef(
                type_definition,
                interface_name,
                node_template=template,
                name=op,
                value=op_def,
                inputs=inputs,
                outputs=outputs,
                input_defs=input_defs,
                metadata=metadata,
            )
            interfaces.append(iface)

        notifications = value.get("notifications")
        if notifications:
            for no, no_def in notifications.items():
                notification = OperationDef(
                    type_definition,
                    interface_name,
                    node_template=template,
                    name=no,
                    value=no_def,
                    metadata=metadata,
                )
                interfaces.append(notification)

        # add a "default" operation that has the shared inputs and implementation
        if inputs or implementation or input_defs or outputs:
            iface = OperationDef(
                type_definition,
                interface_name,
                node_template=template,
                name="default",
                value=cls(implementation=implementation, _source=_source),
                inputs=inputs,
                outputs=outputs,
                input_defs=input_defs,
                metadata=metadata,
            )
            interfaces.append(iface)
    return interfaces

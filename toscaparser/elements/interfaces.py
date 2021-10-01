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
from toscaparser.common.exception import UnknownFieldError
from toscaparser.common.exception import MissingRequiredFieldError
from toscaparser.common.exception import ValidationError
from toscaparser.elements.statefulentitytype import StatefulEntityType

SECTIONS = (
    LIFECYCLE,
    CONFIGURE,
    INSTALL,
    LIFECYCLE_SHORTNAME,
    CONFIGURE_SHORTNAME,
    INSTALL_SHORTNAME,
) = (
    "tosca.interfaces.node.lifecycle.Standard",
    "tosca.interfaces.relationship.Configure",
    "unfurl.interfaces.Install",
    "Standard",
    "Configure",
    "Install",
)

OPERATION_DEF_RESERVED_WORDS = (DESCRIPTION, IMPLEMENTATION, INPUTS, OUTPUTS) = (
    "description",
    "implementation",
    "inputs",
    "outputs",
)

INTERFACE_DEF_RESERVED_WORDS = [
    "type",
    "inputs",
    "operations",
    "notifications",
    "description",
    "implementation",
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
) = ("primary", "dependencies", "timeout", "className", "operation_host", "environment", "preConditions", "_source")

INLINE_ARTIFACT_DEF_RESERVED_WORDS = ("description", "file", "repository", "_source")

# this is kind of misnamed, these are created for each operation defined on a interface definition
class InterfacesDef(StatefulEntityType):
    """TOSCA built-in interfaces type."""

    def __init__(
        self,
        node_type,
        interfacename,
        node_template=None,
        name=None,
        value=None,
        inputs=None,
        outputs=None,
    ):
        self.ntype = node_type
        self.node_template = node_template
        self.interfacename = interfacename
        self.name = name
        self.value = value
        self.implementation = None
        self.inputs = inputs
        self._source = None
        self.outputs = outputs
        self.defs = {}
        interfaces = getattr(self.ntype, "interfaces", None)
        if interfaces and "type" in interfaces.get(interfacename, {}):
            self.interfacetype = interfaces[interfacename]["type"]
        elif interfacename == LIFECYCLE_SHORTNAME:
            self.interfacetype = LIFECYCLE
        elif interfacename == CONFIGURE_SHORTNAME:
            self.interfacetype = CONFIGURE
        elif interfacename == INSTALL_SHORTNAME:
            self.interfacetype = INSTALL
        if not self.interfacetype:
            ExceptionCollector.appendException(
                TypeError(
                    'Interface type for interface "{0}" not found'.format(
                        self.interfacename
                    )
                )
            )
        self.type = self.interfacetype
        if node_type:
            if (
                self.node_template
                and self.node_template.custom_def
                and self.interfacetype in self.node_template.custom_def
            ):
                self.defs = self.node_template.custom_def[self.interfacetype]
            elif self.interfacetype in self.TOSCA_DEF:
                self.defs = self.TOSCA_DEF[self.interfacetype]
        if not self.defs:
            ExceptionCollector.appendException(
                TypeError(
                    'Interface type definition for interface "{0}" '
                    "not found".format(self.interfacetype)
                )
            )
        if value:
            if isinstance(self.value, dict):
                for i, j in self.value.items():
                    if i == "_source":
                        self._source = j
                    elif i == IMPLEMENTATION:
                        self.implementation = j
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
                    elif i not in OPERATION_DEF_RESERVED_WORDS:
                        ExceptionCollector.appendException(
                            UnknownFieldError(what=self._msg, field=i)
                        )
            else:
                self.implementation = value
            self.validate_implementation()

    @property
    def _msg(self):
        return 'operation "%s:%s" on template "%s"' % (
            self.interfacename,
            self.name,
            self.node_template.name,
        )

    def validate_implementation(self):
        if isinstance(self.implementation, dict):
            for key, value in self.implementation.items():
                if key == PRIMARY:
                    self.validate_inline_artifact(value)
                elif key == DEPENDENCIES:
                    if not isinstance(value, list):
                        ExceptionCollector.appendException(
                            ValidationError(message=self._msg)
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

    @property
    def lifecycle_ops(self):
        if self.defs:
            if self.type == LIFECYCLE:
                return self._ops()

    @property
    def configure_ops(self):
        if self.defs:
            if self.type == CONFIGURE:
                return self._ops()

    def _ops(self):
        ops = []
        for name in list(self.defs.keys()):
            ops.append(name)
        return ops

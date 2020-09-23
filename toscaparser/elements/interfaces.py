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

INTERFACE_DEF_RESERVED_WORDS = ["type", "inputs", "operations", "notifications", "description", "implementation"]

# this is kind of misnamed, these are created for each operation defined on a interface definition
class InterfacesDef(StatefulEntityType):
    """TOSCA built-in interfaces type."""

    def __init__(
        self,
        node_type,
        interfacetype,
        node_template=None,
        name=None,
        value=None,
        inputs=None,
        outputs=None
    ):
        self.ntype = node_type
        self.node_template = node_template
        self.iname = interfacetype
        self.name = name
        self.value = value
        self.implementation = None
        self.inputs = inputs
        self._source = None
        self.outputs = outputs
        self.defs = {}
        interfaces = getattr(self.ntype, "interfaces", None)
        if "type" in interfaces.get(interfacetype, {}):
            interfacetype = interfaces[interfacetype]["type"]
        elif interfacetype == LIFECYCLE_SHORTNAME:
            interfacetype = LIFECYCLE
        elif interfacetype == CONFIGURE_SHORTNAME:
            interfacetype = CONFIGURE
        elif interfacetype == INSTALL_SHORTNAME:
            interfacetype = INSTALL
        self.type = interfacetype
        if node_type:
            if (
                self.node_template
                and self.node_template.custom_def
                and interfacetype in self.node_template.custom_def
            ):
                self.defs = self.node_template.custom_def[interfacetype]
            else:
                self.defs = self.TOSCA_DEF[interfacetype]
        if value:
            if isinstance(self.value, dict):
                for i, j in self.value.items():
                    if i == '_source':
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
                        what = '"interfaces" of template "%s"' % self.node_template.name
                        ExceptionCollector.appendException(
                            UnknownFieldError(what=what, field=i)
                        )
            else:
                self.implementation = value

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

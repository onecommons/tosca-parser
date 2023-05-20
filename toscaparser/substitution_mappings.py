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
from toscaparser.common.exception import InvalidNodeTypeError
from toscaparser.common.exception import MissingDefaultValueError
from toscaparser.common.exception import MissingRequiredFieldError
from toscaparser.common.exception import MissingRequiredInputError
from toscaparser.common.exception import UnknownFieldError
from toscaparser.common.exception import UnknownOutputError
from toscaparser.common.exception import ValidationError
from toscaparser.elements.nodetype import NodeType
from toscaparser.utils.gettextutils import _
from toscaparser.nodetemplate import NodeTemplate

log = logging.getLogger("tosca")


class SubstitutionMappings(object):
    """SubstitutionMappings class declaration

    SubstitutionMappings exports the topology template as an
    implementation of a Node type.
    """

    # added in 1.3: substitution_filter, attributes, interfaces (and node is an extension)
    SECTIONS = (
        NODE,
        NODE_TYPE,
        REQUIREMENTS,
        CAPABILITIES,
        PROPERTIES,
        SUBSTITUTION_FILTER,
        ATTRIBUTES,
        INTERFACES,
    ) = (
        "node",
        "node_type",
        "requirements",
        "capabilities",
        "properties",
        "substitution_filter",
        "attributes",
        "interfaces",
    )

    OPTIONAL_OUTPUTS = ["tosca_id", "tosca_name", "state"]

    def __init__(self, sub_mapping_def, topology):
        self.topology = topology
        self.sub_mapping_def = sub_mapping_def
        if topology:
            self.inputs = {input.name: input for input in topology.inputs}
            self.outputs = topology.outputs or []
        else:
            self.inputs = {}
            self.outputs = []
        self.sub_mapped_node_template = None
        self.node_type = None
        self._capabilities = None
        self._requirements = None
        self._properties = None
        self._node_template = None
        self._outer_relationships = {}
        self._validate()

    def match(self, nodetemplate):
        if self.node_type and self.node_type.is_derived_from(nodetemplate.type):
            if self.substitution_filter:
                return nodetemplate.match_nodefilter(self.substitution_filter)
            return True
        return False

    def _make_node(self):
        if not self.node_type:
            return None
        tpl = dict(type=self.node_type.type, properties=self.properties)
        # XXX capabilities, requirements, attributes
        return self.topology.add_template("_substitution_mapping", tpl, False)

    def substitute(self, nodetemplate, remaining_topologies):
        if nodetemplate:
            assert not self._outer_relationships
            # each substituted node template should have its own topology
            topology = self.topology.copy()
            return topology.substitution_mappings._substitute(
                nodetemplate, remaining_topologies
            )
        else:
            return self._substitute(nodetemplate, remaining_topologies)

    def _substitute(self, nodetemplate, remaining_topologies):
        if not self._node_template:
            self._node_template = self._make_node()
        if not self._node_template:
            return self

        if nodetemplate:
            # we only care about outputs matching attributes when we have a node to substitute
            self._validate_outputs()

            # update our node template with the substituted template's properties:
            current_props = self._node_template.get_properties()
            for p in nodetemplate.get_properties_objects():
                if p.name in current_props:
                    # XXX what if schema is incompatible?
                    current_props[p.name].value = p.value
                else:
                    self._node_template._properties.append(p)
            nodetemplate.substitution = self
            self.sub_mapped_node_template = nodetemplate

        self._node_template.revalidate_properties()
        # topology might have to do its own substitutions:
        if remaining_topologies:
            self.topology._do_substitutions(remaining_topologies)
        return self

    @property
    def type(self):
        if self.sub_mapping_def:
            return self.sub_mapping_def.get(self.NODE_TYPE)

    @property
    def node(self):
        return self.sub_mapping_def.get(self.NODE)

    @property
    def capabilities(self):
        return self.sub_mapping_def.get(self.CAPABILITIES)

    @property
    def requirements(self):
        return self.sub_mapping_def.get(self.REQUIREMENTS)

    @property
    def substitution_filter(self):
        return self.sub_mapping_def.get(self.SUBSTITUTION_FILTER)

    @property
    def properties(self):
        # 3.8.8 Property mapping
        if self._properties is None:
            self._properties = {}
            mapping = self.sub_mapping_def.get(self.PROPERTIES)
            if mapping is not None:
                self._map(mapping, self._properties)
            else:
                # property mapping not defined, use all the inputs
                inputs = self.topology.parsed_params or {}
                for name, input in self.inputs.items():
                    if name in inputs:
                        value = inputs[name]
                    else:
                        value = input.default
                    self._properties[name] = value
        return self._properties

    def has_property_mapping(self):
        return self.PROPERTIES in self.sub_mapping_def and not self.node

    def get_declared_properties(self):
        if self.node:
            node = self.topology.node_templates.get(self.node)
            if node:
                return node._properties_tpl
        else:
            return self.properties
        return {}

    def get_declared_requirement_names(self):
        if self.node:
            node = self.topology.node_templates.get(self.node)
            if node:
                 # list only has one item
                return [next(iter(r)) for r in node.requirements]
        return []  # XXX extract from requirement mapping

    def add_relationship(self, name, reqDef, rel):
        # this is called in NodeTemplate.relationships by the outer node template
        self._outer_relationships.setdefault(name, []).append((name, reqDef, rel))

    def _update_requirements(self, node):
        # traceback.print_stack()
        # this is called in NodeTemplate.relationships by the inner node template
        names = []
        if node is self._node_template:
            for rels in self._outer_relationships.values():
                for name, reqDef, rel in rels:
                    names.append(name)
                    node._relationships.append((rel, {name: reqDef}, reqDef))
        return names

    def _map(self, mapping, dest):
        inputs = self.topology.parsed_params or {}
        for propname, value in mapping.items():
            # map property from input
            if isinstance(value, dict):
                if "mapping" not in value:
                    ExceptionCollector.appendException(
                        UnknownFieldError(what="SubstitutionMappings", field=value)
                    )
                    continue
                value = value["mapping"]
            if isinstance(value, list):
                input = value[0]
            else:
                input = value
            if input in inputs:
                dest[propname] = inputs[input]
            elif input in self.inputs:
                dest[propname] = self.inputs[input].default
            else:
                ExceptionCollector.appendException(
                    MissingRequiredInputError(
                        what=_("SubstitutionMappings with node_type ")
                        + self.node_type.type,
                        input_name=input,
                    )
                )

    def _validate(self):
        # Basic validation
        self._validate_keys()
        if not self._validate_type():
            return

        if self.node:
            for key in [self.PROPERTIES, self.REQUIREMENTS, self.CAPABILITIES]:
                if key in self.sub_mapping_def:
                    ExceptionCollector.appendException(
                        ValidationError(
                            message=_(
                                "substitution_mappings with explicit node declaration can not have a %s mapping declared"
                            )
                            % key
                        )
                    )
        if self.substitution_filter:
            NodeTemplate.validate_filter(
                self.substitution_filter, "substitution_filter"
            )

    def _validate_keys(self):
        """validate the keys of substitution mappings."""
        for key in self.sub_mapping_def.keys():
            if key not in self.SECTIONS:
                ExceptionCollector.appendException(
                    UnknownFieldError(what=_("SubstitutionMappings"), field=key)
                )

    def _validate_type(self):
        """validate the node_type of substitution mappings."""
        if self.node:
            node = self.topology.node_templates.get(self.node)
            if not node:
                ExceptionCollector.appendException(
                    ValidationError(
                        message=_('Unknown node "%s" declared on substitution_mappings')
                        % self.node
                    )
                )
                return False
            self._node_template = node
            self.node_type = node.type_definition
        else:
            node_type = self.sub_mapping_def.get(self.NODE_TYPE)
            if not node_type:
                ExceptionCollector.appendException(
                    MissingRequiredFieldError(
                        what=_("SubstitutionMappings used in topology_template"),
                        required=self.NODE_TYPE,
                    )
                )
                return False
            node_type_def = self.topology.custom_defs.get(node_type)
            if not node_type_def:
                ExceptionCollector.appendException(InvalidNodeTypeError(what=node_type))
                return False
            self.node_type = NodeType(node_type, self.topology.custom_defs)
        return True

    def _validate_outputs(self):
        """validate the outputs of substitution mappings.

        The outputs defined by the topology template have to match the
        attributes of the node type or the substituted node template,
        and the observable attributes of the substituted node template
        have to be defined as attributes of the node type or outputs in
        the topology template.
        """

        # The outputs defined by the topology template have to match the
        # attributes of the node type according to the specification, but
        # it's reasonable that there are more inputs than the node type
        # has properties, the specification will be amended?
        for output in self.outputs:
            if output.name not in self.node_type.get_attributes_def():
                ExceptionCollector.appendException(
                    UnknownOutputError(
                        where=_("SubstitutionMappings with node_type ")
                        + self.node_type.type,
                        output_name=output.name,
                    )
                )

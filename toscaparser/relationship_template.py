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
from toscaparser.elements.statefulentitytype import StatefulEntityType
from toscaparser.entity_template import EntityTemplate
from toscaparser.elements.entity_type import Namespace

log = logging.getLogger("tosca")


class RelationshipTemplate(EntityTemplate):
    """Relationship template."""

    SECTIONS = (
        DERIVED_FROM,
        PROPERTIES,
        REQUIREMENTS,
        INTERFACES,
        TYPE,
        DEFAULT_FOR,
        DEPENDENCIES,
        DIRECTIVES,
    ) = (
        "derived_from",
        "properties",
        "requirements",
        "interfaces",
        "type",
        "default_for",
        "dependencies",
        "directives",
    )
    ANY = "ANY"

    def __init__(
        self, relationship_template, name, custom_def=None, target=None, source=None, stub = False
    ):
        self.stub = stub
        super(RelationshipTemplate, self).__init__(
            name, relationship_template, "relationship_type", custom_def
        )
        self.target = target
        self.source = source
        self.capability = None
        self.default_for = self.entity_tpl.get(self.DEFAULT_FOR)

    def _should_validate_properties(self):
        return not self.stub

    def get_matching_capabilities(
        self, targetNodeTemplate, capability_name, cap_type_def=None
    ):
        # match on symbolic name or type name
        capability_type_name = capability_name
        if cap_type_def:
            namespace = (
                targetNodeTemplate.custom_def
                if isinstance(targetNodeTemplate.custom_def, Namespace)
                else None
            )
            capability_namespace = (
                namespace.find_namespace(cap_type_def.get("!namespace-capability"))
                if namespace
                else self.custom_def
            )
            capability_def = capability_namespace.get(capability_name)
            if capability_def:
                capability_type_name = StatefulEntityType(
                    capability_name,
                    StatefulEntityType.CAPABILITY_PREFIX,
                    capability_namespace,
                ).global_name
        # return the capabilities on the given targetNodeTemplate that matches this relationship
        capabilitiesDict = targetNodeTemplate.get_capabilities()
        # if capability_name is set, make sure the target node has a capability
        # that matching it as a name or or as a type
        if capability_name:
            capability = capabilitiesDict.get(capability_name)
            if capability:
                # just test the capability that matches the symbolic name
                capabilities = [capability]
            else:
                # name doesn't match a symbolic name, see if its a valid type name
                capabilities = [
                    cap
                    for cap in capabilitiesDict.values()
                    if cap.is_derived_from(capability_type_name)
                ]
        else:
            capabilities = list(capabilitiesDict.values())

        # if valid_target_types is set, make sure the matching capabilities are compatible
        capabilityTypes = self.type_definition.valid_target_types
        if capabilityTypes:
            capabilities = [
                cap
                for cap in capabilities
                if any(cap.is_derived_from(capType) for capType in capabilityTypes)
            ]
        elif not capability_name and len(capabilities) > 1:
            # find the best match for the targetNodeTemplate
            # if no capability was specified and there are more than one to choose from, choose the most generic
            featureCap = capabilitiesDict.get("feature")
            if featureCap:
                return [featureCap]
        return capabilities

    def is_default_connection(self):
        return self.default_for == "SELF"

    @staticmethod
    def _is_default_connection(value):
        return (
            isinstance(value.get("relationship"), dict)
            and value["relationship"].get("default_for") == "SELF"
        )

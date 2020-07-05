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

from toscaparser.entity_template import EntityTemplate
from toscaparser.properties import Property

log = logging.getLogger('tosca')


class RelationshipTemplate(EntityTemplate):
    '''Relationship template.'''

    SECTIONS = (DERIVED_FROM, PROPERTIES, REQUIREMENTS,
                INTERFACES, TYPE, DEFAULT_FOR) = \
               ('derived_from', 'properties', 'requirements', 'interfaces',
                 'type', 'default_for')
    ANY = 'ANY'

    def __init__(self, relationship_template, name, custom_def=None,
                 target=None, source=None):
        super(RelationshipTemplate, self).__init__(name,
                                                   relationship_template,
                                                   'relationship_type',
                                                   custom_def)
        self.name = name
        self.target = target
        self.source = source
        self.default_for = self.entity_tpl.get(self.DEFAULT_FOR)

    def get_matching_capabilities(self, targetNodeTemplate, capability_name=None):
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
                capabilities = [cap for cap in capabilitiesDict.values() if cap.is_derived_from(capability_name)]
        else:
            capabilities = capabilitiesDict.values()

        # if valid_target_types is set, make sure the matching capabilities are compatible
        capabilityTypes = self.type_definition.valid_target_types
        if capabilityTypes:
            capabilities = [cap for cap in capabilities
                              if any(cap.is_derived_from(capType) for capType in capabilityTypes)]
        return capabilities

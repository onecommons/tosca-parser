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

from toscaparser.elements.property_definition import PropertyDef
from toscaparser.elements.statefulentitytype import StatefulEntityType


class CapabilityType(StatefulEntityType):
    '''TOSCA built-in capabilities type.'''
    TOSCA_TYPEURI_CAPABILITY_ROOT = 'tosca.capabilities.Root'

    def __init__(self, name, ctype, ntype, custom_def=None):
        self.name = name
        super(CapabilityType, self).__init__(ctype, self.CAPABILITY_PREFIX,
                                                custom_def)
        self.nodetype = ntype

    @property
    def parent_type(self):
        '''Return a capability this capability is derived from.'''
        if not hasattr(self, 'defs'):
            return None
        pnode = self.derived_from(self.defs)
        if pnode:
            return CapabilityType(self.name, pnode,
                                     self.nodetype, self.custom_def)

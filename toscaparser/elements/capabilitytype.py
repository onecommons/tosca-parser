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


class CapabilityTypeDef(StatefulEntityType):
    '''TOSCA built-in capabilities type.'''
    TOSCA_TYPEURI_CAPABILITY_ROOT = 'tosca.capabilities.Root'

    def __init__(self, name, ctype, ntype, custom_def=None):
        self.name = name
        super(CapabilityTypeDef, self).__init__(ctype, self.CAPABILITY_PREFIX,
                                                custom_def)
        self.nodetype = ntype
        self.properties = None
        self.custom_def = custom_def
        if self.PROPERTIES in self.defs:
            self.properties = self.defs[self.PROPERTIES]

    @property
    def parent_type(self):
        '''Return a capability this capability is derived from.'''
        if not hasattr(self, 'defs'):
            return None
        pnode = self.derived_from(self.defs)
        if pnode:
            return CapabilityTypeDef(self.name, pnode,
                                     self.nodetype, self.custom_def)

    def inherits_from(self, type_names):
        '''Check this capability is in type_names

           Check if this capability or some of its parent types
           are in the list of types: type_names
        '''
        if self.type in type_names:
            return True
        elif self.parent_type:
            return self.parent_type.inherits_from(type_names)
        else:
            return False

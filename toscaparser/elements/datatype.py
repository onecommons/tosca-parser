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


from toscaparser.common.exception import ExceptionCollector, ValidationError
from toscaparser.elements.statefulentitytype import StatefulEntityType


class DataType(StatefulEntityType):
    '''TOSCA built-in and user defined complex data type.'''

    def __init__(self, datatypename, custom_def=None):
        super(DataType, self).__init__(datatypename,
                                       self.DATATYPE_NETWORK_PREFIX,
                                       custom_def)
        self.custom_def = custom_def
        if self.value_type and self.entity_value(self.defs, 'properties'):
            ExceptionCollector.appendException(
                ValidationError(message=f'Invalid datatype "{datatypename}": can not define both "type" and "properties" fields.')
            )

    @property
    def parent_type(self):
        '''Return a datatype this datatype is derived from.'''
        ptype = self.derived_from(self.defs)
        if ptype:
            return DataType(ptype, self.custom_def)
        return None

    @property
    def value_type(self):
        '''Return 'type' section in the datatype schema.'''
        return self.entity_value(self.defs, 'type')

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

from toscaparser.dataentity import DataEntity
from toscaparser.elements.constraints import Schema
from toscaparser import functions
from toscaparser.elements.scalarunit import get_scalarunit_class


class Property(object):
    '''TOSCA built-in Property type.'''

    PROPERTY_KEYS = Schema.KEYS

    ENTRY_SCHEMA_KEYS = (
        ENTRYTYPE, ENTRYPROPERTIES
    ) = (
        'type', 'properties'
    )

    def __init__(self, property_name, value, schema_dict, custom_def=None):
        self.name = property_name
        self.value = value
        self.custom_def = custom_def
        self.entity = DataEntity(schema_dict['type'], self.value, self.custom_def, self.name)
        # the value_type will be the simple if the datatype was derived from one
        self.schema = Schema(property_name, schema_dict, self.entity.datatype.value_type)
        self._entity = None
        self._entry_schema_entity = None

    @property
    def entry_schema_entity(self):
        if self._entry_schema_entity is None and self.entry_schema:
            self._entry_schema_entity = DataEntity(self.entry_schema['type'], None, self.custom_def, self.name)
        return self._entry_schema_entity

    @property
    def type(self):
        return self.schema.type

    @property
    def required(self):
        return self.schema.required

    @property
    def description(self):
        return self.schema.description

    @property
    def default(self):
        return self.schema.default

    @property
    def constraints(self):
        return self.schema.constraints

    @property
    def entry_schema(self):
        return self.schema.entry_schema

    def validate(self):
        self.value = self._validate(self.value)

    def _validate(self, value):
        '''Validate if not a reference property.'''
        if not functions.is_function(value):
            if self.type == Schema.STRING:
                value = str(value)
            metadata = self.schema.metadata
            if metadata and metadata.get('default_unit'):
                try:
                    float(value)
                    # no unit specified, append the default unit
                    if get_scalarunit_class(self.type)._check_unit_in_scalar_standard_units(metadata['default_unit']):
                        value = str(value) + metadata['default_unit']
                except:
                    pass
            value = DataEntity.validate_datatype(self.type, value,
                                                      self.entry_schema,
                                                      self.custom_def,
                                                      self.name)
            self._validate_constraints(value)
        return value

    def _validate_constraints(self, value):
        if self.constraints:
            for constraint in self.constraints:
                if constraint:
                    constraint.validate(value)

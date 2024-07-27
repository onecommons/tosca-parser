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
from toscaparser.common.exception import MissingRequiredFieldError
from toscaparser.common.exception import UnknownFieldError
from toscaparser.dataentity import DataEntity
from toscaparser.elements.constraints import Schema
from toscaparser.elements.entity_type import EntityType
from toscaparser.utils.gettextutils import _


log = logging.getLogger('tosca')


class Parameter:

    INPUTFIELD = (TYPE, VALUE, DESCRIPTION, DEFAULT, CONSTRAINTS, REQUIRED, STATUS,
                  KEY_SCHEMA, ENTRY_SCHEMA, METADATA) = ('type', 'value', 'description',
                                               'default', 'constraints',
                                               'required', 'status',
                                               'key_schema', 'entry_schema', 'metadata')

    def __init__(self, name, schema_dict, custom_defs=None):
        self.name = name
        # "type" isn't a required key for parameters
        self.schema = Schema(name, schema_dict, schema_dict.get("type", "any"))
        self.custom_defs = custom_defs or {}

        self._validate_field()
        if self.type:
            self.validate_type(self.type)

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
    def status(self):
        return self.schema.status

    @property
    def key_schema(self):
        return self.schema.key_schema

    @property
    def entry_schema(self):
        return self.schema.entry_schema

    def validate(self, value=None):
        if value is not None:
            self._validate_value(value)

    def _validate_field(self):
        for name in self.schema.schema:
            if name not in self.INPUTFIELD:
                ExceptionCollector.appendException(
                    UnknownFieldError(what='%s "%s"' % (self.__class__.__name__, self.name),
                                      field=name))

    def validate_type(self, input_type):
        if input_type not in Schema.PROPERTY_TYPES:
            ExceptionCollector.appendException(
                ValueError(_('Invalid type "%s".') % type))

    def _validate_value(self, value):
        value = DataEntity.validate_datatype(self.type, value,
                                                  self.entry_schema,
                                                  self.custom_defs,
                                                  self.name,
                                                  self.key_schema)
        if self.constraints:
            for constraint in self.constraints:
                if constraint:
                    constraint.validate(value)
        return value

class Input(Parameter):
    pass

class Output(Parameter):

    @property
    def value(self):
        return self.schema.schema.get(self.VALUE)

    def validate(self):
        if self.value is None:
            ExceptionCollector.appendException(
                MissingRequiredFieldError(what='Output "%s"' % self.name,
                                          required=self.VALUE))
        else:
            self._validate_value(self.value)

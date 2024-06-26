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
from toscaparser.common.exception import InvalidSchemaError
from toscaparser.common.exception import TOSCAException
from toscaparser.utils.gettextutils import _


class PropertyDef(object):
    '''TOSCA built-in Property type.'''

    VALID_PROPERTY_KEYNAMES = (PROPERTY_KEYNAME_DEFAULT,
                               PROPERTY_KEYNAME_REQUIRED,
                               PROPERTY_KEYNAME_STATUS) = \
        ('default', 'required', 'status')

    PROPERTY_REQUIRED_DEFAULT = True

    VALID_REQUIRED_VALUES = ['true', 'false']
    VALID_STATUS_VALUES = (PROPERTY_STATUS_SUPPORTED, PROPERTY_STATUS_SUPPORTED,
                           PROPERTY_STATUS_EXPERIMENTAL, STATUS_DEPRECATED, STATUS_REMOVED) = \
        ('supported', 'unsupported', 'experimental', 'deprecated', 'removed')

    PROPERTY_STATUS_DEFAULT = PROPERTY_STATUS_SUPPORTED

    def __init__(self, name, value=None, schema=None):
        self.name = name
        self.value = value
        self.schema = schema
        self._status = self.PROPERTY_STATUS_DEFAULT
        self._required = self.PROPERTY_REQUIRED_DEFAULT

        self._parse_error = False
        if not isinstance(schema, dict):
            msg = (_('Schema definition of "%(pname)s" must be a mapping, not: %(schema)s') % dict(pname=self.name, schema=schema))
            ExceptionCollector.appendException(
                InvalidSchemaError(message=msg))
            self._parse_error = True
            return

        try:
            # Validate required 'type' property exists
            self.schema['type']
        except KeyError:
            self._parse_error = True
            msg = (_('Schema definition of "%(pname)s" must have a "type" '
                     'attribute.') % dict(pname=self.name))
            ExceptionCollector.appendException(
                InvalidSchemaError(message=msg))
        self._load_required_attr_from_schema()
        self._load_status_attr_from_schema()

    @property
    def type(self):
        if self.schema:
            return self.schema['type']
        return None

    @property
    def default(self):
        if self.schema:
            return self.schema.get(self.PROPERTY_KEYNAME_DEFAULT)
        return None

    @property
    def required(self):
        return self._required

    def _load_required_attr_from_schema(self):
        # IF 'required' keyname exists verify it's a boolean,
        # if so override default
        if self.PROPERTY_KEYNAME_REQUIRED in self.schema:
            value = self.schema[self.PROPERTY_KEYNAME_REQUIRED]
            if isinstance(value, bool):
                self._required = value
            else:
                valid_values = ', '.join(self.VALID_REQUIRED_VALUES)
                attr = self.PROPERTY_KEYNAME_REQUIRED
                TOSCAException.generate_inv_schema_property_error(self,
                                                                  attr,
                                                                  value,
                                                                  valid_values)

    @property
    def status(self):
        return self._status

    def _load_status_attr_from_schema(self):
        # IF 'status' keyname exists verify it's a valid value,
        # if so override default
        if self.PROPERTY_KEYNAME_STATUS in self.schema:
            value = self.schema[self.PROPERTY_KEYNAME_STATUS]
            if value in self.VALID_STATUS_VALUES:
                self._status = value
            else:
                valid_values = ', '.join(self.VALID_STATUS_VALUES)
                attr = self.PROPERTY_KEYNAME_STATUS
                TOSCAException.generate_inv_schema_property_error(self,
                                                                  attr,
                                                                  value,
                                                                  valid_values)

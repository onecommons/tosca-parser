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

import collections.abc
import datetime
import re
import json

from toscaparser.common.exception import ExceptionCollector
from toscaparser.common.exception import InvalidSchemaError
from toscaparser.common.exception import ValidationError
from toscaparser.elements.portspectype import PortSpec
from toscaparser.elements import scalarunit
from toscaparser.utils.gettextutils import _
from toscaparser.utils import yamlparser


class Schema(collections.abc.Mapping):

    KEYS = (TYPE, REQUIRED, DESCRIPTION, DEFAULT, CONSTRAINTS, KEY_SCHEMA, ENTRY_SCHEMA, STATUS, METADATA, TITLE) = (
        "type",
        "required",
        "description",
        "default",
        "constraints",
        "key_schema",
        "entry_schema",
        "status",
        "metadata",
        "title"
    )

    PROPERTY_TYPES = (
        INTEGER,
        STRING,
        BOOLEAN,
        FLOAT,
        RANGE,
        NUMBER,
        TIMESTAMP,
        LIST,
        MAP,
        SCALAR_UNIT_SIZE,
        SCALAR_UNIT_FREQUENCY,
        SCALAR_UNIT_TIME,
        SCALAR_UNIT_BITRATE,
        VERSION,
        PORTDEF_FULLNAME,
        PORTDEF,
        PORTSPEC_FULLNAME,
        PORTSPEC,
        ANY,
    ) = (
        "integer",
        "string",
        "boolean",
        "float",
        "range",
        "number",
        "timestamp",
        "list",
        "map",
        "scalar-unit.size",
        "scalar-unit.frequency",
        "scalar-unit.time",
        "scalar-unit.bitrate",
        "version",
        "tosca.datatypes.network.PortDef",
        "PortDef",
        PortSpec.TYPE_URI,
        PortSpec.SHORTNAME,
        "any",
    )

    PYTHON_TO_PROPERTY_TYPES = {
     int: INTEGER,
     float: FLOAT,
     str: STRING,
     bool: BOOLEAN,
     list: LIST,
     dict: MAP,
    }

    SCALAR_UNIT_SIZE_DEFAULT = "B"

    def __init__(self, name, schema_dict, datatype=None):
        self.name = name
        if not isinstance(schema_dict, collections.abc.Mapping):
            msg = (_('Schema definition of "%(pname)s" ("%(schema)s") must be a dict not a %(type)s.')
                   % dict(pname=name, schema=schema_dict, type=type(schema_dict).__name__))
            ExceptionCollector.appendException(InvalidSchemaError(message=msg))

        try:
            self.type = datatype or schema_dict["type"]
        except KeyError:
            msg = _(
                'Schema definition of "%(pname)s" must have a "type" ' "attribute."
            ) % dict(pname=name)
            ExceptionCollector.appendException(InvalidSchemaError(message=msg))

        self.schema = schema_dict
        self._len = None
        self.constraints_list = None

    @property
    def required(self):
        return self.schema.get(self.REQUIRED, True)

    @property
    def description(self):
        return self.schema.get(self.DESCRIPTION, "")

    @property
    def title(self):
        return self.schema.get(self.TITLE, "")

    @property
    def default(self):
        return self.schema.get(self.DEFAULT)

    @property
    def status(self):
        return self.schema.get(self.STATUS, "")

    @property
    def metadata(self):
        return self.schema.get(self.METADATA) or {}

    @property
    def constraints(self):
        if self.constraints_list is None:
            constraint_schemata = self.schema.get(self.CONSTRAINTS)
            if constraint_schemata:
                self.constraints_list = [
                    Constraint(self.name, self.type, cschema)
                    for cschema in constraint_schemata
                ]
            else:
                self.constraints_list = []
        return self.constraints_list

    @property
    def key_schema(self):
        return self.schema.get(self.KEY_SCHEMA)

    @property
    def entry_schema(self):
        return self.schema.get(self.ENTRY_SCHEMA)

    def __getitem__(self, key):
        return self.schema[key]

    def __iter__(self):
        for k in self.KEYS:
            try:
                self.schema[k]
            except KeyError:
                pass
            else:
                yield k

    def __len__(self):
        if self._len is None:
            self._len = len(list(iter(self)))
        return self._len


class Constraint(object):
    """Parent class for constraints for a Property or Input."""

    CONSTRAINTS = (
        EQUAL,
        GREATER_THAN,
        GREATER_OR_EQUAL,
        LESS_THAN,
        LESS_OR_EQUAL,
        IN_RANGE,
        VALID_VALUES,
        LENGTH,
        MIN_LENGTH,
        MAX_LENGTH,
        PATTERN,
        SCHEMA,
    ) = (
        "equal",
        "greater_than",
        "greater_or_equal",
        "less_than",
        "less_or_equal",
        "in_range",
        "valid_values",
        "length",
        "min_length",
        "max_length",
        "pattern",
        "schema",
    )

    def __new__(cls, property_name=None, property_type=None, constraint=None):
        if cls is not Constraint:
            return super(Constraint, cls).__new__(cls)

        if(not isinstance(constraint, collections.abc.Mapping) or
           len(constraint) != 1):
            ExceptionCollector.appendException(
                InvalidSchemaError(message=_("Invalid constraint: %s (must be a map with one key)") % constraint)
            )
        else:
            for type in constraint.keys():
                ConstraintClass = get_constraint_class(type)
                if not ConstraintClass:
                    msg = _('Invalid property "%s".') % type
                    ExceptionCollector.appendException(InvalidSchemaError(message=msg))

            return ConstraintClass(property_name, property_type, constraint)

    def __init__(self, property_name, property_type, constraint):
        self.property_name = property_name
        self.property_type = property_type
        self.constraint_value = constraint[self.constraint_key]
        self.constraint_value_msg = self.constraint_value
        if self.property_type in scalarunit.ScalarUnit.SCALAR_UNIT_TYPES:
            self.constraint_value = self._get_scalarunit_constraint_value()
        # check if constraint is valid for property type
        if property_type not in self.valid_prop_types:
            msg = _(
                'Property "%(ctype)s" is not valid for data type ' '"%(dtype)s".'
            ) % dict(ctype=self.constraint_key, dtype=property_type)
            ExceptionCollector.appendException(InvalidSchemaError(message=msg))

    def _get_scalarunit_constraint_value(self):
        if self.property_type in scalarunit.ScalarUnit.SCALAR_UNIT_TYPES:
            ScalarUnit_Class = scalarunit.get_scalarunit_class(self.property_type)
        if isinstance(self.constraint_value, list):
            return [
                ScalarUnit_Class(v).get_num_from_scalar_unit()
                for v in self.constraint_value
            ]
        else:
            return ScalarUnit_Class(self.constraint_value).get_num_from_scalar_unit()

    def _err_msg(self, value):
        return _('Property "%s" could not be validated.') % self.property_name

    def validate(self, value):
        import toscaparser.functions

        self.value_msg = value
        if toscaparser.functions.is_function(value):
            return
        if self.property_type in scalarunit.ScalarUnit.SCALAR_UNIT_TYPES:
            value = scalarunit.get_scalarunit_value(self.property_type, value)
        try:
            if not self._is_valid(value):
                err_msg = self._err_msg(value)
                ExceptionCollector.appendException(ValidationError(message=err_msg))
        except Exception as e:
            err_msg = self._err_msg(value)
            exc = ValidationError(message=err_msg)
            exc.__cause__ = e
            ExceptionCollector.appendException(exc)

class Equal(Constraint):
    """Constraint class for "equal"

    Constrains a property or parameter to a value equal to ('=')
    the value declared.
    """

    constraint_key = Constraint.EQUAL

    valid_prop_types = Schema.PROPERTY_TYPES

    def _is_valid(self, value):
        if value == self.constraint_value:
            return True

        return False

    def _err_msg(self, value):
        return _(
            'The value "%(pvalue)s" of property "%(pname)s" is not '
            'equal to "%(cvalue)s".'
        ) % dict(
            pname=self.property_name,
            pvalue=self.value_msg,
            cvalue=self.constraint_value_msg,
        )


class GreaterThan(Constraint):
    """Constraint class for "greater_than"

    Constrains a property or parameter to a value greater than ('>')
    the value declared.
    """

    constraint_key = Constraint.GREATER_THAN

    valid_types = (int, float, datetime.date, datetime.time, datetime.datetime)

    valid_prop_types = (
        Schema.INTEGER,
        Schema.FLOAT,
        Schema.NUMBER,
        Schema.TIMESTAMP,
        Schema.SCALAR_UNIT_SIZE,
        Schema.SCALAR_UNIT_FREQUENCY,
        Schema.SCALAR_UNIT_TIME,
    )

    def __init__(self, property_name, property_type, constraint):
        super(GreaterThan, self).__init__(property_name, property_type, constraint)
        if not isinstance(constraint[self.GREATER_THAN], self.valid_types):
            ExceptionCollector.appendException(
                InvalidSchemaError(
                    message=_(
                        'The property "greater_than" ' "expects comparable values."
                    )
                )
            )

    def _is_valid(self, value):
        if value > self.constraint_value:
            return True

        return False

    def _err_msg(self, value):
        return _(
            'The value "%(pvalue)s" of property "%(pname)s" must be '
            'greater than "%(cvalue)s".'
        ) % dict(
            pname=self.property_name,
            pvalue=self.value_msg,
            cvalue=self.constraint_value_msg,
        )


class GreaterOrEqual(Constraint):
    """Constraint class for "greater_or_equal"

    Constrains a property or parameter to a value greater than or equal
    to ('>=') the value declared.
    """

    constraint_key = Constraint.GREATER_OR_EQUAL

    valid_types = (int, float, datetime.date, datetime.time, datetime.datetime)

    valid_prop_types = (
        Schema.INTEGER,
        Schema.FLOAT,
        Schema.NUMBER,
        Schema.TIMESTAMP,
        Schema.SCALAR_UNIT_SIZE,
        Schema.SCALAR_UNIT_FREQUENCY,
        Schema.SCALAR_UNIT_TIME,
    )

    def __init__(self, property_name, property_type, constraint):
        super(GreaterOrEqual, self).__init__(property_name, property_type, constraint)
        if not isinstance(self.constraint_value, self.valid_types):
            ExceptionCollector.appendException(
                InvalidSchemaError(
                    message=_(
                        "The property "
                        '"greater_or_equal" expects '
                        "comparable values."
                    )
                )
            )

    def _is_valid(self, value):
        if value is not None and value >= self.constraint_value:
            return True
        return False

    def _err_msg(self, value):
        return _(
            'The value "%(pvalue)s" of property "%(pname)s" must be '
            'greater than or equal to "%(cvalue)s".'
        ) % dict(
            pname=self.property_name,
            pvalue=self.value_msg,
            cvalue=self.constraint_value_msg,
        )


class LessThan(Constraint):
    """Constraint class for "less_than"

    Constrains a property or parameter to a value less than ('<')
    the value declared.
    """

    constraint_key = Constraint.LESS_THAN

    valid_types = (int, float, datetime.date, datetime.time, datetime.datetime)

    valid_prop_types = (
        Schema.INTEGER,
        Schema.FLOAT,
        Schema.NUMBER,
        Schema.TIMESTAMP,
        Schema.SCALAR_UNIT_SIZE,
        Schema.SCALAR_UNIT_FREQUENCY,
        Schema.SCALAR_UNIT_TIME,
    )

    def __init__(self, property_name, property_type, constraint):
        super(LessThan, self).__init__(property_name, property_type, constraint)
        if not isinstance(self.constraint_value, self.valid_types):
            ExceptionCollector.appendException(
                InvalidSchemaError(
                    message=_('The property "less_than" ' "expects comparable values.")
                )
            )

    def _is_valid(self, value):
        if value < self.constraint_value:
            return True

        return False

    def _err_msg(self, value):
        return _(
            'The value "%(pvalue)s" of property "%(pname)s" must be '
            'less than "%(cvalue)s".'
        ) % dict(
            pname=self.property_name,
            pvalue=self.value_msg,
            cvalue=self.constraint_value_msg,
        )


class LessOrEqual(Constraint):
    """Constraint class for "less_or_equal"

    Constrains a property or parameter to a value less than or equal
    to ('<=') the value declared.
    """

    constraint_key = Constraint.LESS_OR_EQUAL

    valid_types = (int, float, datetime.date, datetime.time, datetime.datetime)

    valid_prop_types = (
        Schema.INTEGER,
        Schema.FLOAT,
        Schema.NUMBER,
        Schema.TIMESTAMP,
        Schema.SCALAR_UNIT_SIZE,
        Schema.SCALAR_UNIT_FREQUENCY,
        Schema.SCALAR_UNIT_TIME,
    )

    def __init__(self, property_name, property_type, constraint):
        super(LessOrEqual, self).__init__(property_name, property_type, constraint)
        if not isinstance(self.constraint_value, self.valid_types):
            ExceptionCollector.appendException(
                InvalidSchemaError(
                    message=_(
                        'The property "less_or_equal" ' "expects comparable values."
                    )
                )
            )

    def _is_valid(self, value):
        if value <= self.constraint_value:
            return True

        return False

    def _err_msg(self, value):
        return _(
            'The value "%(pvalue)s" of property "%(pname)s" must be '
            'less than or equal to "%(cvalue)s".'
        ) % dict(
            pname=self.property_name,
            pvalue=self.value_msg,
            cvalue=self.constraint_value_msg,
        )


class InRange(Constraint):
    """Constraint class for "in_range"

    Constrains a property or parameter to a value in range of (inclusive)
    the two values declared.
    """

    UNBOUNDED = "UNBOUNDED"

    constraint_key = Constraint.IN_RANGE

    valid_types = (int, float, datetime.date, datetime.time, datetime.datetime, str)

    valid_prop_types = (
        Schema.INTEGER,
        Schema.FLOAT,
        Schema.NUMBER,
        Schema.TIMESTAMP,
        Schema.SCALAR_UNIT_SIZE,
        Schema.SCALAR_UNIT_FREQUENCY,
        Schema.SCALAR_UNIT_TIME,
        Schema.RANGE,
        Schema.PORTDEF_FULLNAME,
        Schema.PORTDEF,
    )

    def __init__(self, property_name, property_type, constraint):
        super(InRange, self).__init__(property_name, property_type, constraint)
        if(not isinstance(self.constraint_value, collections.abc.Sequence) or
           (len(constraint[self.IN_RANGE]) != 2)):
            ExceptionCollector.appendException(
                InvalidSchemaError(
                    message=_('The property "in_range" ' "expects a list.")
                )
            )

        msg = _('The property "in_range" expects comparable values')
        for value in self.constraint_value:
            if not isinstance(value, self.valid_types):
                ExceptionCollector.appendException(InvalidSchemaError(message=msg + f", not {type(value)}"))

            # The only string we allow for range are scalars and the special value 'UNBOUNDED'
            if isinstance(value, str):
                if value != self.UNBOUNDED:
                    ExceptionCollector.appendException(InvalidSchemaError(message=msg + f', not "{value}"'))

        self.min = self.constraint_value[0]
        self.max = self.constraint_value[1]

    def _is_valid(self, value):
        if isinstance(value, collections.abc.MutableSequence):
            # its a range
            min = value[0]
            max = value[1]
        else:
            min = max = value
        if not isinstance(self.min, str):
            if min < self.min:
                return False
        if not isinstance(self.max, str):
            if max > self.max:
                return False
        return True

    def _err_msg(self, value):
        return _(
            'The value "%(pvalue)s" of property "%(pname)s" is out of '
            'range "(min:%(vmin)s, max:%(vmax)s)".'
        ) % dict(
            pname=self.property_name,
            pvalue=self.value_msg,
            vmin=self.constraint_value_msg[0],
            vmax=self.constraint_value_msg[1],
        )


class ValidValues(Constraint):
    """Constraint class for "valid_values"

    Constrains a property or parameter to a value that is in the list of
    declared values.
    """

    constraint_key = Constraint.VALID_VALUES

    valid_prop_types = Schema.PROPERTY_TYPES

    def __init__(self, property_name, property_type, constraint):
        super(ValidValues, self).__init__(property_name, property_type,
                                          constraint)
        if not isinstance(self.constraint_value, collections.abc.Sequence):
            ExceptionCollector.appendException(
                InvalidSchemaError(
                    message=_('The property "valid_values" ' "expects a list.")
                )
            )

    def _is_valid(self, value):
        if isinstance(value, list):
            return all(v in self.constraint_value for v in value)
        return value in self.constraint_value

    def _err_msg(self, value):
        allowed = "[%s]" % ", ".join(str(a) for a in self.constraint_value)
        return _(
            'The value "%(pvalue)s" of property "%(pname)s" is not '
            'valid. Expected a value from "%(cvalue)s".'
        ) % dict(pname=self.property_name, pvalue=value, cvalue=allowed)


class Length(Constraint):
    """Constraint class for "length"

    Constrains the property or parameter to a value of a given length.
    """

    constraint_key = Constraint.LENGTH

    valid_types = (int,)

    valid_prop_types = (Schema.STRING,)

    def __init__(self, property_name, property_type, constraint):
        super(Length, self).__init__(property_name, property_type, constraint)
        if not isinstance(self.constraint_value, self.valid_types):
            ExceptionCollector.appendException(
                InvalidSchemaError(
                    message=_('The property "length" expects ' "an integer.")
                )
            )

    def _is_valid(self, value):
        if isinstance(value, str) and len(value) == self.constraint_value:
            return True

        return False

    def _err_msg(self, value):
        return _(
            'Length of value "%(pvalue)s" of property "%(pname)s" '
            'must be equal to "%(cvalue)s".'
        ) % dict(pname=self.property_name, pvalue=value, cvalue=self.constraint_value)


class MinLength(Constraint):
    """Constraint class for "min_length"

    Constrains the property or parameter to a value to a minimum length.
    """

    constraint_key = Constraint.MIN_LENGTH

    valid_types = (int,)

    valid_prop_types = (Schema.STRING, Schema.MAP, Schema.LIST)

    def __init__(self, property_name, property_type, constraint):
        super(MinLength, self).__init__(property_name, property_type, constraint)
        if not isinstance(self.constraint_value, self.valid_types):
            ExceptionCollector.appendException(
                InvalidSchemaError(
                    message=_('The property "min_length" ' "expects an integer.")
                )
            )

    def _is_valid(self, value):
        if (isinstance(value, (str, dict, list)) and
           len(value) >= self.constraint_value):
            return True

        return False

    def _err_msg(self, value):
        return _(
            'Length of value "%(pvalue)s" of property "%(pname)s" '
            'must be at least "%(cvalue)s".'
        ) % dict(pname=self.property_name, pvalue=value, cvalue=self.constraint_value)


class MaxLength(Constraint):
    """Constraint class for "max_length"

    Constrains the property or parameter to a value to a maximum length.
    """

    constraint_key = Constraint.MAX_LENGTH

    valid_types = (int,)

    valid_prop_types = (Schema.STRING, Schema.MAP, Schema.LIST)

    def __init__(self, property_name, property_type, constraint):
        super(MaxLength, self).__init__(property_name, property_type, constraint)
        if not isinstance(self.constraint_value, self.valid_types):
            ExceptionCollector.appendException(
                InvalidSchemaError(
                    message=_('The property "max_length" ' "expects an integer.")
                )
            )

    def _is_valid(self, value):
        if (isinstance(value, (str, dict, list)) and
           len(value) <= self.constraint_value):
            return True

        return False

    def _err_msg(self, value):
        return _(
            'Length of value "%(pvalue)s" of property "%(pname)s" '
            'must be no greater than "%(cvalue)s".'
        ) % dict(pname=self.property_name, pvalue=value, cvalue=self.constraint_value)


class Pattern(Constraint):
    """Constraint class for "pattern"

    Constrains the property or parameter to a value that is allowed by
    the provided regular expression.
    """

    constraint_key = Constraint.PATTERN

    valid_types = str

    valid_prop_types = (Schema.STRING,)

    def __init__(self, property_name, property_type, constraint):
        super(Pattern, self).__init__(property_name, property_type, constraint)
        if not isinstance(self.constraint_value, self.valid_types):
            ExceptionCollector.appendException(
                InvalidSchemaError(
                    message=_('The property "pattern" ' "expects a string.")
                )
            )
        self.match = re.compile(self.constraint_value).match

    def _is_valid(self, value):
        if not isinstance(value, str):
            return False
        match = self.match(value)
        return match is not None and match.end() == len(value)

    def _err_msg(self, value):
        return _(
            'The value "%(pvalue)s" of property "%(pname)s" does not '
            'match pattern "%(cvalue)s".'
        ) % dict(pname=self.property_name, pvalue=value, cvalue=self.constraint_value)


class SchemaConstraint(Constraint):
    """Constraint class for "schema"

    Constrains the property or parameter to a value that is allowed by
    the provided json schema.
    """

    constraint_key = Constraint.SCHEMA

    valid_types = str

    valid_prop_types = (Schema.STRING, Schema.ANY)

    def __init__(self, property_name, property_type, constraint):
        super(SchemaConstraint, self).__init__(property_name, property_type, constraint)
        if not isinstance(self.constraint_value, self.valid_types):
            ExceptionCollector.appendException(
                InvalidSchemaError(
                    message=_('The "schema" constraint expects a string.')
                )
            )
        self.schema = json.loads(self.constraint_value)
        from jsonschema import Draft7Validator

        Draft7Validator.check_schema(self.schema)

    def _is_valid(self, value):
        from jsonschema import Draft7Validator

        if self.property_type != Schema.ANY:
            value = yamlparser.simple_parse(value)

        validator = Draft7Validator(self.schema)
        errors = list(validator.iter_errors(value))
        if not errors:
            return True
        self.message = "\n".join(e.message for e in errors[:1])
        return False

    def _err_msg(self, value):
        return _(
            'The value "%(pvalue)s" of property "%(pname)s" does not '
            'had the following errors validating its json schema: "%(cvalue)s".'
        ) % dict(pname=self.property_name, pvalue=value, cvalue=self.message)


constraint_mapping = {
    Constraint.EQUAL: Equal,
    Constraint.GREATER_THAN: GreaterThan,
    Constraint.GREATER_OR_EQUAL: GreaterOrEqual,
    Constraint.LESS_THAN: LessThan,
    Constraint.LESS_OR_EQUAL: LessOrEqual,
    Constraint.IN_RANGE: InRange,
    Constraint.VALID_VALUES: ValidValues,
    Constraint.LENGTH: Length,
    Constraint.MIN_LENGTH: MinLength,
    Constraint.MAX_LENGTH: MaxLength,
    Constraint.PATTERN: Pattern,
    Constraint.SCHEMA: SchemaConstraint,
}


def get_constraint_class(type):
    return constraint_mapping.get(type)

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
from toscaparser.common.exception import UnknownFieldError, ValidationError
from toscaparser.entity_template import EntityTemplate
from toscaparser.elements.constraints import Constraint, get_constraint_class


SECTIONS = (DELEGATE, SET_STATE, CALL_OPERATION, INLINE) = \
              ('delegate', 'set_state', 'call_operation', 'inline')

log = logging.getLogger('tosca')

PRECONDITION_SECTIONS = (TARGET, TARGET_RELATIONSHIP, CONDITION) = (
                          'target', 'target_relationship', "condition")

class Precondition(EntityTemplate):

    '''Step defined in workflows of topology template'''

    def __init__(self, precondition_tpl):
        self.precondition_tpl = precondition_tpl
        self._validate_keys()
        self._condition = None
        self.target = self.precondition_tpl.get('target')
        self.target_relationship = self.precondition_tpl.get('target_relationship')

    def _validate_keys(self):
        for key in self.precondition_tpl.keys():
            if key not in PRECONDITION_SECTIONS:
                ExceptionCollector.appendException(
                    UnknownFieldError(what='PreCondition',
                                      field=key))

    @property
    def condition(self):
        """
        filter: # filter is a list of clauses. Matching between clauses is and.
          - or: # only one of sub-clauses must be true.
            - assert:
              - foo: [{equals: true}]
            - assert:
              - bar: [{greater_than: 2}, {less_than: 20}]
      """
        if self._condition is None:
            self._condition = list(ConditionClause.getConditions(self.precondition_tpl.get(CONDITION, [])))
        return self._condition

class ConditionClause(object):

  def __init__(self, name, definition):
    self.name = name
    if name in ['and', 'or', 'not', 'assert']:
        self.conditions = list(self.getConditions(definition))
    else: # 3.6.25.3 Direct assertion definition
        if isinstance(definition, dict):
            definition = [definition]
        # hack: pick a prop_type to avoid validation error
        # XXX need to get the real property_type from the target's attribute definition
        self.conditions = [Constraint(name,
                            get_constraint_class(next(iter(constraint))).valid_prop_types[0],
                            constraint) for constraint in definition]

  def evaluate(self, attributes):
    if self.name == 'not':
        for condition in self.conditions:
            if not condition.evaluate(attributes):
                return True
        return False
    elif self.name in ['and', 'assert']:
        for condition in self.conditions:
            if not condition.evaluate(attributes):
                return False
        return True
    elif self.name == 'or':
        for condition in self.conditions:
            if condition.evaluate(attributes):
                return True
    else:
        # 3.6.25.3 Direct assertion definition
        if self.name not in attributes:
            return False
        value = attributes[self.name]
        for condition in self.conditions:
            # XXX:
            #if condition.property_type in scalarunit.ScalarUnit.SCALAR_UNIT_TYPES:
            #  value = scalarunit.get_scalarunit_value(condition.property_type, value)
            if not condition._is_valid(value):
                return False
        return True

  @staticmethod
  def getConditions(constraints):
      for constraint in constraints:
          key, value = list(constraint.items())[0]
          yield ConditionClause(key, value)

class Activity(object):

    '''Step defined in workflows of topology template'''

    def __init__(self, activity_tpl):
        self.activity_tpl = activity_tpl
        self._validate_keys()
        self.type = list(self.activity_tpl.keys())[0]
        val = self.activity_tpl[self.type]
        if isinstance(val, dict):
            self.inputs = val.pop('inputs', None)
            # the other item will be a string:
            # delegate and inline both take workflow and inputs, call_operation takes operation and inputs
            setattr(self, self.type, list(val.values())[0])
        else:
            setattr(self, self.type, val)
            self.inputs = None

    def _validate_keys(self):
        if len(self.activity_tpl) != 1:
            ExceptionCollector.appendException(
                ValidationError(message="Invalid Activity"))

        for key in self.activity_tpl.keys():
            if key not in SECTIONS:
                ExceptionCollector.appendException(
                    UnknownFieldError(what='Activity',
                                      field=key))

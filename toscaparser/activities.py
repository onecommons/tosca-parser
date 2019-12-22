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
from toscaparser.common.exception import UnknownFieldError
from toscaparser.entity_template import EntityTemplate
from toscaparser.elements.constraints import Constraint


SECTIONS = (DELEGATE, SET_STATE, CALL_OPERATION, INLINE) = \
              ('delegate', 'set_state', 'call_operation', 'inline')

# delegate and inline both take 'workflow', 'inputs', call_operation takes operation and inputs

log = logging.getLogger('tosca')

class ConditionClause(object):

  def __init__(self, name, definition):
    self.name = name
    self.conditions = list(self._getConditions(definition))

  @staticmethod
  def _getConditions(constraints):
      for constraint in constraints:
          key, value = list(constraint.items())[0]
          if key in ['and', 'or', 'not', 'assert']:
              yield ConditionClause(key, value)
          else:
              yield Constraint(key, None, value)

class Activity(EntityTemplate):

    '''Step defined in workflows of topology template'''

    def __init__(self, activity_tpl):
        self.activity_tpl = activity_tpl
        self._validate_keys()
        for key in SECTIONS:
          setattr(self, key, self.activity_tpl.get(key))

    def _validate_keys(self):
        for key in self.activity_tpl.keys():
            if key not in SECTIONS:
                ExceptionCollector.appendException(
                    UnknownFieldError(what='Activity',
                                      field=key))

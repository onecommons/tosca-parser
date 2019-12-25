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
import six
from toscaparser.common.exception import ExceptionCollector
from toscaparser.common.exception import UnknownFieldError
from toscaparser.entity_template import EntityTemplate
from toscaparser.activities import Activity, ConditionClause

SECTIONS = (TARGET, TARGET_RELATIONSHIP, OPERATION_HOST, FILTER,
            ACTIVITIES, ON_SUCCESS, ON_FAILURE) = \
           ('target', 'target_relationship', 'operation_host', 'filter',
            'activities', 'on_success', 'on_failure')

log = logging.getLogger('tosca')

class Step(EntityTemplate):

    '''Step defined in workflows of topology template'''

    def __init__(self, name, step_tpl):
        self.name = name
        self.step_tpl = step_tpl
        self._validate_keys()
        self._activities = None
        self._filter = None
        for key in (TARGET, TARGET_RELATIONSHIP, OPERATION_HOST):
            setattr(self, key, self.step_tpl.get(key))
        for key in ('on_success', 'on_failure'):
            v = self.step_tpl.get(key) or []
            if isinstance(v, six.string_types):
              v = [v]
            setattr(self, key, v)
        self.activities
        self.filter

    @property
    def activities(self):
      if self._activities is None:
        self._activities = [Activity(tpl) for tpl in self.step_tpl.get(ACTIVITIES, [])]
      return self._activities

    @property
    def filter(self):
        """
        filter: # filter is a list of clauses. Matching between clauses is and.
          - or: # only one of sub-clauses must be true.
            - assert:
              - foo: [{equals: true}]
            - assert:
              - bar: [{greater_than: 2}, {less_than: 20}]
      """
        if self._filter is None:
            self._filter = list(ConditionClause.getConditions(self.step_tpl.get(FILTER, [])))
        return self._filter

    def _validate_keys(self):
        # XXX validate target and activities are present and valid
        for key in self.step_tpl.keys():
            if key not in SECTIONS:
                ExceptionCollector.appendException(
                    UnknownFieldError(what='Step "%s"' % self.name,
                                      field=key))

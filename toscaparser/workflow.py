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
from toscaparser.steps import Step
from toscaparser.utils import validateutils
from toscaparser.activities import Precondition

SECTIONS = (METADATA, DESCRIPTION, INPUTS, PRECONDITIONS, STEPS, IMPLEMENTATION, OUTPUTS) = \
           ('metadata', 'description',
            'inputs', 'preconditions', 'steps', 'implementation', 'outputs')

log = logging.getLogger('tosca')


class Workflow(object):
    '''Workflows defined in Topology template.'''
    def __init__(self, name, workflow, custom_def=None):
        self.name = name
        self._tpl = workflow
        self.meta_data = None
        if METADATA in workflow:
            self.meta_data = workflow.get(METADATA)
            validateutils.validate_map(self.meta_data)
        self._validate_keys()
        self.steps = self._steps(workflow.get(STEPS))
        self._validate_steps()
        self.inputs = workflow.get('inputs')
        self.preconditions = [Precondition(tpl) for tpl in workflow.get(PRECONDITIONS, [])]
        self.outputs = workflow.get('outputs')

    def _validate_steps(self):
      steps = set()
      for step in self.steps.values():
        steps.update(step.on_success + step.on_failure)
      missing = steps.difference(self.steps)
      if missing:
          msg = "Workflow %s referencing missing step(s): %s", (self.name, missing)
          ExceptionCollector.appendException(
              ValidationError(message=msg))

    @property
    def description(self):
        return self._tpl.get('description')

    @property
    def metadata(self):
        return self._tpl.get('metadata')

    def _steps(self, steps):
        return {name: Step(name, step_tpl) for name, step_tpl in steps.items()}

    def _validate_keys(self):
        for key in self._tpl.keys():
            if key not in SECTIONS:
                ExceptionCollector.appendException(
                    UnknownFieldError(what='Workflow "%s"' % self.name,
                                      field=key))

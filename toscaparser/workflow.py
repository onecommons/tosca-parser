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
from toscaparser.steps import Step
from toscaparser.utils import validateutils
from toscaparser.activities import ConditionClause

SECTIONS = (TYPE, METADATA, DESCRIPTION, INPUTS, PRECONDITIONS, STEPS, IMPLEMENTATION, OUTPUTS) = \
           ('type', 'metadata', 'description',
            'inputs', 'preconditions', 'steps', 'implementation', 'outputs')

log = logging.getLogger('tosca')


class Workflow(EntityTemplate):
    '''Workflows defined in Topology template.'''
    def __init__(self, name, workflow, custom_def=None):
        super(Workflow, self).__init__(name,
                                     workflow,
                                     'workflow_type',
                                     custom_def)
        self.meta_data = None
        if self.METADATA in workflow:
            self.meta_data = workflow.get(self.METADATA)
            validateutils.validate_map(self.meta_data)
        self.steps = self._steps(workflow.get(STEPS))
        self.inputs = workflow.get('inputs')
        self._validate_keys()
        self.preconditions = list(ConditionClause.getConditions(workflow.get(PRECONDITIONS, [])))
        self.outputs = workflow.get('outputs')

    @property
    def description(self):
        return self.entity_tpl.get('description')

    @property
    def metadata(self):
        return self.entity_tpl.get('metadata')

    def _step(self, step):
        stepObjs = []
        if step:
            for name, step_tpl in step.items():
                stepObj = Step(name, step_tpl)
                stepObjs.append(stepObj)
        return stepObjs

    def _validate_keys(self):
        for key in self.entity_tpl.keys():
            if key not in SECTIONS:
                ExceptionCollector.appendException(
                    UnknownFieldError(what='Workflow "%s"' % self.name,
                                      field=key))

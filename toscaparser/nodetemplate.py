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
from toscaparser.common.exception import InvalidPropertyValueError
from toscaparser.common.exception import MissingRequiredFieldError
from toscaparser.common.exception import TypeMismatchError
from toscaparser.common.exception import UnknownFieldError
from toscaparser.common.exception import ValidationError
from toscaparser.dataentity import DataEntity
from toscaparser.entity_template import EntityTemplate
from toscaparser.relationship_template import RelationshipTemplate
from toscaparser.utils.gettextutils import _
from toscaparser.artifacts import Artifact

log = logging.getLogger('tosca')


class NodeTemplate(EntityTemplate):
    '''Node template from a Tosca profile.'''
    def __init__(self, name, topology_template, custom_def=None,
                 available_rel_tpls=None, available_rel_types=None):
        node_templates = topology_template._tpl_nodetemplates()
        super(NodeTemplate, self).__init__(name, node_templates[name],
                                           'node_type',
                                           custom_def)
        self.topology_template = topology_template
        self.templates = node_templates
        self.custom_def = custom_def
        self.related = {}
        self.relationship_tpl = []
        self.available_rel_tpls = available_rel_tpls or []
        self.available_rel_types = available_rel_types or []
        self._relationships = None
        self.sub_mapping_tosca_template = None
        self._artifacts = None
        self._instance_keys = None

    @property
    def relationships(self):
        """
        returns [(RelationshipTemplate: requires_tpl_dict)]
        """
        if self._relationships is None:
            self._relationships = []
            # self.requirements is from the yaml
            requires = self.requirements
            if requires and isinstance(requires, list):
                for r in requires:
                    reqDef, relTpl = self._get_explicit_relationship(r)
                    if relTpl:
                        self._relationships.append( (relTpl, r) )
        return self._relationships

    def _getRequirementDefinition(self, requirementName):
        parent_reqs = self.type_definition.get_all_requirements()
        defaultDef = dict(relationship=dict(type = "tosca.relationships.Root"))
        if parent_reqs:
            for req_dict in parent_reqs:
                if requirementName in req_dict:
                    # 3.7.3 Requirement definition p.122
                    # if present, this will be either the name of the relationship type
                    # or a dictionary containing "type"
                    reqDef = req_dict[requirementName]
                    if isinstance(reqDef, dict):
                        # normalize 'relationship' key:
                        relDef = reqDef.get('relationship')
                        if not relDef:
                            relDef = dict(type = "tosca.relationships.Root")
                        elif isinstance(relDef, dict):
                            relDef = relDef.copy()
                        else:
                            relDef = dict(type = relDef)
                        reqDef = reqDef.copy()
                        reqDef['relationship'] = relDef
                        return reqDef
                    else:
                        # 3.7.3.2.1 Simple grammar (Capability Type only)
                        defaultDef['capability'] = reqDef
                        return defaultDef
        return defaultDef

    def _get_explicit_relationship(self, req):
        """Handle explicit relationship

        For example,
        - req:
            node: DBMS
            relationship: tosca.relationships.HostedOn

        Returns RelationshipTemplate or None if there was a validation error.

        If no relationship was either assigned or defined by the node's type definition,
        one with type "tosca.relationships.Root" will be returned.
        """
        name, value = next(iter(req.items())) # list only has one item
        typeReqDef = self._getRequirementDefinition(name)
        reqDef = typeReqDef.copy()
        if isinstance(value, dict):
            # see 3.8.2 Requirement assignment p. 140 for value
            reqDef.update(value)
        else:
            reqDef['node'] = value

        relationship = reqDef['relationship']
        relTpl = None
        if isinstance(relationship, dict):
          type = relationship.get('type')
          if not type:
              ExceptionCollector.appendException(
                  MissingRequiredFieldError(
                      what=_('"relationship" used in template '
                             '"%s"') % self.name,
                      required=self.TYPE))
              return reqDef, None
        elif relationship in self.available_rel_types:
            relationship = dict(type = relationship) # it's the name of a type
        else:
            # it's the name of a relationship template
            for tpl in self.available_rel_tpls:
                if tpl.name == relationship:
                  type = tpl.type
                  relTpl = tpl
                  break
            else:
                ExceptionCollector.appendException(
                  ValidationError(message = _('Relationship template "%(relationship)s" was not found'
                       ' for requirement "%(rname)s" of node "%(nname)s".')
                     % {'relationship': relationship, 'rname': name, 'nname': self.name}))
                return reqDef, None

        if not relTpl:
            assert isinstance(relationship, dict) and relationship['type'] == type
            relTpl = RelationshipTemplate(relationship, name, self.custom_def)
        relTpl.source = self

        # XXX support node_filter
        node = reqDef.get('node')
        related_tpl = None
        if node:
            related_tpl = self.topology_template.node_templates.get(node)
            if related_tpl:
                if not relTpl.get_matching_capabilities(related_tpl, reqDef.get('capability')):
                    if 'capability' in reqDef:
                        ExceptionCollector.appendException(
                            ValidationError(message = _('No matching capability "%(cname)s" found'
                              ' on target node "%(tname)s" for requirement "%(rname)s" of node "%(nname)s".')
                            % {'rname': name, 'nname': self.name, 'cname': reqDef['capability'], 'tname': related_tpl.name}))
                    else:
                        ExceptionCollector.appendException(
                            ValidationError(message = _('No capability with a matching target type found'
                              ' on target node "%(tname)s" for requirement "%(rname)s" of node "%(nname)s".')
                            % {'rname': name, 'nname': self.name, 'tname': related_tpl.name}))
                        return reqDef, None
        elif 'capability' not in reqDef and not relTpl.type_definition.valid_target_types:
            ExceptionCollector.appendException(
              ValidationError(message='requirement "%s" of node "%s" must specify a node or a capability' %
                              (name, self.name)))
            return reqDef, None

        if not related_tpl:
            # check if "node" is a node type
            for nodeTemplate in self.topology_template.node_templates.values():
                found = None
                # check if node name is node type
                if not node or nodeTemplate.is_derived_from(node):
                    capability = reqDef.get('capability')
                    # should have already returned an error if this assertion is false
                    assert node or capability or relTpl.type_definition.valid_target_types
                    if relTpl.get_matching_capabilities(nodeTemplate, capability):
                        found = nodeTemplate

                if found:
                    if related_tpl:
                        if "default" in found.directives:
                            continue
                        elif "default" in related_tpl.directives:
                            related_tpl = found
                        else:
                            ExceptionCollector.appendException(
                          ValidationError(message=
      'requirement "%s" of node ""%s" is ambiguous, targets more than one template: "%s" and "%s"' %
                                        (name, self.name, related_tpl.name, found.name)))
                            return reqDef, None
                    else:
                        related_tpl = found

        if related_tpl:
            # if relTpl is in available_rel_tpls what if target and source are already assigned?
            relTpl.target = related_tpl
            related_tpl.relationship_tpl.append(relTpl)
        else:
            ExceptionCollector.appendException(
                ValidationError(message = _('No matching target template found'
                           ' for requirement "%(rname)s" of node "%(nname)s".')
                         % {'rname': name, 'nname': self.name}))
            return reqDef, None
        return reqDef, relTpl

    def get_relationship_template(self):
        """Returns a list of RelationshipTemplates that target this node"""
        return self.relationship_tpl

    @property
    def artifacts(self):
        if self._artifacts is None:
            # node templates can't be imported so we don't need to track their source
            artifacts_tpl = self.entity_tpl.get(self.ARTIFACTS)
            if artifacts_tpl:
                artifacts = {name: Artifact(name, value, self.custom_def)
                    for name, value in artifacts_tpl.items()}
            else:
                artifacts = {}

            # but types can, so we do
            for parent_type in reversed(self.types):
                if not parent_type.defs or not parent_type.defs.get(self.ARTIFACTS):
                    continue
                for name, value in parent_type.defs[self.ARTIFACTS].items():
                    artifacts[name] = Artifact(name, value, self.custom_def, parent_type._source)
            self._artifacts = artifacts
        return self._artifacts

    @property
    def instance_keys(self):
        if self._instance_keys is None:
          self._instance_keys = map(lambda k: [k] if isinstance(k, str) else k,
            self.type_definition.get_value(self.INSTANCE_KEYS, self.entity_tpl, parent=True) or [])
        return self._instance_keys

    def validate(self, tosca_tpl=None):
        if not self.type_definition:
            return
        self._validate_capabilities()
        self._validate_requirements()
        self._validate_instancekeys()
        self.artifacts

    def _validate_requirements(self):
        type_requires = self.type_definition.get_all_requirements()
        allowed_reqs = ["template"]
        if type_requires:
            for treq in type_requires:
                for key, value in treq.items():
                    allowed_reqs.append(key)
                    if isinstance(value, dict):
                        for key in value:
                            allowed_reqs.append(key)

        requires = self.type_definition.get_value(self.REQUIREMENTS,
                                                  self.entity_tpl)
        if requires:
            if not isinstance(requires, list):
                ExceptionCollector.appendException(
                    TypeMismatchError(
                        what='"requirements" of template "%s"' % self.name,
                        type='list'))
            else:
                for req in requires:
                    for r1, value in req.items():
                        if isinstance(value, dict):
                            self._validate_requirements_keys(value)
                            self._validate_requirements_properties(value)
                        allowed_reqs.append(r1)
                    self._common_validate_field(req, allowed_reqs,
                                                'requirements')

    def _validate_requirements_properties(self, requirements):
        # TODO(anyone): Only occurrences property of the requirements is
        # validated here. Validation of other requirement properties are being
        # validated in different files. Better to keep all the requirements
        # properties validation here.
        for key, value in requirements.items():
            if key == 'occurrences':
                self._validate_occurrences(value)
                break

    def _validate_occurrences(self, occurrences):
        DataEntity.validate_datatype('list', occurrences)
        for value in occurrences:
            DataEntity.validate_datatype('integer', value)
        if len(occurrences) != 2 or not (0 <= occurrences[0] <= occurrences[1]) \
                or occurrences[1] == 0:
            ExceptionCollector.appendException(
                InvalidPropertyValueError(what=(occurrences)))

    def _validate_requirements_keys(self, requirement):
        for key in requirement.keys():
            if key not in self.REQUIREMENTS_SECTION:
                ExceptionCollector.appendException(
                    UnknownFieldError(
                        what='"requirements" of template "%s"' % self.name,
                        field=key))

    def _validate_instancekeys(self):
        template = self.entity_tpl
        msg = (_('keys definition of "%s" must be a list of containing strings or lists') % self.name)
        keys = self.type_definition.get_value(self.INSTANCE_KEYS, template, parent=True) or []
        if not isinstance(keys, list):
            ExceptionCollector.appendException(
                ValidationError(message=msg))
        for key in keys:
            if isinstance(key, list):
                for item in key:
                  if not isinstance(item, str):
                      compoundKeyMsg = _("individual keys in compound keys must be strings")
                      ExceptionCollector.appendException(
                        ValidationError(message=compoundKeyMsg))
            elif not isinstance(key, str):
                ExceptionCollector.appendException(
                    ValidationError(message=msg))

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


from toscaparser.common.exception import ExceptionCollector, TOSCAException
from toscaparser.common.exception import InvalidPropertyValueError
from toscaparser.common.exception import MissingRequiredFieldError
from toscaparser.common.exception import TypeMismatchError
from toscaparser.common.exception import ValidationError
from toscaparser.common.exception import InvalidOccurrences
from toscaparser.dataentity import DataEntity
from toscaparser.elements.statefulentitytype import StatefulEntityType
from toscaparser.entity_template import EntityTemplate
from toscaparser.relationship_template import RelationshipTemplate
from toscaparser.utils.gettextutils import _
from toscaparser.artifacts import Artifact
from toscaparser.activities import ConditionClause
from toscaparser.elements.nodetype import NodeType
from toscaparser.elements.entity_type import Namespace

log = logging.getLogger('tosca')


class NodeTemplate(EntityTemplate):
    '''Node template from a Tosca profile.'''
    def __init__(self, name, topology_template, custom_def=None,
                 available_rel_tpls=None):
        node_templates = topology_template._tpl_nodetemplates()
        ExceptionCollector.near = f' in node template "{name}"'
        self.topology_template = topology_template
        super(NodeTemplate, self).__init__(name, node_templates[name],
                                           'node_type',
                                           custom_def)
        self.templates = node_templates
        self.custom_def = custom_def
        self.related = {}
        self.relationship_tpl = []
        self.available_rel_tpls = available_rel_tpls or {}
        self._relationships = None
        self.substitution = None
        self._artifacts = None
        self._instance_keys = None
        self._all_requirements = None
        self._missing_requirements = None

    def _should_validate_properties(self):
        tosca_template = self.topology_template.tosca_template
        if tosca_template and not tosca_template.verify:
            return False
        for name in ("select", "substitute"):
            if name in self.directives:
                return False
        # if we're in a nested topology and we're the root node, defer validation till substitution
        root_topology = tosca_template and tosca_template.topology_template
        if root_topology and root_topology is not self.topology_template:
            if self.name in ("_substitution_mapping", self.topology_template._tpl_substitution_mappings().get("node")):
                return False
        return super()._should_validate_properties()

    @property
    def all_requirements(self):   # external api, unused
        """
        returns [(name, requires_tpl_dict)]
        """
        if self._all_requirements is None:
            self._all_requirements = []
            # self.requirements is from the yaml
            requires = self.requirements
            type_requirements = self.type_definition.requirement_definitions
            names = []
            if requires and isinstance(requires, list):
                for r in requires:
                    name, value = next(iter(r.items())) # list only has one item
                    names.append(name)
                    if isinstance(value, str):
                        value = dict(node=value)
                    self._all_requirements.append((name, value))

            # add requirements on the type definition that were not defined by the template
            for name, req_on_type in type_requirements.items():
                if name not in names:
                    self._all_requirements.append((name, {}))
        return self._all_requirements

    @property
    def relationships(self):
        """
        returns [(RelationshipTemplate, original_tpl, requires_tpl_dict)]
        """
        if self._relationships is None:
            self._relationships = []
            self._missing_requirements = {}
            if not self.type_definition:
                return self._relationships
            # self.requirements is from the yaml
            requires = self.requirements
            type_requirements = self.type_definition.requirement_definitions
            names = []

            if self.topology_template.substitution_mappings:
                # if this node_template is substituted one, add or replace the outer node templates requirements
                # (set in substitution.add_relationship)
                substituted = self.topology_template.substitution_mappings._update_requirements(self)
            else:
                substituted = []

            if requires and isinstance(requires, list):
                for r in requires:
                    name, value = next(iter(r.items()))  # list only has one item
                    if name in substituted:
                        continue
                    names.append(name)
                    reqDef, relTpl = self._get_explicit_relationship(name, value)
                    if relTpl:
                        self._relationships.append( (relTpl, r, reqDef) )
                        if self.substitution:
                            # this needs to be called before the substituted node.relationships is called
                            self.substitution.add_relationship(name, value, relTpl)

            # add requirements on the type definition that were not defined by the template
            resolver = self.topology_template.tosca_template and self.topology_template.tosca_template.import_resolver
            for name, req_on_type in type_requirements.items():
                if name not in names and name not in substituted:
                    match = False
                    node = req_on_type.get('node')
                    is_template = node and self.find_node_related_template(node, req_on_type.get("!namespace-node"))
                    if is_template:
                        relTpl = self._relationship_from_req(name, req_on_type, None)
                        if relTpl:
                            match = True
                            self._relationships.append( (relTpl, {name: req_on_type}, req_on_type) )
                    elif resolver:
                        # if we are able to create a RelationshipTemplate, see if the resolver can find a match
                        if isinstance(self.custom_def, Namespace):
                            namespace = self.custom_def.find_namespace(req_on_type.get("!namespace-relationship"))
                        else:
                            namespace = self.custom_def
                        relationship, relTpl, type = self._get_rel_type(req_on_type['relationship'], name, namespace)
                        if relationship and not relTpl:
                            try:
                                ExceptionCollector.pause()
                                relTpl = RelationshipTemplate(relationship, name, namespace)
                            except TOSCAException as e:
                                log.debug(f"relationship %s isn't valid: %s ({req_on_type})", relationship, str(e))
                                relTpl = None
                            finally:
                                ExceptionCollector.resume()
                        if relTpl:
                            relTpl.source = self
                            related_node, related_capability = resolver.find_matching_node(relTpl, name, req_on_type)
                            if related_node:
                                match = True
                                self._set_relationship(related_node, related_capability, relTpl)
                                self._relationships.append( (relTpl, {name: req_on_type}, req_on_type) )
                    if not match and ("occurrences" not in req_on_type or req_on_type["occurrences"][0]):
                        # minimum occurrences is not 0
                        self._missing_requirements[name] = req_on_type
        return self._relationships

    @property
    def missing_requirements(self):
        if self._missing_requirements is None:
            self.relationships # creates self._missing_requirements
        return self._missing_requirements

    def find_node_related_template(self, name, namespace_id=None):
        return self.topology_template.find_node_related_template(name, namespace_id)

    def _get_explicit_relationship(self, name, value):
        """Handle the value of a requirement declared on a node template

        For example,
        - req:
            node: DBMS
            relationship: tosca.relationships.HostedOn

        Returns a requirements dict and either RelationshipTemplate or None if there was a validation error.

        If no relationship was either assigned or defined by the node's type definition,
        one with type "tosca.relationships.Root" will be returned.
        """
        typeReqDef = self.type_definition.get_requirement_definition(name)
        if isinstance(value, dict):
            # see 3.8.2 Requirement assignment p. 140 for value
            node = value.get("node")
            reqDef = NodeType.merge_requirement_definition(typeReqDef, value)
            for key in ["node", "capability", "relationship"]:
                if key in value:  # don't use type's namespace
                    reqDef.pop(f"!namespace-{key}", None)
        else:
            reqDef = typeReqDef.copy()
            reqDef['node'] = value
            reqDef.pop("!namespace-node", None)
            node = value
        return reqDef, self._relationship_from_req(name, reqDef, node)

    def _get_rel_type(self, relationship, name, namespace):
        relTpl = None
        if isinstance(relationship, dict):
            type = relationship.get('type')
            if not type:
                ExceptionCollector.appendException(
                    MissingRequiredFieldError(
                        what=_('"relationship" used in template '
                              '"%s"') % self.name,
                        required=self.TYPE))
                return None, None, None
        elif relationship in self.available_rel_tpls:
            tpl = self.available_rel_tpls[relationship]
            type = tpl.type
            relTpl = tpl
        elif (relationship in namespace
                or relationship in StatefulEntityType.TOSCA_DEF):
            # it's the name of a type
            type = relationship
            relationship = dict(type = relationship)
        else:
            ExceptionCollector.appendException(
              ValidationError(message = _('Relationship template or type "%(relationship)s" was not found'
                    ' for requirement "%(rname)s" of node "%(nname)s".')
                  % {'relationship': relationship, 'rname': name, 'nname': self.name}))
            return None, None, None
        return relationship, relTpl, type

    def _find_matching_node(self, relTpl, req_name, nodetype, req_def, node_filter):
        # nodetype will be a global names if possible
        related_node = None
        related_capability = None
        capability = req_def.get('capability')
        for nodeTemplate in self.topology_template.node_templates.values():
            found = None
            found_cap = None
            # check if node name is node type
            if not nodetype or nodeTemplate.is_derived_from(nodetype):
                if capability or relTpl.type_definition.valid_target_types:
                    capabilities = relTpl.get_matching_capabilities(nodeTemplate, capability, req_def)
                    if capabilities:
                        found = nodeTemplate
                        found_cap = capabilities[0] # first is best match
                    else:
                        continue # didn't match capabilities, don't check node_filter
                if node_filter:
                    if nodeTemplate.match_nodefilter(node_filter):
                        found = nodeTemplate
                        if not found_cap:
                            capabilities = relTpl.get_matching_capabilities(nodeTemplate, capability, req_def)
                            assert capabilities
                            found_cap = capabilities[0]
                    else:
                        continue

            if found:
                if related_node:
                    if "default" in found.directives:
                        # this is a default, stick with the first one we found
                        continue
                    elif "default" in related_node.directives:
                        # replace the default node that we had previously found
                        related_node = found
                        related_capability = found_cap
                    else:
                        if node_filter:
                            ExceptionCollector.appendException(
                          ValidationError(message=
      'requirement "%s" of node "%s" is ambiguous, targets more than one template: "%s" and "%s"' %
                                        (req_name, self.name, related_node.name, found.name)))
                        return None, None
                else:
                    related_node = found
                    related_capability = found_cap
        return related_node, related_capability

    def _set_relationship(self, related_node, related_capability, relTpl):
        if self.topology_template.substitution_mappings:
            # the outer topology's node template might have overridden this requirement
            # (in substitution.add_relationship)
            related_node, related_capability = self.topology_template.substitution_mappings.maybe_substitute(related_node, related_capability)
        # if relTpl is in available_rel_tpls what if target and source are already assigned?
        relTpl.target = related_node
        relTpl.capability = related_capability
        related_node.relationship_tpl.append(relTpl)

    def is_replaced_by_outer(self):
        mappings = self.topology_template.substitution_mappings
        return mappings and self.name in mappings._outer_relationships

    def _relationship_from_req(self, name, reqDef, node_on_template):
        namespace = self.custom_def if isinstance(self.custom_def, Namespace) else None
        rel_type_namespace = (namespace.find_namespace(reqDef.get("!namespace-relationship")) 
                              if namespace 
                              else self.custom_def)
        relationship, relTpl, rel_type = self._get_rel_type(reqDef['relationship'], name, rel_type_namespace)
        if relationship is None:
            return None

        if not relTpl:
            assert isinstance(relationship, dict) and relationship['type'] == rel_type, (relationship, rel_type)
            relTpl = RelationshipTemplate(relationship, name, rel_type_namespace)

        relTpl.source = self

        node = reqDef.get('node')
        node_filter = reqDef.get('node_filter')
        capability = reqDef.get('capability')
        related_node = None
        related_capability = None
        if node:
            related_node = self.find_node_related_template(node, reqDef.get("!namespace-node"))
            if related_node:
                capabilities = relTpl.get_matching_capabilities(related_node, capability, reqDef)
                if not capabilities:
                    if capability:
                        ExceptionCollector.appendException(
                            ValidationError(message = _('No matching capability "%(cname)s" found'
                              ' on target node "%(tname)s" for requirement "%(rname)s" of node "%(nname)s".')
                            % {'rname': name, 'nname': self.name, 'cname': capability, 'tname': related_node.name}))
                        return None
                    else:
                        ExceptionCollector.appendException(
                            ValidationError(message = _('No capability with a matching target type found'
                              ' on target node "%(tname)s" for requirement "%(rname)s" of node "%(nname)s".')
                            % {'rname': name, 'nname': self.name, 'tname': related_node.name}))
                        return None
                related_capability = capabilities[0] # first one is best match
        elif not capability and not relTpl.type_definition.valid_target_types and not node_filter:
            min_required = reqDef.get("occurrences", [1])[0]
            if min_required != 0:
                ExceptionCollector.appendException(
                  ValidationError(message='requirement "%s" of node "%s" must specify a node_filter, a node or a capability' %
                                  (name, self.name)))
            # else: not an error if requirement is optional
            return None

        node_type_namespace = (namespace.find_namespace(reqDef.get("!namespace-node"))
                               if namespace
                               else self.custom_def)
        node_typename = node # treat node as a type name
        if not related_node:
            if node_typename:
                nodetype_def = node_type_namespace and node_type_namespace.get(node)
                if nodetype_def:
                    node_typename = NodeType(node, node_type_namespace).global_name
            related_node, related_capability = self._find_matching_node(relTpl, name, node_typename, reqDef, node_filter)
        if related_node:
            self._set_relationship(related_node, related_capability, relTpl)
        resolver = self.topology_template.tosca_template and self.topology_template.tosca_template.import_resolver
        if resolver and resolver.find_matching_node:
            related_node, related_capability = resolver.find_matching_node(relTpl, name, reqDef)
            if related_node and related_node is not relTpl.target:  # match changed or wasn't set before
                self._set_relationship(related_node, related_capability, relTpl)

        if not related_node:
            min_required = reqDef.get("occurrences", [1])[0]
            if min_required == 0:
                return None
            if node:
                if not node_on_template and ("@" in node_typename or node_typename in NodeType.TOSCA_DEF):
                    # not an error if "node" wasn't explicitly declared on the template and "node" referenced a type name
                    msg = None
                else:
                    msg = _('Could not find target template "%(node)s"'
                              ' for requirement "%(rname)s"'
                            ) % {'node': node, 'rname': name}
            else:
                msg = _('No matching target template found'
                           ' for requirement "%(rname)s"'
                           ) % {'rname': name}
            if msg:
                if "default" in self.directives:
                    log.warning(f'{msg} on default node template "{self.name}"')
                else:
                    ExceptionCollector.appendException(
                        ValidationError(message = msg))
            return None
        return relTpl

    def get_relationship_templates(self):
        """Returns a list of RelationshipTemplates that target this node"""
        def include_source(source):
            if source:
                source.topology_template.substitution_mappings
                mappings = source.topology_template.substitution_mappings
                if mappings:
                    if mappings.substituted or source.is_replaced_by_outer():
                        return False
            return True

        return [relTpl for relTpl in self.relationship_tpl if include_source(relTpl.source)]

    @property
    def artifacts(self):
        if self._artifacts is None:
            artifacts = {}
            required_artifacts = {}

            for parent_type in reversed(self.types):
                if not parent_type.defs or not parent_type.defs.get(EntityTemplate.ARTIFACTS):
                    continue
                self.find_artifacts_on_type(parent_type, artifacts, required_artifacts)

            # node templates can't be imported so we don't need to track their source
            artifacts_tpl = self.entity_tpl.get(self.ARTIFACTS)
            if artifacts_tpl:
                artifacts.update({name: Artifact(name, value, self.custom_def)
                    for name, value in artifacts_tpl.items()})

            for name, value in required_artifacts.items():
                typename = value.get("type")
                if isinstance(self.custom_def, Namespace):
                    namespace = self.custom_def.find_namespace(value.pop("!namespace", None))
                    typename = namespace.get_global_name(typename)
                artifact = artifacts.get(name)
                if not artifact:
                    if value.get("required"):
                        ExceptionCollector.appendException(
                          ValidationError(message='required artifact "%s" of type "%s" not defined on node "%s"' %
                              (name, typename, self.name)))
                elif typename and not artifact.is_derived_from(typename):
                    ExceptionCollector.appendException(
                      ValidationError(message='artifact "%s" on node "%s" must be derived from type "%s"' %
                              (name, self.name, typename)))

            self._artifacts = artifacts
        return self._artifacts

    @staticmethod
    def find_artifacts_on_type(parent_type: StatefulEntityType, artifacts: dict, required_artifacts: dict, parent=True):
        artifact_tpls = parent_type.get_value(EntityTemplate.ARTIFACTS, parent=parent, add_namespace=True)
        if not artifact_tpls:
            return
        for name, value in artifact_tpls.items():
            if isinstance(value, dict) and "file" not in value:
                if "type" not in value:
                    ExceptionCollector.appendException(
                            MissingRequiredFieldError(
                                what=f'Artifact "{name}" declared on node type "{parent_type.type}"', required="file"
                            )
                        )
                else:
                        # this is not a full artifact definition so treat this as
                        # specifying that an artifact of a certain type is required
                    required_artifacts[name] = value
            else:
                if isinstance(value, dict) and isinstance(parent_type.custom_def, Namespace):
                    namespace = parent_type.custom_def.find_namespace(value.pop("!namespace", None))
                else:
                    namespace = parent_type.custom_def
                artifacts[name] = Artifact(name, value, namespace, parent_type._source)

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

        requires = self.requirements

        if requires:
            if not isinstance(requires, list):
                ExceptionCollector.appendException(
                    TypeMismatchError(
                        what='"requirements" of template "%s"' % self.name,
                        type='list'))
            else:
                for req in requires:
                    if not isinstance(req, dict):
                        ExceptionCollector.appendException(
                            TypeMismatchError(
                                what='a "requirement" in template "%s"' % self.name,
                                type='dict'))
                        continue
                    if len(req) != 1:
                        what = 'requirement "%s" in template "%s"' % (req, self.name)
                        ExceptionCollector.appendException(InvalidPropertyValueError(what=what))
                        continue

                    for r1, value in req.items():
                        if isinstance(value, dict):
                            self.type_definition._validate_requirements_keys(value,  'template "%s"' % self.name)
                            self._validate_requirements_properties(value)
                            node_filter = value.get('node_filter')
                            if node_filter:
                                self._validate_nodefilter(node_filter)
                        elif not isinstance(value, str):
                            msg = 'bad value "%s" for requirement "%s" in template "%s"' % (value, r1, self.name)
                            ExceptionCollector.appendException(ValidationError(message=msg))

                    # disable this check to allow node templates to define additional requirements
                    # self._common_validate_field(req, allowed_reqs, 'requirements')

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
        if not isinstance(occurrences, list) or len(occurrences) != 2:
            ExceptionCollector.appendException(
                InvalidOccurrences(what=(occurrences), why="not a list with 2 items"))
            return
        if isinstance(DataEntity.validate_datatype('integer', occurrences[0]), int):
            if occurrences[1] != "UNBOUNDED":
                if isinstance(DataEntity.validate_datatype('integer', occurrences[1]), int):
                    if not (0 <= occurrences[0] <= occurrences[1]) or occurrences[1] == 0:
                        ExceptionCollector.appendException(
                            InvalidOccurrences(what=(occurrences), why="invalid range"))

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

    def _validate_nodefilter_filter(self, node_filter, cap_label=''):
        if cap_label:
            name = 'capability "%s" on nodefilter on template "%s"' % (cap_label, self.name)
        else:
            name = 'nodefilter on template "%s"' % self.name
        return self.validate_filter(node_filter, name)

    @staticmethod
    def validate_filter(node_filter, name):
        valid = True
        if not isinstance(node_filter, dict):
            ExceptionCollector.appendException(
                TypeMismatchError(
                    what=name,
                    type='dict'))
            return False
        if 'properties' in node_filter:
            propfilters = node_filter['properties']
            if not isinstance(propfilters, list):
                ExceptionCollector.appendException(
                    TypeMismatchError(
                        what='"properties" of %s' % name,
                        type='list'))
                return False
            for filter in propfilters:
                if not isinstance(filter, dict):
                    ExceptionCollector.appendException(
                        TypeMismatchError(
                            what='filter in %s' % name,
                            type='dict'))
                    valid = False
                    continue
                if len(filter) != 1:
                    msg = _('Invalid %s: only one property allowed per filter condition') % name
                    ExceptionCollector.appendException(ValidationError(message=msg))
                    valid = False
                    continue
                # XXX validate filter condition
        return valid

    def _validate_nodefilter(self, node_filter):
        valid = True
        if not self._validate_nodefilter_filter(node_filter):
            return False

        capfilters = node_filter.get('capabilities')
        if capfilters:
            if not isinstance(capfilters, list):
                ExceptionCollector.appendException(
                    TypeMismatchError(
                        what='"capabilities" of nodefilter in template "%s"' % self.name,
                        type='list'))
                return False
            for capfilter in capfilters:
                if not isinstance(capfilter, dict):
                    ExceptionCollector.appendException(
                        TypeMismatchError(
                            what='capabilities list item on nodefilter in template "%s"' % self.name,
                            type='dict'))
                    valid = False
                    continue
                if len(capfilter) != 1:
                    msg = _('Invalid nodefilter on template "%s": only one capability name per list item') % self.name
                    ExceptionCollector.appendException(ValidationError(message=msg))
                    valid = False
                    continue
                name, filter = list(capfilter.items())[0]
                if not self._validate_nodefilter_filter(filter, name):
                    valid = False
        return valid

    @staticmethod
    def _match_filter(entity, node_filter):
        filters = node_filter.get('properties') or []
        props = entity.get_properties()
        for condition in filters:
            assert isinstance(condition, dict)
            key, value = list(condition.items())[0]
            if key not in props:
                return False
            prop = props[key]
            propvalue = prop.value
            if isinstance(value, dict):
                if 'eval' in value or 'q' in value:
                    continue
                if not ConditionClause(key, value, prop.type).evaluate({key:propvalue}):
                    return False
            elif propvalue != value: # simple match
                return False
        return True

    def match_nodefilter(self, node_filter):
        if 'properties' in node_filter:
            if not self._match_filter(self, node_filter):
                return False
        capfilters = node_filter.get('capabilities')
        if capfilters:
            assert isinstance(capfilters, list)
            capabilities = self.get_capabilities()
            for capfilter in capfilters:
                assert isinstance(capfilter, dict)
                name, filter = list(capfilter.items())[0]
                cap = capabilities.get(name)
                if not cap:
                    return False
                if not self._match_filter(cap, filter):
                    return False
            return True
        return False

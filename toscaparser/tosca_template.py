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
import os

from toscaparser.common.exception import ExceptionCollector
from toscaparser.common.exception import InvalidTemplateVersion
from toscaparser.common.exception import MissingRequiredFieldError
from toscaparser.common.exception import UnknownFieldError
from toscaparser.common.exception import ValidationError
from toscaparser.elements.entity_type import update_definitions, EntityType, Namespace
from toscaparser.extensions.exttools import ExtTools
import toscaparser.imports
from toscaparser.prereq.csar import CSAR
from toscaparser.repositories import Repository
from toscaparser.topology_template import TopologyTemplate
from toscaparser.substitution_mappings import SubstitutionMappings
from toscaparser.utils.gettextutils import _
import toscaparser.utils.yamlparser

# TOSCA template key names
SECTIONS = (DEFINITION_VERSION, NAMESPACE, TEMPLATE_NAME,
            TOPOLOGY_TEMPLATE, TEMPLATE_AUTHOR, TEMPLATE_VERSION,
            DESCRIPTION, IMPORTS, DSL_DEFINITIONS, TYPES, NODE_TYPES,
            RELATIONSHIP_TYPES, RELATIONSHIP_TEMPLATES,
            CAPABILITY_TYPES, ARTIFACT_TYPES, DATA_TYPES, INTERFACE_TYPES,
            POLICY_TYPES, GROUP_TYPES, REPOSITORIES) = \
           ('tosca_definitions_version', 'namespace',
            'template_name', 'topology_template', 'template_author',
            'template_version', 'description', 'imports', 'dsl_definitions',
            'types', 'node_types', 'relationship_types', 'relationship_templates',
            'capability_types', 'artifact_types', 'data_types',
            'interface_types', 'policy_types', 'group_types', 'repositories')
# Sections that are specific to individual template versions
SPECIAL_SECTIONS = (METADATA, DECORATORS) = ('metadata', 'decorators')

log = logging.getLogger("tosca.model")

YAML_LOADER = toscaparser.utils.yamlparser.load_yaml


class ToscaTemplate(object):
    exttools = ExtTools()
    strict = False

    MAIN_TEMPLATE_VERSIONS = ['tosca_simple_yaml_1_0',
                              'tosca_simple_yaml_1_2',
                              'tosca_simple_yaml_1_3']

    VALID_TEMPLATE_VERSIONS = MAIN_TEMPLATE_VERSIONS + exttools.get_versions()

    ADDITIONAL_SECTIONS = {'tosca_simple_yaml_1_0': SPECIAL_SECTIONS,
                           'tosca_simple_yaml_1_2': SPECIAL_SECTIONS,
                           'tosca_simple_yaml_1_3': SPECIAL_SECTIONS}

    ADDITIONAL_SECTIONS.update(exttools.get_sections())

    '''Load the template data.'''
    def __init__(
        self,
        path=None,
        parsed_params=None,
        a_file=True,
        yaml_dict_tpl=None,
        import_resolver=None,
        verify=True,
        fragment="",
        base_dir=None,
    ):
        ExceptionCollector.start()
        self.a_file = a_file
        self.input_path = None
        self.path = None
        self.fragment = fragment
        self.tpl = {}
        self.import_resolver = import_resolver
        self.nested_tosca_tpls = {}
        self.nested_topologies = {}
        self.verify = verify
        if path:
            self.input_path = path
            # don't validate or load if yaml_dict_tpl was set
            if yaml_dict_tpl:
                self.path = path
            else:
                self.path = self._get_path(path)
                self.tpl = YAML_LOADER(self.path, self.a_file)
        self.base_dir = base_dir or (self.path and os.path.dirname(self.path)) or "."

        if yaml_dict_tpl:
            self.tpl = yaml_dict_tpl

        if not path and not yaml_dict_tpl:
            ExceptionCollector.appendException(
                ValueError(_('No path or yaml_dict_tpl was provided. '
                             'There is nothing to parse.')))

        self.topology_template = None
        if self.tpl:
            self.parsed_params = parsed_params
            self._validate_field()
            self.version = self._tpl_version()
            EntityType.reset_caches()
            self.description = self._tpl_description()
            all_custom_defs = self.load_imports()
            self.topology_template = self._topology_template(all_custom_defs)
            self._repositories = None
            if self.topology_template.tpl:
                self.inputs = self._inputs()
                self.relationship_templates = self._relationship_templates()
                self.outputs = self._outputs()
                self.policies = self._policies()
                self._handle_nested_tosca_templates_with_topology(all_custom_defs.all_namespaces)

        if verify:
            if self.tpl and self.topology_template.tpl:
                # now that all the node templates have been loaded we can validated the relationships between them
                self.validate_relationships()
            ExceptionCollector.stop()
            self.raise_validation_errors()
        else:
            ExceptionCollector.stop()

    def validate_relationships(self):
        self.topology_template.validate_relationships(self.strict)
        for nested in self.nested_topologies.values():
            nested.validate_relationships(self.strict)

    def _topology_template(self, custom_defs):
        return TopologyTemplate(self._tpl_topology_template(),
                                custom_defs,
                                self.parsed_params,
                                self)

    def _inputs(self):
        return self.topology_template.inputs

    @property
    def nodetemplates(self):
        return self.topology_template.nodetemplates

    def _relationship_templates(self):
        return self.topology_template.relationship_templates

    def _outputs(self):
        return self.topology_template.outputs

    def _tpl_version(self):
        return self.tpl.get(DEFINITION_VERSION)

    def _tpl_description(self):
        desc = self.tpl.get(DESCRIPTION)
        if desc:
            return desc.rstrip()

    def _tpl_imports(self):
        return self.tpl.get(IMPORTS)

    @property
    def repositories(self):
        if self._repositories is None:
            repositories = {}
            assert self.topology_template
            for filename, (tosca_tpl, namespace_id) in self.nested_tosca_tpls.items():
                repositories.update(tosca_tpl.get(REPOSITORIES) or {})
            repositories.update(self.tpl.get(REPOSITORIES) or {})
            # we need to update the template because it is passed directly to the import loader
            self.tpl[REPOSITORIES] = repositories
            if self.import_resolver:
                get_repository = self.import_resolver.get_repository
            else:
                get_repository = Repository
            self._repositories = {name:get_repository(name, val) for name, val in repositories.items()}
        return self._repositories

    def _tpl_relationship_templates(self):
        topology_template = self._tpl_topology_template()
        return topology_template.get(RELATIONSHIP_TEMPLATES)

    def _tpl_topology_template(self):
        return self.tpl.get(TOPOLOGY_TEMPLATE)

    def _policies(self):
        return self.topology_template.policies

    def load_imports(self):
        """Handle custom types defined in imported template files

        This method loads the custom type definitions referenced in "imports"
        section of the TOSCA YAML template.
        """
        imported_types = Namespace({}, None, self.path or "")
        imports_loader = toscaparser.imports.ImportsLoader(
            None, self.path, imported_types, self.tpl.get("repositories"),
            self.import_resolver, self.base_dir
        )
        _source, namespace_id = imports_loader.get_source(self.base_dir,
                                self.path, None, "", self.tpl.get(NAMESPACE))
        imported_types.source_info = _source
        imported_types.namespace_id = namespace_id
        # resolver could have changed this
        imported_types.shared_namespace = bool(_source.get("namespace_uri"))

        imports = self.tpl.get("imports") 
        if imports:
            log.debug("loading imports")
            imported_types = imports_loader.resolver.load_imports(imports_loader, imports)
            log.debug("finished loading imports")
            self.nested_tosca_tpls = imports_loader.nested_tosca_tpls
        else:
            self.nested_tosca_tpls = {}
        # we don't need to set _source on the root template because local names can't be prefixed
        imports_loader._update_custom_def(self.tpl, imported_types, False)
        return imported_types

    def _handle_nested_tosca_templates_with_topology(self, namespaces):
        ExceptionCollector.near = ""
        assert self.topology_template
        for filename, (tosca_tpl, namespace_id) in self.nested_tosca_tpls.items():
            topology_tpl = tosca_tpl.get(TOPOLOGY_TEMPLATE)
            if topology_tpl:
                custom_types = namespaces[namespace_id]
                self.nested_topologies[filename] = TopologyTemplate(
                                topology_tpl, custom_types, None, self)
        substitutable_topologies = [t for t in self.nested_topologies.values() if t.substitution_mappings]
        assert self.topology_template
        self.topology_template._do_substitutions(substitutable_topologies)
        if self.topology_template.substitution_mappings and not self.topology_template.substitution_mappings.node:
            # create a node template for the root topology's substitution mapping
            self.topology_template.substitution_mappings.substitute(None, None)

    def find_topology_by_namespace_id(self, namespace_id):
        for filename, (tosca_tpl, namespace) in self.nested_tosca_tpls.items():
            if namespace_id == namespace and filename in self.nested_topologies:
                return self.nested_topologies[filename]
        return None

    def _validate_field(self):
        version = self._tpl_version()
        if not version:
            ExceptionCollector.appendException(
                MissingRequiredFieldError(what='Template',
                                          required=DEFINITION_VERSION))
        else:
            self._validate_version(version)
            self.version = version

        for name in self.tpl:
            if (name not in SECTIONS and
               name not in self.ADDITIONAL_SECTIONS.get(version, ())):
                ExceptionCollector.appendException(
                    UnknownFieldError(what='Template', field=name))

    def _validate_version(self, version):
        if version not in self.VALID_TEMPLATE_VERSIONS:
            ExceptionCollector.appendException(
                InvalidTemplateVersion(
                    what=version,
                    valid_versions='", "'. join(self.VALID_TEMPLATE_VERSIONS)))
        else:
            if version not in self.MAIN_TEMPLATE_VERSIONS:
                update_definitions(self.exttools, version, YAML_LOADER)

    def _get_path(self, path):
        if path.lower().endswith('.yaml') or path.lower().endswith('.yml'):
            return path
        elif path.lower().endswith(('.zip', '.csar')):
            # a CSAR archive
            csar = CSAR(path, self.a_file)
            if csar.validate():
                csar.decompress()
                self.a_file = True  # the file has been decompressed locally
                return os.path.join(csar.temp_dir, csar.get_main_template())
        else:
            ExceptionCollector.appendException(
                ValueError(_('"%(path)s" is not a valid file.')
                           % {'path': path}))

    def raise_validation_errors(self):
        if ExceptionCollector.exceptionsCaught():
            if self.input_path:
                raise ValidationError(
                    message=(_('\nThe input "%(path)s" failed validation with '
                               'the following error(s): \n\n\t')
                             % {'path': self.input_path}) +
                    '\n\t'.join(ExceptionCollector.getExceptionsReport()))
            else:
                raise ValidationError(
                    message=_('\nThe pre-parsed input failed validation with '
                              'the following error(s): \n\n\t') +
                    '\n\t'.join(ExceptionCollector.getExceptionsReport()))
        else:
            if self.input_path:
                msg = (_('The input "%(path)s" successfully passed '
                         'validation.') % {'path': self.input_path})
            else:
                msg = _('The pre-parsed input successfully passed validation.')

            log.info(msg)

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

from copy import deepcopy
from toscaparser.common.exception import ExceptionCollector
from toscaparser.common.exception import InvalidTemplateVersion
from toscaparser.common.exception import MissingRequiredFieldError
from toscaparser.common.exception import UnknownFieldError
from toscaparser.common.exception import ValidationError
from toscaparser.elements.entity_type import update_definitions, EntityType
from toscaparser.extensions.exttools import ExtTools
import toscaparser.imports
from toscaparser.prereq.csar import CSAR
from toscaparser.repositories import Repository
from toscaparser.topology_template import TopologyTemplate
from toscaparser.substitution_mappings import SubstitutionMappings
from toscaparser.utils.gettextutils import _
import toscaparser.utils.yamlparser

# TOSCA template key names
SECTIONS = (DEFINITION_VERSION, DEFAULT_NAMESPACE, TEMPLATE_NAME,
            TOPOLOGY_TEMPLATE, TEMPLATE_AUTHOR, TEMPLATE_VERSION,
            DESCRIPTION, IMPORTS, DSL_DEFINITIONS, TYPES, NODE_TYPES,
            RELATIONSHIP_TYPES, RELATIONSHIP_TEMPLATES,
            CAPABILITY_TYPES, ARTIFACT_TYPES, DATA_TYPES, INTERFACE_TYPES,
            POLICY_TYPES, GROUP_TYPES, REPOSITORIES) = \
           ('tosca_definitions_version', 'tosca_default_namespace',
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
    def __init__(self, path=None, parsed_params=None, a_file=True,
                 yaml_dict_tpl=None, import_resolver=None, verify=True, fragment=""):

        ExceptionCollector.start()
        self.a_file = a_file
        self.input_path = None
        self.path = None
        self.fragment = fragment
        self.tpl = None
        self.import_resolver = import_resolver
        self.nested_tosca_tpls = {}
        self.nested_topologies = {}
        if path:
            self.input_path = path
            # don't validate or load if yaml_dict_tpl was set
            if yaml_dict_tpl:
                self.path = path
            else:
                self.path = self._get_path(path)
                self.tpl = YAML_LOADER(self.path, self.a_file)

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
            custom_defs = self._get_all_custom_defs()
            self.topology_template = self._topology_template(custom_defs)
            self._repositories = None
            if self.topology_template.tpl:
                self.inputs = self._inputs()
                self.relationship_templates = self._relationship_templates()
                self.outputs = self._outputs()
                self.policies = self._policies()
                self._handle_nested_tosca_templates_with_topology(custom_defs)
                # now that all the node templates have been loaded we can validated the relationships between them
                self.topology_template.validate_relationships(self.strict)
                for nested in self.nested_topologies.values():
                    nested.validate_relationships(self.strict)

        ExceptionCollector.stop()
        if verify:
            self.verify_template()

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
            assert self.topology_template # sets self.nested_tosca_tpls
            for filename, tosca_tpl in self.nested_tosca_tpls.items():
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

    def get_type_sections(self):
        return [TYPES, NODE_TYPES, CAPABILITY_TYPES, RELATIONSHIP_TYPES,
                 DATA_TYPES, ARTIFACT_TYPES, INTERFACE_TYPES, POLICY_TYPES, GROUP_TYPES]

    def _get_all_custom_defs(self):
        custom_defs, nested_tosca_tpls = self._get_custom_defs(self.tpl, self.path, self.path)
        self.nested_tosca_tpls = nested_tosca_tpls
        # Handle custom types defined in current template file
        for type_def in self.get_type_sections():
            inner_custom_types = self.tpl.get(type_def)
            if inner_custom_types:
                custom_defs.update(inner_custom_types)
        return custom_defs

    def _get_custom_defs(self, tpl, path, root_path):
        custom_defs_final = {}
        tosca_tpls = {}
        custom_defs, nested_imports = self.load_imports(path, tpl, root_path)
        for filename, (import_tpl, root_path, prefix) in nested_imports.items():
            tosca_tpls[filename] = import_tpl
            import_defs, nested_tosca_tpls = self._get_custom_defs(import_tpl, filename, root_path)
            custom_defs_final.update(import_defs)
            tosca_tpls.update(nested_tosca_tpls)
        if custom_defs:
            custom_defs_final.update(custom_defs)
        return custom_defs_final, tosca_tpls

    def load_imports(self, path, tpl, root_path):
        """Handle custom types defined in imported template files

        This method loads the custom type definitions referenced in "imports"
        section of the TOSCA YAML template.
        """
        imports = tpl.get("imports")
        if not imports:
            return {}, {}

        type_sections = self.get_type_sections()
        imports_loader = toscaparser.imports.ImportsLoader(
            None, path, type_sections, self.tpl.get("repositories"),
            self.import_resolver, root_path
        )
        imports_loader.resolver.load_imports(imports_loader, imports)
        # nested_tosca_tpls is Dict[file_path, (tpl, repository_name, prefix)] of the imported templates
        nested_tosca_tpls = imports_loader.get_nested_tosca_tpls()
        # custom defs are merged together (with possibly namespace prefix)
        custom_defs = imports_loader.get_custom_defs()
        return custom_defs, nested_tosca_tpls

    def _handle_nested_tosca_templates_with_topology(self, custom_types):
        ExceptionCollector.near = ""
        for filename, tosca_tpl in self.nested_tosca_tpls.items():
            topology_tpl = tosca_tpl.get(TOPOLOGY_TEMPLATE)
            if topology_tpl:
                custom_types = custom_types.copy()
                custom_types.update(tosca_tpl.get('node_types', {}))  # XXX isn't this redundant?
                self.nested_topologies[filename] = TopologyTemplate(
                                topology_tpl, custom_types, None, self)
        substitutable_topologies = [t for t in self.nested_topologies.values() if t.substitution_mappings]
        self.topology_template._do_substitutions(substitutable_topologies)
        if self.topology_template.substitution_mappings and not self.topology_template.substitution_mappings.node:
            # create a node template for the root topology's substitution mapping
            self.topology_template.substitution_mappings.substitute(None, None)

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

    def verify_template(self):
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
